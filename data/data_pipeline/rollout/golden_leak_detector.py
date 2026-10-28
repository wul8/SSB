#!/usr/bin/env python3
"""
S4 Golden泄漏检测器

检查生成的轨迹是否泄漏了golden/answer/target等关键词。

核心检查:
1. 静态关键词扫描: golden, answer, target, correct, solution
2. 文件路径泄漏: golden.xlsx, answer.xlsx, target.xlsx
3. 思考泄漏: thoughts中不应出现golden相关词汇
4. 观察泄漏: observations中不应包含golden路径
"""

import json
import re
import logging
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LeakFinding:
    """泄漏发现"""
    location: str  # message_idx, field
    keyword: str   # 触发的关键词
    context: str   # 上下文片段
    severity: str  # high, medium, low


class GoldenLeakDetector:
    """Golden泄漏检测器"""

    # 高危关键词(完全禁止)
    HIGH_RISK_KEYWORDS = [
        r'\bgolden\.xlsx\b',
        r'\banswer\.xlsx\b',
        r'\btarget\.xlsx\b',
        r'\bgolden_path\b',
        r'\banswer_path\b',
    ]

    # 中危关键词(需要上下文检查)
    MEDIUM_RISK_KEYWORDS = [
        r'\bgolden\b',
        r'\banswer\b',
        r'\btarget\b',
        r'\bcorrect[_ ]answer\b',
        r'\bsolution[_ ]file\b',
    ]

    # 低危关键词(可能误报,需要仔细审查)
    LOW_RISK_KEYWORDS = [
        r'\bcorrect\b',
        r'\bsolution\b',
        r'\bexpected\b',
    ]

    def __init__(self):
        self.findings: List[LeakFinding] = []

    def detect(self, trajectory_path: Path) -> List[LeakFinding]:
        """
        检测轨迹中的golden泄漏

        Args:
            trajectory_path: 轨迹JSON路径

        Returns:
            泄漏发现列表
        """
        self.findings = []

        with open(trajectory_path, 'r', encoding='utf-8') as f:
            trajectory = json.load(f)

        # 检查messages
        messages = trajectory.get('messages', [])
        for idx, msg in enumerate(messages):
            self._check_message(idx, msg)

        # 检查provenance
        provenance = trajectory.get('provenance', {})
        self._check_provenance(provenance)

        return self.findings

    def _check_message(self, idx: int, message: Dict):
        """检查单个message"""
        role = message.get('role')

        # 检查thought字段(只针对assistant消息)
        if role == 'assistant':
            thought = message.get('thought', '')
            if thought:
                self._scan_text(
                    text=thought,
                    location=f"message[{idx}].thought",
                    context_prefix=f"Assistant thought at turn {idx}"
                )

        # 检查content字段(所有角色)
        content = message.get('content', '')
        if content:
            # System和user消息允许包含"correct"等词汇(任务描述需要)
            if role in ['system', 'user']:
                # 只检查高危关键词
                self._scan_text(
                    text=content,
                    location=f"message[{idx}].content",
                    context_prefix=f"{role.capitalize()} content at turn {idx}",
                    keywords_only=self.HIGH_RISK_KEYWORDS
                )
            else:
                # Assistant和tool消息检查所有级别
                self._scan_text(
                    text=content,
                    location=f"message[{idx}].content",
                    context_prefix=f"{role.capitalize()} content at turn {idx}"
                )

        # 检查tool_calls参数
        tool_calls = message.get('tool_calls', [])
        for tc_idx, tc in enumerate(tool_calls):
            args = tc.get('arguments', {})
            args_str = json.dumps(args)
            self._scan_text(
                text=args_str,
                location=f"message[{idx}].tool_calls[{tc_idx}].arguments",
                context_prefix=f"Tool arguments at turn {idx}"
            )

    def _check_provenance(self, provenance: Dict):
        """检查provenance字段"""
        # Provenance可以包含golden_leak_check等元数据字段名
        # 只检查值,不检查键
        for key, value in provenance.items():
            if isinstance(value, str):
                # 跳过元数据字段名本身
                if key in ['golden_leak_check', 'generator']:
                    continue
                self._scan_text(
                    text=value,
                    location=f"provenance.{key}",
                    context_prefix=f"Provenance field {key}"
                )

    def _scan_text(
        self,
        text: str,
        location: str,
        context_prefix: str,
        keywords_only: Optional[List[str]] = None
    ):
        """
        扫描文本中的泄漏关键词

        Args:
            text: 待扫描文本
            location: 位置标识
            context_prefix: 上下文前缀
            keywords_only: 仅检查指定关键词列表(可选)
        """
        if not text:
            return

        # 确定要检查的关键词集合
        if keywords_only:
            keyword_sets = [(keywords_only, 'high')]
        else:
            keyword_sets = [
                (self.HIGH_RISK_KEYWORDS, 'high'),
                (self.MEDIUM_RISK_KEYWORDS, 'medium'),
                (self.LOW_RISK_KEYWORDS, 'low'),
            ]

        for keywords, severity in keyword_sets:
            for pattern in keywords:
                matches = list(re.finditer(pattern, text, re.IGNORECASE))
                for match in matches:
                    # 提取上下文(前后30个字符)
                    start = max(0, match.start() - 30)
                    end = min(len(text), match.end() + 30)
                    context = text[start:end]

                    self.findings.append(LeakFinding(
                        location=location,
                        keyword=match.group(0),
                        context=context,
                        severity=severity
                    ))

    def generate_report(self, findings: List[LeakFinding]) -> Dict:
        """生成检测报告"""
        # 按严重性分组
        by_severity = {'high': [], 'medium': [], 'low': []}
        for finding in findings:
            by_severity[finding.severity].append(finding)

        report = {
            'total_findings': len(findings),
            'by_severity': {
                'high': len(by_severity['high']),
                'medium': len(by_severity['medium']),
                'low': len(by_severity['low']),
            },
            'passed': len(by_severity['high']) == 0,  # 只有高危泄漏才fail
            'findings': [
                {
                    'location': f.location,
                    'keyword': f.keyword,
                    'context': f.context,
                    'severity': f.severity
                }
                for f in findings
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

    # 执行检测
    detector = GoldenLeakDetector()
    findings = detector.detect(trajectory_path)

    # 生成报告
    report = detector.generate_report(findings)

    print("\n" + "="*80)
    print("Golden泄漏检测报告")
    print("="*80)
    print(f"轨迹文件: {trajectory_path.name}")
    print(f"总发现数: {report['total_findings']}")
    print(f"  高危: {report['by_severity']['high']}")
    print(f"  中危: {report['by_severity']['medium']}")
    print(f"  低危: {report['by_severity']['low']}")
    print()
    print(f"检测结果: {'✓ PASS' if report['passed'] else '✗ FAIL'}")
    print()

    if findings:
        print("发现详情:")
        print("-" * 80)
        for f in findings[:10]:  # 只显示前10个
            print(f"[{f.severity.upper()}] {f.location}")
            print(f"  关键词: {f.keyword}")
            print(f"  上下文: ...{f.context}...")
            print()

    print("="*80)


if __name__ == "__main__":
    main()
