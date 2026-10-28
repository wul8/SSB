#!/usr/bin/env python3
"""
S4 LLM Rollout轨迹生成器

唯一的轨迹生成路径：不比对input/golden反推操作序列，而是让LLM真正多轮
尝试解这个任务（自己view_xlsx看文件、自己写bash改文件、自己判断何时
submit），产出的thought和tool_calls是LLM真实推理的结果，不是照着已知
答案倒推的解说词。

关键约束(scaffold兼容):
- System prompt必须与SYSTEM_PROMPT逐字一致，否则过不了ScaffoldAligner
- 只能使用bash/view_xlsx/submit三个工具
- LLM的上下文里绝不能出现golden_path/answer_position —— user消息只能
  由task['instruction']+criteria构成，这是GoldenLeakDetector的硬约束，
  也是"让LLM自己解题"这个设计前提

model/api_key留空占位时，generate()直接报错，需要在config.py的
LLM_ROLLOUT_CONFIG中配置model名称并设置对应的API key环境变量。
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import LLM_ROLLOUT_CONFIG
from rollout.scaffold_common import (
    SYSTEM_PROMPT,
    build_user_message,
    render_view_xlsx_observation,
    resolve_output_path,
)

logger = logging.getLogger(__name__)


# 与Anthropic Messages API tools=[...]参数对应的工具schema
TOOL_SCHEMAS = [
    {
        "name": "view_xlsx",
        "description": "View contents of an Excel file. Use mode 'list' to list sheet names, or 'content' (default) to view a sheet's cell values.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the .xlsx file"},
                "mode": {"type": "string", "enum": ["list", "content"], "description": "'list' to list sheets, 'content' to view content (default: content)"},
                "sheet": {"type": "string", "description": "Sheet name to view (default: first visible sheet)"},
                "start_row": {"type": "integer", "description": "Starting row number (1-based)"},
                "end_row": {"type": "integer", "description": "Ending row number (1-based)"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "bash",
        "description": "Execute a bash command to modify the Excel file (e.g. via a Python/openpyxl script).",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to execute"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "submit",
        "description": "Submits the current file.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

# 中转endpoint对不同模型的tool schema格式要求不一致：kimi-k3/deepseek-v4-flash
# 认Anthropic原生格式(name+input_schema)。deepseek-v4-pro此前(2026-08)只认OpenAI
# function-calling格式(type=function+function.{name,parameters})，2026-09-01
# route_b_mimotable_batch1批次复测发现中转endpoint已切换成也认Anthropic原生格式，
# 继续用OpenAI格式请求会100%收到400 "tools[0].***.name: empty string"——
# 已用单轮+多轮tool_use/tool_result的原生格式请求验证多次稳定成功，因此
# 移除deepseek-v4-pro的OpenAI-style特例。如果中转endpoint未来再次变更导致
# 该模型请求全部400，先用相同方式排查是否又需要OpenAI格式。
OPENAI_STYLE_TOOL_MODELS = set()

TOOL_SCHEMAS_OPENAI_STYLE = [
    {
        "type": "function",
        "function": {
            "name": s["name"],
            "description": s["description"],
            "parameters": s["input_schema"],
        },
    }
    for s in TOOL_SCHEMAS
]


def _tool_schemas_for_model(model: str) -> List[Dict]:
    return TOOL_SCHEMAS_OPENAI_STYLE if model in OPENAI_STYLE_TOOL_MODELS else TOOL_SCHEMAS


def _apply_path_subs(text: str, subs: List[Tuple[str, str]], reverse: bool) -> str:
    """把text里的路径文字在real(沙箱真实路径)和display(task.json风格路径)间互换

    reverse=False: display->real，用于LLM发出的bash命令执行前，把它写的
    display路径还原成沙箱真实路径才能真正操作到文件。
    reverse=True: real->display，用于命令输出/view_xlsx observation回显前，
    把真实沙箱路径换回display路径，不让LLM在回显里看到穿帮的真实路径。

    subs是[(real, display), ...]列表，顺序=[input文件对, output文件对, 目录对]——
    文件级替换必须先做，否则目录级替换会先把整段目录前缀吞掉，导致文件级
    的str.replace再也匹配不上完整文件路径。
    """
    for real, display in subs:
        text = text.replace(real, display) if reverse else text.replace(display, real)
    return text


def _append_assistant_turn(api_messages: List[Dict], model: str, response, thought: str, tool_use_blocks: List) -> None:
    """把本轮assistant回复追加进api_messages

    OPENAI_STYLE_TOOL_MODELS的中转端连多轮历史里的消息格式也要求OpenAI
    chat格式(assistant.tool_calls + role="tool")，回传Anthropic原生的
    tool_use/tool_result content block会直接400 —— 不是只换tools参数的
    schema就能跑通，两种模型family要维护两套消息拼装逻辑。
    """
    if model not in OPENAI_STYLE_TOOL_MODELS:
        api_messages.append({"role": "assistant", "content": response.content})
        return

    text_blocks = [b for b in response.content if getattr(b, "type", None) == "text"]
    text_content = "".join(b.text for b in text_blocks) or None
    api_messages.append({
        "role": "assistant",
        "content": text_content,
        "tool_calls": [
            {
                "id": b.id,
                "type": "function",
                "function": {"name": b.name, "arguments": json.dumps(b.input)},
            }
            for b in tool_use_blocks
        ] or None,
    })


def _append_tool_results(api_messages: List[Dict], model: str, results: List[Dict]) -> None:
    """把本轮工具执行结果追加进api_messages

    results: [{"tool_use_id":..., "content":..., "is_error":...}, ...]
    """
    if model not in OPENAI_STYLE_TOOL_MODELS:
        api_messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r["tool_use_id"], "content": r["content"], "is_error": r["is_error"]}
                for r in results
            ],
        })
        return

    for r in results:
        api_messages.append({"role": "tool", "tool_call_id": r["tool_use_id"], "content": r["content"]})


@dataclass
class RolloutStep:
    """rollout过程中记录的一步(assistant tool_call + 对应observation)"""
    tool_name: str
    arguments: Dict
    thought: str
    observation: str
    is_error: bool = False


@dataclass
class RolloutResult:
    """一次完整rollout的结果"""
    success: bool
    steps: List[RolloutStep] = field(default_factory=list)
    error: Optional[str] = None
    submitted_path: Optional[str] = None


class LLMRolloutGenerator:
    """LLM Rollout轨迹生成器"""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        config: Optional[Dict] = None,
    ):
        cfg = config or LLM_ROLLOUT_CONFIG
        self.model = model or cfg["model"]
        self.api_key = api_key or os.environ.get(cfg["api_key_env_var"])
        self.base_url = base_url or cfg["base_url"]
        self.max_turns = cfg["max_turns"]
        self.execution_timeout = cfg["execution_timeout"]
        self.total_execution_timeout = cfg["total_execution_timeout"]
        self.max_tokens = cfg["max_tokens"]
        self.temperature = cfg["temperature"]
        self.reasoning_effort = cfg.get("reasoning_effort")
        self._client = None  # 懒加载,真正调用API时才实例化

    def _get_client(self):
        """懒加载anthropic客户端；缺少model/api_key时直接报错"""
        if not self.model or not self.api_key:
            raise RuntimeError(
                "LLM_ROLLOUT_CONFIG.model/api_key未配置 —— 本次只搭建了框架，"
                "尚未接入真实模型。请在config.py的LLM_ROLLOUT_CONFIG中填入"
                "model名称，并设置对应的API key环境变量后再调用generate()。"
            )
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def generate(
        self,
        task_json_path,
        output_dir,
        sample_id: Optional[str] = None,
    ) -> Dict:
        """
        让LLM真实尝试完成任务，生成rollout轨迹

        Args:
            task_json_path: 任务JSON路径
            output_dir: 输出目录
            sample_id: 样本ID(可选)

        Returns:
            轨迹字典(符合trajectory.schema.json)
        """
        task_json_path = Path(task_json_path)
        output_dir = Path(output_dir)

        logger.info(f"LLM Rollout: {task_json_path}")

        with open(task_json_path, "r", encoding="utf-8") as f:
            task = json.load(f)

        if sample_id is None:
            sample_id = f"{task['task_id']}__rollout_v1"

        if "input_path" in task:
            input_path = Path(task["input_path"])
            # input_path在task.json里可能写的是绝对路径，但文件实际在task.json同级目录
            # 例如：task.json在passed/template/下，input_path写的是/mnt/.../template/xxx_input.xlsx
            # 但实际文件在passed/template/xxx_input.xlsx
            if not input_path.exists():
                # 尝试在task.json同级目录找同名文件
                fallback = task_json_path.parent / input_path.name
                if fallback.exists():
                    input_path = fallback
                else:
                    raise FileNotFoundError(f"input文件不存在: {input_path} (也尝试了 {fallback})")
        else:
            input_path = task_json_path.parent / task["input_workbook"]

        # 在scratch目录里操作副本，绝不改动原始input.xlsx，
        # LLM整个rollout过程中看到的、改动的都是这份副本
        with tempfile.TemporaryDirectory(prefix="llm_rollout_") as scratch_dir:
            scratch_dir = Path(scratch_dir)
            scratch_path = scratch_dir / input_path.name
            shutil.copy2(input_path, scratch_path)

            # display_*是task.json风格/独立输出目录风格的路径文字，只用于LLM
            # 看到的prompt/tool_calls回显，不是真实IO目标——真实IO永远走
            # 下面的scratch_*。output现在对齐官方scaffold的独立输出目录方案
            # (SCAFFOLD_CONFIG["output_path_pattern"])，不再与输入同目录，
            # 因此沙箱里也需要一个独立的output子目录作镜像，否则输入目录的
            # 目录级替换会先吞掉输出目录路径的前缀。
            display_input_path = input_path
            display_output_path = resolve_output_path(task["task_id"])
            scratch_output_dir = scratch_dir / "output"
            scratch_output_dir.mkdir(parents=True, exist_ok=True)
            scratch_output_path = scratch_output_dir / display_output_path.name

            path_subs = [
                (str(scratch_path), str(display_input_path)),
                (str(scratch_output_path), str(display_output_path)),
                (str(scratch_output_dir), str(display_output_path.parent)),
                (str(scratch_dir), str(display_input_path.parent)),
            ]
            protected_dirs = [str(display_input_path.parent), str(display_output_path.parent)]

            rollout_result = self._run_rollout(
                task, scratch_path, scratch_output_path,
                display_input_path, display_output_path,
                scratch_dir, path_subs, protected_dirs,
            )

            # scratch_dir会在with块结束后被清空，LLM最终submit的文件必须
            # 在此之前复制出来，否则S5 TrajectoryVerifier永远拿不到output.xlsx
            if rollout_result.success and rollout_result.submitted_path:
                self._save_verify_bundle(
                    task, task_json_path, input_path, output_dir, sample_id,
                    scratch_dir, rollout_result.submitted_path,
                )

            messages = self._build_messages(task, rollout_result, display_input_path, display_output_path)

        trajectory = self._build_trajectory(sample_id, task, messages, rollout_result)

        trajectory_path = output_dir / f"{sample_id}.json"
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(trajectory_path, "w", encoding="utf-8") as f:
            json.dump(trajectory, f, indent=2, ensure_ascii=False)

        logger.info(f"✓ Rollout轨迹已导出: {trajectory_path}")

        return {
            "trajectory_path": str(trajectory_path),
            "total_steps": len(rollout_result.steps),
        }

    def _save_verify_bundle(
        self,
        task: Dict,
        task_json_path: Path,
        input_path: Path,
        output_dir: Path,
        sample_id: str,
        scratch_dir: Path,
        submitted_path: str,
    ) -> None:
        """把task.json/input.xlsx/golden.xlsx/output.xlsx落盘成一个目录

        供verify.trajectory_verifier.TrajectoryVerifier直接消费(它按此
        四件套的固定文件名读取)。submitted_path是LLM自己报告的路径，可能
        拼错或指向scratch_dir之外的地方，需要校验后才能复制。
        """
        submitted = Path(submitted_path)
        if not submitted.is_absolute():
            submitted = scratch_dir / submitted
        try:
            submitted = submitted.resolve()
            scratch_resolved = scratch_dir.resolve()
        except OSError:
            logger.warning(f"submit路径无法解析，跳过output.xlsx留存: {submitted_path}")
            return
        if scratch_resolved not in submitted.parents or not submitted.exists():
            logger.warning(f"submit路径不在scratch目录内或不存在，跳过output.xlsx留存: {submitted_path}")
            return

        if "golden_path" in task:
            golden_path = Path(task["golden_path"])
            # 与input_path同样的问题：task.json里写的是绝对路径，但文件在同级目录
            if not golden_path.exists():
                fallback = task_json_path.parent / golden_path.name
                if fallback.exists():
                    golden_path = fallback
                else:
                    raise FileNotFoundError(f"golden文件不存在: {golden_path} (也尝试了 {fallback})")
        else:
            golden_path = task_json_path.parent / task["golden_workbook"]

        bundle_dir = output_dir / f"{sample_id}__verify_bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(task_json_path, bundle_dir / "task.json")
        shutil.copy2(input_path, bundle_dir / "input.xlsx")
        shutil.copy2(golden_path, bundle_dir / "golden.xlsx")
        shutil.copy2(submitted, bundle_dir / "output.xlsx")
        logger.info(f"✓ 验证用四件套已保存: {bundle_dir}")

    def _run_rollout(
        self, task: Dict, scratch_path: Path, output_path: Path,
        display_input_path: Path, display_output_path: Path,
        scratch_dir: Path, path_subs: List[Tuple[str, str]], protected_dirs: List[str],
    ) -> RolloutResult:
        """真正的多轮LLM工具调用循环

        LLM的上下文只包含task['instruction']+criteria，不包含golden_path/
        answer_position —— 它必须像真实推理时一样自己发现并修复问题。
        """
        client = self._get_client()

        instruction = task["instruction"]
        if task.get("criteria"):
            instruction += "\n\nSuccess criteria:\n"
            for idx, criterion in enumerate(task["criteria"], 1):
                instruction += f"{idx}. {criterion}\n"

        # LLM从始至终只看到display路径(task.json风格)，真实沙箱路径scratch_path/
        # scratch_dir只用于_execute_tool内部实际IO，两者靠path_subs在执行前后互换
        user_content = build_user_message(instruction, display_input_path, display_output_path)

        api_messages = [{"role": "user", "content": user_content}]
        steps: List[RolloutStep] = []

        for turn in range(self.max_turns):
            extra_body = {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else None
            response = None
            for attempt in range(3):
                response = client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=SYSTEM_PROMPT,
                    tools=_tool_schemas_for_model(self.model),
                    messages=api_messages,
                    extra_body=extra_body,
                )
                if response.content is not None:
                    break
                logger.warning(f"turn {turn} attempt {attempt}: 中转endpoint返回content=None，重试")
            else:
                return RolloutResult(
                    success=False,
                    steps=steps,
                    error=f"turn {turn}: 中转endpoint连续3次返回content=None",
                )

            # reasoning_effort触发的extended thinking以type="thinking"的block返回(内容在
            # .thinking字段，不是.text)，之前只拼接type="text"会导致thought几乎全空——
            # 深度推理的内容白白花了token/时间却没有落进轨迹。
            thought_parts = []
            for b in response.content:
                block_type = getattr(b, "type", None)
                if block_type == "thinking":
                    thought_parts.append(getattr(b, "thinking", "") or "")
                elif block_type == "text":
                    thought_parts.append(b.text)
            thought = "".join(thought_parts)
            tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

            _append_assistant_turn(api_messages, self.model, response, thought, tool_use_blocks)

            if not tool_use_blocks:
                return RolloutResult(
                    success=False,
                    steps=steps,
                    error=f"turn {turn}: LLM未调用任何工具就结束了回复",
                )

            tool_results = []
            for block in tool_use_blocks:
                observation, is_error = self._execute_tool(
                    block.name, block.input, scratch_path, scratch_dir, path_subs, protected_dirs,
                )
                steps.append(RolloutStep(
                    tool_name=block.name,
                    arguments=dict(block.input),
                    thought=thought,
                    observation=observation,
                    is_error=is_error,
                ))
                tool_results.append({"tool_use_id": block.id, "content": observation, "is_error": is_error})

                if block.name == "submit":
                    # submit无参数(tools/submit/config.yaml: arguments: [])，模型不会
                    # 回报路径——submitted_path就是user message里预先公布的output_path
                    return RolloutResult(success=True, steps=steps, submitted_path=str(output_path))

            _append_tool_results(api_messages, self.model, tool_results)

        return RolloutResult(success=False, steps=steps, error=f"超过max_turns({self.max_turns})仍未submit")

    def _execute_tool(
        self, name: str, arguments: Dict, scratch_path: Path, scratch_dir: Path,
        path_subs: List[Tuple[str, str]], protected_dirs: List[str],
    ):
        """执行LLM发出的单个工具调用，返回(observation字符串, is_error)

        bash命令由LLM动态生成、内容不可预知。这里只做超时+scratch
        目录隔离，不做容器级沙箱。
        # TODO: 沙箱加固 —— 生产化前需要评估更强的隔离(容器/受限用户等)

        LLM看到/写的都是display路径(task.json风格)，这里在真正execute前
        把命令文本里的display路径替换回scratch真实路径，执行完再把回显里
        残留的scratch真实路径换回display路径，全程真实IO严格限制在scratch
        目录内。
        """
        if name == "view_xlsx":
            observation = render_view_xlsx_observation(scratch_path, arguments)
            return _apply_path_subs(observation, path_subs, reverse=True), False

        if name == "bash":
            command = arguments.get("command", "")
            real_command = _apply_path_subs(command, path_subs, reverse=False)
            if any(protected_dir in real_command for protected_dir in protected_dirs):
                # 替换后仍残留原始数据集目录路径(输入侧或输出侧)，说明LLM的
                # 写法没被path_subs覆盖到(比如引用了同目录下未知文件名)——
                # 宁可拒绝执行，也不能冒险让命令碰到scratch目录之外的原始文件
                return "Error: command references a path outside the sandboxed working directory", True
            try:
                result = subprocess.run(
                    ["bash", "-c", real_command],
                    capture_output=True,
                    text=True,
                    timeout=self.execution_timeout,
                    cwd=scratch_dir,
                )
            except subprocess.TimeoutExpired:
                return f"Error: command timed out after {self.execution_timeout}s", True

            stdout = _apply_path_subs(result.stdout, path_subs, reverse=True)
            stderr = _apply_path_subs(result.stderr, path_subs, reverse=True)
            if result.returncode != 0:
                return f"Command failed (rc={result.returncode}):\n{stderr[:2000]}", True
            return stdout[:2000] or "Command executed successfully.", False

        if name == "submit":
            return "Submission received.", False

        return f"Error: unknown tool '{name}'", True

    def _build_messages(self, task: Dict, rollout: RolloutResult, display_input_path: Path, display_output_path: Path) -> List[Dict]:
        """把RolloutResult转成符合scaffold格式的messages数组

        user message必须与_run_rollout实际发给API的内容逐字一致，否则导出的
        轨迹文本和真实调用时LLM看到的prompt会出现两个不同版本。
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        instruction = task["instruction"]
        if task.get("criteria"):
            instruction += "\n\nSuccess criteria:\n"
            for idx, criterion in enumerate(task["criteria"], 1):
                instruction += f"{idx}. {criterion}\n"
        user_content = build_user_message(instruction, display_input_path, display_output_path)
        messages.append({"role": "user", "content": user_content})

        for step in rollout.steps:
            messages.append({
                "role": "assistant",
                "thought": step.thought,
                "tool_calls": [{"name": step.tool_name, "arguments": step.arguments}],
            })
            messages.append({"role": "tool", "content": step.observation})

        return messages

    def _build_trajectory(
        self,
        sample_id: str,
        task: Dict,
        messages: List[Dict],
        rollout: RolloutResult,
    ) -> Dict:
        """构建完整的轨迹对象(符合trajectory.schema.json)"""
        step_meta = []
        for idx, step in enumerate(rollout.steps):
            step_meta.append({
                "i": idx,
                "phase": "execute",
                "effective": not step.is_error,
                "tool_name": step.tool_name,
                "cells_written": 0,
                "touched_protected": False,
            })

        total_steps = len(rollout.steps)
        effective_steps = sum(1 for s in rollout.steps if not s.is_error)
        view_xlsx_calls = sum(1 for s in rollout.steps if s.tool_name == "view_xlsx")
        bash_calls = sum(1 for s in rollout.steps if s.tool_name == "bash")
        execution_errors = sum(1 for s in rollout.steps if s.is_error)

        total_chars = sum(len(str(m)) for m in messages)

        return {
            "sample_id": sample_id,
            "task_id": task["task_id"],
            "category": task.get("task_type", task.get("type", "FM")),
            "difficulty": task.get("difficulty", "L2"),
            "source_lineage_id": task.get("workbook_id", "unknown"),
            "scaffold": "spreadsheet_bench_v2",
            "messages": messages,
            "step_meta": step_meta,
            "verifier": {
                "recalculated": False,  # 由S5验证阶段填充
                "modification_accuracy": 0.0,
                "regression_accuracy": 0.0,
                "accuracy": 0.0,
                "protected_violation": 0,
                "invariants_passed": [],
                "invariants_failed": [],
                "excel_errors_in_output": 0,
                "formula_family_consistent": True,
                "style_preserved": True,
            },
            "provenance": {
                "generator": "rollout",
                "model": self.model,
                "golden_leak_check": "pass",  # 由golden_leak_detector.py事后检测填充
                "created_at": datetime.utcnow().isoformat() + "Z",
            },
            "context_stats": {
                "total_steps": total_steps,
                "effective_steps": effective_steps,
                "effective_ratio": effective_steps / total_steps if total_steps > 0 else 0,
                "view_xlsx_calls": view_xlsx_calls,
                "bash_calls": bash_calls,
                "execution_errors": execution_errors,
                "final_context_chars": total_chars,
                "final_context_tokens_est": total_chars // 4,
            },
            "for_negative_pool": False,
            "rollout_success": rollout.success,
            "rollout_error": rollout.error,
        }


def main():
    """测试用主函数：不带真实model/api_key时应清晰报错"""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="LLM Rollout轨迹生成器(测试入口)")
    parser.add_argument("task_json", type=str, help="任务JSON路径")
    parser.add_argument("output_dir", type=str, help="输出目录")
    parser.add_argument("--model", type=str, default=None)
    args = parser.parse_args()

    generator = LLMRolloutGenerator(model=args.model)
    result = generator.generate(Path(args.task_json), Path(args.output_dir))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
