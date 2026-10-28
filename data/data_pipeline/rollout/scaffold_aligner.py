#!/usr/bin/env python3
"""
S4 Scaffold对齐检查器

验证生成的轨迹是否严格遵守scaffold规范。

检查项:
1. System prompt是否正确
2. 只使用允许的3个工具: bash, view_xlsx, submit
3. Message角色序列是否合法
4. 工具调用格式是否正确
5. 观察截断是否正确(10000字符限制)
6. Turn数是否在限制内(跟随LLM_ROLLOUT_CONFIG["max_turns"])
"""

import json
import logging
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from rollout.scaffold_common import SYSTEM_PROMPT
from config import LLM_ROLLOUT_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class AlignmentIssue:
    """对齐问题"""
    severity: str  # error, warning
    location: str  # 位置
    issue: str     # 问题描述
    expected: Optional[str] = None  # 期望值
    actual: Optional[str] = None    # 实际值


class ScaffoldAligner:
    """Scaffold对齐检查器"""

    # 与官方SWE-agent scaffold(config/spreadsheet.yaml的system_template)逐字对齐，
    # 直接复用scaffold_common.SYSTEM_PROMPT，避免两处硬编码后再次漂移
    EXPECTED_SYSTEM_PROMPT = SYSTEM_PROMPT

    ALLOWED_TOOLS = {'bash', 'view_xlsx', 'submit'}
    ALLOWED_ROLES = {'system', 'user', 'assistant', 'tool'}
    # 轨迹生成统一为LLM rollout后，turn上限跟随LLM_ROLLOUT_CONFIG而非
    # SCAFFOLD_CONFIG["max_turns"]=50（那是官方scaffold硬约束，rollout为
    # 兼容deepseek-v4-pro等模型放宽到了100，见config.py注释）
    MAX_TURNS = LLM_ROLLOUT_CONFIG["max_turns"]
    MAX_OBSERVATION_LENGTH = 10000

    def __init__(self):
        self.issues: List[AlignmentIssue] = []

    def check(self, trajectory_path: Path) -> List[AlignmentIssue]:
        """
        检查轨迹是否符合scaffold规范

        Args:
            trajectory_path: 轨迹JSON路径

        Returns:
            对齐问题列表
        """
        self.issues = []

        with open(trajectory_path, 'r', encoding='utf-8') as f:
            trajectory = json.load(f)

        messages = trajectory.get('messages', [])

        # 1. 检查system prompt
        self._check_system_prompt(messages)

        # 2. 检查消息序列
        self._check_message_sequence(messages)

        # 3. 检查工具使用
        self._check_tool_usage(messages)

        # 4. 检查观察长度
        self._check_observation_length(messages)

        # 5. 检查turn数
        self._check_turn_count(messages)

        # 6. 检查scaffold字段
        self._check_scaffold_field(trajectory)

        return self.issues

    def _check_system_prompt(self, messages: List[Dict]):
        """检查system prompt是否正确"""
        if not messages:
            self.issues.append(AlignmentIssue(
                severity='error',
                location='messages[0]',
                issue='Missing system message'
            ))
            return

        first_msg = messages[0]
        if first_msg.get('role') != 'system':
            self.issues.append(AlignmentIssue(
                severity='error',
                location='messages[0]',
                issue='First message must be system',
                expected='system',
                actual=first_msg.get('role')
            ))
            return

        content = first_msg.get('content', '')
        if content.strip() != self.EXPECTED_SYSTEM_PROMPT.strip():
            self.issues.append(AlignmentIssue(
                severity='error',
                location='messages[0].content',
                issue='System prompt does not match expected scaffold',
                expected=self.EXPECTED_SYSTEM_PROMPT[:100] + '...',
                actual=content[:100] + '...'
            ))

    def _check_message_sequence(self, messages: List[Dict]):
        """检查消息序列是否合法"""
        if len(messages) < 2:
            self.issues.append(AlignmentIssue(
                severity='error',
                location='messages',
                issue='Trajectory must have at least system + user messages',
                expected='≥2',
                actual=str(len(messages))
            ))
            return

        # 检查第二条消息应该是user
        if messages[1].get('role') != 'user':
            self.issues.append(AlignmentIssue(
                severity='error',
                location='messages[1]',
                issue='Second message must be user',
                expected='user',
                actual=messages[1].get('role')
            ))

        # 检查角色序列: system, user, (assistant, tool)*, assistant(final submit)
        for idx, msg in enumerate(messages[2:], start=2):
            role = msg.get('role')
            if role not in self.ALLOWED_ROLES:
                self.issues.append(AlignmentIssue(
                    severity='error',
                    location=f'messages[{idx}].role',
                    issue=f'Invalid role: {role}',
                    expected=str(self.ALLOWED_ROLES),
                    actual=role
                ))

            # 检查assistant/tool交替出现
            if idx >= 3:
                prev_role = messages[idx - 1].get('role')
                if role == 'assistant' and prev_role not in ['user', 'tool']:
                    self.issues.append(AlignmentIssue(
                        severity='warning',
                        location=f'messages[{idx}]',
                        issue=f'Assistant message should follow user or tool, not {prev_role}'
                    ))
                elif role == 'tool' and prev_role != 'assistant':
                    self.issues.append(AlignmentIssue(
                        severity='error',
                        location=f'messages[{idx}]',
                        issue=f'Tool message must follow assistant, not {prev_role}'
                    ))

    def _check_tool_usage(self, messages: List[Dict]):
        """检查工具使用是否符合规范"""
        for idx, msg in enumerate(messages):
            if msg.get('role') != 'assistant':
                continue

            # 检查tool_calls格式
            tool_calls = msg.get('tool_calls', [])
            if not tool_calls:
                # Assistant消息可以没有tool_calls(最后的submit)
                continue

            for tc_idx, tc in enumerate(tool_calls):
                tool_name = tc.get('name')
                if tool_name not in self.ALLOWED_TOOLS:
                    self.issues.append(AlignmentIssue(
                        severity='error',
                        location=f'messages[{idx}].tool_calls[{tc_idx}].name',
                        issue=f'Invalid tool: {tool_name}',
                        expected=str(self.ALLOWED_TOOLS),
                        actual=tool_name
                    ))

                # 检查arguments字段存在
                if 'arguments' not in tc:
                    self.issues.append(AlignmentIssue(
                        severity='error',
                        location=f'messages[{idx}].tool_calls[{tc_idx}]',
                        issue='Missing arguments field in tool call'
                    ))

    def _check_observation_length(self, messages: List[Dict]):
        """检查观察是否正确截断"""
        for idx, msg in enumerate(messages):
            if msg.get('role') != 'tool':
                continue

            content = msg.get('content', '')
            if len(content) > self.MAX_OBSERVATION_LENGTH:
                # 检查是否有<elided_chars>标记
                if '<elided_chars>' not in content:
                    self.issues.append(AlignmentIssue(
                        severity='error',
                        location=f'messages[{idx}].content',
                        issue=f'Observation exceeds {self.MAX_OBSERVATION_LENGTH} chars but not truncated',
                        expected=f'≤{self.MAX_OBSERVATION_LENGTH} or with <elided_chars>',
                        actual=f'{len(content)} chars, no truncation marker'
                    ))

    def _check_turn_count(self, messages: List[Dict]):
        """检查turn数是否超限"""
        # Turn = assistant消息数量
        assistant_count = sum(1 for msg in messages if msg.get('role') == 'assistant')

        if assistant_count > self.MAX_TURNS:
            self.issues.append(AlignmentIssue(
                severity='error',
                location='messages',
                issue=f'Turn count exceeds limit',
                expected=f'≤{self.MAX_TURNS}',
                actual=str(assistant_count)
            ))

    def _check_scaffold_field(self, trajectory: Dict):
        """检查scaffold字段"""
        scaffold = trajectory.get('scaffold')
        if scaffold != 'spreadsheet_bench_v2':
            self.issues.append(AlignmentIssue(
                severity='warning',
                location='scaffold',
                issue='Scaffold field should be "spreadsheet_bench_v2"',
                expected='spreadsheet_bench_v2',
                actual=str(scaffold)
            ))

    def generate_report(self, issues: List[AlignmentIssue]) -> Dict:
        """生成检查报告"""
        by_severity = {'error': [], 'warning': []}
        for issue in issues:
            by_severity[issue.severity].append(issue)

        report = {
            'total_issues': len(issues),
            'by_severity': {
                'error': len(by_severity['error']),
                'warning': len(by_severity['warning']),
            },
            'passed': len(by_severity['error']) == 0,
            'issues': [
                {
                    'severity': i.severity,
                    'location': i.location,
                    'issue': i.issue,
                    'expected': i.expected,
                    'actual': i.actual
                }
                for i in issues
            ]
        }

        return report


def main():
    """测试用主函数"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # 测试文件
    trajectory_path = Path("/tmp/oracle_test/0_ref_0_template_2824__oracle_v1.json")

    if not trajectory_path.exists():
        logger.error(f"轨迹文件不存在: {trajectory_path}")
        return

    # 执行检查
    aligner = ScaffoldAligner()
    issues = aligner.check(trajectory_path)

    # 生成报告
    report = aligner.generate_report(issues)

    print("\n" + "="*80)
    print("Scaffold对齐检查报告")
    print("="*80)
    print(f"轨迹文件: {trajectory_path.name}")
    print(f"总问题数: {report['total_issues']}")
    print(f"  错误: {report['by_severity']['error']}")
    print(f"  警告: {report['by_severity']['warning']}")
    print()
    print(f"检查结果: {'✓ PASS' if report['passed'] else '✗ FAIL'}")
    print()

    if issues:
        print("问题详情:")
        print("-" * 80)
        for issue in issues:
            print(f"[{issue.severity.upper()}] {issue.location}")
            print(f"  问题: {issue.issue}")
            if issue.expected:
                print(f"  期望: {issue.expected}")
            if issue.actual:
                print(f"  实际: {issue.actual}")
            print()

    print("="*80)


if __name__ == "__main__":
    main()
