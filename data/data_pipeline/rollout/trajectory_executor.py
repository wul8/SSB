#!/usr/bin/env python3
"""
S4 轨迹执行器

LLMRolloutGenerator生成的轨迹只描述LLM在rollout过程里实际发出的
bash/view_xlsx/submit步骤(且bash已在rollout时真实执行过一次)。本模块
用于按需重放轨迹里记录的bash命令，把input.xlsx变换成output.xlsx，供
S5的TrajectoryVerifier验证一个"照着轨迹机械操作真能做出正确结果"的
output.xlsx，而不是golden.xlsx的复制品。

核心假设(成立原因):
- 轨迹记录时用的input_path字符串(view_xlsx的path参数、bash命令里的
  load_workbook路径)是同一个字符串，替换成scratch副本路径即可让所有
  命令原地操作scratch文件而不污染原始input.xlsx。
"""

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """轨迹执行结果"""
    success: bool
    steps_executed: int
    steps_total: int
    error: Optional[str] = None
    step_errors: List[str] = field(default_factory=list)


class TrajectoryExecutor:
    """真正执行trajectory JSON中的bash步骤，产出output.xlsx"""

    def __init__(self, timeout: int = 60):
        self.timeout = timeout

    def execute(
        self,
        trajectory_path: Path,
        input_path: Path,
        output_path: Path,
    ) -> ExecutionResult:
        """
        Args:
            trajectory_path: LLMRolloutGenerator.generate()产出的轨迹JSON路径
            input_path: 任务的input.xlsx(不会被修改，只读)
            output_path: 执行完成后写出的output.xlsx路径

        Returns:
            ExecutionResult
        """
        trajectory_path = Path(trajectory_path)
        input_path = Path(input_path)
        output_path = Path(output_path)

        with open(trajectory_path, "r", encoding="utf-8") as f:
            trajectory = json.load(f)

        messages = trajectory.get("messages", [])
        bash_steps = self._extract_bash_steps(messages)

        if not bash_steps:
            return ExecutionResult(
                success=False,
                steps_executed=0,
                steps_total=0,
                error="trajectory中没有bash步骤",
            )

        recorded_input_path = self._find_recorded_input_path(messages)
        submit_path = self._find_submit_path(messages)

        # scratch副本: bash命令原地修改这个文件，input.xlsx保持不动
        scratch_path = output_path.parent / f".scratch_{output_path.stem}.xlsx"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, scratch_path)

        # LLM rollout记录的commands里经常出现`cd <录制时的scratch目录> && ...`
        # 加相对文件名的写法，而录制时的那个临时目录早已被清理。这里按录制
        # 路径原样复原目录结构+同名文件镜像，让`cd`和相对路径引用都能落到
        # 真实文件上，不依赖对command文本做字符串替换才能跑通。
        # 只有当录制时的目录已不存在(LLM rollout的临时scratch目录，
        # generate()结束时被清理)才需要重建+镜像文件。
        recorded_dir: Optional[Path] = None
        recorded_name: Optional[str] = None
        created_recorded_dir = False
        if recorded_input_path and not Path(recorded_input_path).parent.exists():
            recorded_dir = Path(recorded_input_path).parent
            recorded_name = Path(recorded_input_path).name
            recorded_dir.mkdir(parents=True, exist_ok=True)
            created_recorded_dir = True
            shutil.copy2(scratch_path, recorded_dir / recorded_name)

        step_errors: List[str] = []
        executed = 0

        try:
            for idx, command in enumerate(bash_steps):
                run_command = command
                if recorded_input_path:
                    run_command = run_command.replace(recorded_input_path, str(scratch_path))

                try:
                    result = subprocess.run(
                        ["bash", "-c", run_command],
                        capture_output=True,
                        text=True,
                        timeout=self.timeout,
                        cwd=str(recorded_dir) if recorded_dir else None,
                    )
                except subprocess.TimeoutExpired:
                    step_errors.append(f"step {idx}: timeout after {self.timeout}s")
                    break

                if result.returncode != 0:
                    step_errors.append(
                        f"step {idx}: rc={result.returncode} stderr={result.stderr[:500]}"
                    )
                    break

                executed += 1

                # 命令可能通过相对路径改的是recorded_dir里的镜像文件，也可能
                # 通过替换后的绝对路径改的是scratch_path，两者不同步的话下一步
                # 会读到旧内容，所以每步后都对齐一次
                if recorded_dir and (recorded_dir / recorded_name).exists():
                    shutil.copy2(recorded_dir / recorded_name, scratch_path)

            success = len(step_errors) == 0

            if success:
                final_source = scratch_path
                if submit_path:
                    candidates = [Path(submit_path)]
                    if recorded_dir:
                        candidates.append(recorded_dir / Path(submit_path).name)
                    for candidate in candidates:
                        if candidate.exists():
                            final_source = candidate
                            break
                shutil.copy2(str(final_source), str(output_path))
                scratch_path.unlink()
            elif scratch_path.exists():
                scratch_path.unlink()

        except Exception as e:
            if scratch_path.exists():
                scratch_path.unlink()
            step_errors.append(f"executor exception: {e}")
            success = False
        finally:
            if created_recorded_dir and recorded_dir and recorded_dir.exists():
                shutil.rmtree(recorded_dir, ignore_errors=True)

        return ExecutionResult(
            success=success,
            steps_executed=executed,
            steps_total=len(bash_steps),
            error=step_errors[0] if step_errors else None,
            step_errors=step_errors,
        )

    def _recalculate_with_libreoffice(self, input_path: Path, output_path: Path) -> bool:
        """用LibreOffice headless转换重算公式缓存值，写出到output_path

        转换到独立临时目录再搬到output_path：LibreOffice按输入文件名生成同名
        .xlsx，如果outdir与输入文件同目录，输出文件名会和输入文件本身撞名。
        """
        import tempfile

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                cmd = [
                    "libreoffice",
                    "--headless",
                    "--invisible",
                    "--norestore",
                    "--convert-to", "xlsx",
                    "--outdir", tmpdir,
                    str(input_path),
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
                if result.returncode != 0:
                    logger.error(f"LibreOffice重算失败: {result.stderr[:500]}")
                    return False

                converted = Path(tmpdir) / (input_path.stem + ".xlsx")
                if not converted.exists():
                    logger.error(f"LibreOffice未产出预期文件: {converted}")
                    return False

                shutil.move(str(converted), str(output_path))
                return output_path.exists()
        except subprocess.TimeoutExpired:
            logger.error("LibreOffice重算超时")
            return False

    def _extract_bash_steps(self, messages: List[Dict]) -> List[str]:
        """按顺序提取所有bash工具调用的command字符串"""
        commands = []
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls", []):
                if tc.get("name") == "bash":
                    command = tc.get("arguments", {}).get("command")
                    if command:
                        commands.append(command)
        return commands

    def _find_recorded_input_path(self, messages: List[Dict]) -> Optional[str]:
        """从view_xlsx调用的path参数取出轨迹记录时使用的input_path文本"""
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls", []):
                if tc.get("name") == "view_xlsx":
                    path = tc.get("arguments", {}).get("path")
                    if path:
                        return path
        return None

    def _find_submit_path(self, messages: List[Dict]) -> Optional[str]:
        """从submit调用的path参数取出LLM声明的最终产物路径

        LLM rollout经常另存为一个新文件名(如xxx_output.xlsx)再submit那个
        新文件——这种情况下scratch_path上不会有最终结果，必须按这个路径去找。
        """
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            for tc in msg.get("tool_calls", []):
                if tc.get("name") == "submit":
                    path = tc.get("arguments", {}).get("path")
                    if path:
                        return path
        return None


def main():
    """测试用主函数"""
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    if len(sys.argv) < 4:
        print("用法: python trajectory_executor.py <trajectory.json> <input.xlsx> <output.xlsx>")
        sys.exit(1)

    executor = TrajectoryExecutor()
    result = executor.execute(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))

    print(f"\n{'='*60}")
    print(f"执行结果: {'✓ 成功' if result.success else '✗ 失败'}")
    print(f"步骤: {result.steps_executed}/{result.steps_total}")
    if result.error:
        print(f"错误: {result.error}")
    print(f"{'='*60}")

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
