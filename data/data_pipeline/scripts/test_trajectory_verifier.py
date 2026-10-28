#!/usr/bin/env python3
"""
测试S5轨迹验证器

用法：
    # 单个轨迹验证
    python scripts/test_trajectory_verifier.py /path/to/task_dir

    # 批量验证
    python scripts/test_trajectory_verifier.py /path/to/trajectories_dir --batch

    # 保存验证报告
    python scripts/test_trajectory_verifier.py /path/to/trajectories_dir --batch --output report.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from dataclasses import asdict

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from verify.trajectory_verifier import TrajectoryVerifier

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def test_single_trajectory(task_dir: str):
    """测试单个轨迹验证"""
    logger.info(f"Testing single trajectory: {task_dir}")

    verifier = TrajectoryVerifier()
    result = verifier.verify(task_dir)

    print("\n" + "="*60)
    print(f"VERIFICATION RESULT: {result.task_id}")
    print("="*60)
    print(f"Approved: {result.approved}")
    print(f"Accuracy: {result.accuracy:.3f}")
    print(f"  - Modification: {result.modification_accuracy:.3f}")
    print(f"  - Regression: {result.regression_accuracy:.3f}")
    print(f"Recalculated: {result.recalculated}")
    print(f"Protected Violations: {result.protected_violation}")
    print(f"Formula Family Consistent: {result.formula_family_consistent}")
    print(f"Invariants Failed: {result.invariants_failed}")
    print(f"Excel Errors: {result.excel_errors}")
    print(f"Style Preserved: {result.style_preserved}")

    if result.visualization_tier1_passed is not None:
        print(f"Visualization Tier 1: {result.visualization_tier1_passed}")

    if not result.approved:
        print(f"\nRejection Reasons:")
        for reason in result.rejection_reasons:
            print(f"  - {reason}")

    print("="*60)

    return result.approved


def test_batch_trajectories(trajectories_dir: str, output_path: str = None):
    """测试批量轨迹验证"""
    logger.info(f"Testing batch trajectories: {trajectories_dir}")

    verifier = TrajectoryVerifier()
    report = verifier.verify_batch(trajectories_dir)

    print("\n" + "="*60)
    print("BATCH VERIFICATION REPORT")
    print("="*60)
    print(f"Total: {report['total']}")
    print(f"Approved: {report['approved']} ({report['approval_rate']:.1%})")
    print(f"Rejected: {report['rejected']}")

    if report['rejection_breakdown']:
        print(f"\nRejection Breakdown:")
        for reason, count in sorted(report['rejection_breakdown'].items(),
                                    key=lambda x: -x[1]):
            print(f"  {reason}: {count}")

    print(f"\nPer-Task Results:")
    for task_id, result in sorted(report['results'].items()):
        status = "✓ PASS" if result.approved else "✗ FAIL"
        print(f"  {status} {task_id} (accuracy={result.accuracy:.3f})")
        if not result.approved:
            print(f"       Reasons: {', '.join(result.rejection_reasons)}")

    print("="*60)

    # 保存报告到文件
    if output_path:
        output_file = Path(output_path)

        # 转换VerificationResult为dict
        serializable_report = {
            "total": report["total"],
            "approved": report["approved"],
            "rejected": report["rejected"],
            "approval_rate": report["approval_rate"],
            "rejection_breakdown": report["rejection_breakdown"],
            "results": {
                task_id: asdict(result)
                for task_id, result in report["results"].items()
            }
        }

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(serializable_report, f, indent=2)

        logger.info(f"Report saved to: {output_file}")

    return report['approval_rate'] >= 0.95  # 目标：95%通过率


def main():
    parser = argparse.ArgumentParser(
        description="Test S5 Trajectory Verifier",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 单个轨迹验证
    python scripts/test_trajectory_verifier.py generated_tasks/debugging_demo_001

    # 批量验证
    python scripts/test_trajectory_verifier.py trajectories/test_batch --batch

    # 保存报告
    python scripts/test_trajectory_verifier.py trajectories/test_batch --batch \\
        --output trajectories/test_batch/verification_report.json
        """
    )

    parser.add_argument(
        'path',
        help='Task directory (single mode) or trajectories directory (batch mode)'
    )

    parser.add_argument(
        '--batch',
        action='store_true',
        help='Batch mode: verify all trajectories in directory'
    )

    parser.add_argument(
        '--output',
        help='Output path for verification report (batch mode only)'
    )

    args = parser.parse_args()

    # 验证路径存在
    path = Path(args.path)
    if not path.exists():
        logger.error(f"Path not found: {args.path}")
        sys.exit(1)

    # 执行验证
    try:
        if args.batch:
            success = test_batch_trajectories(args.path, args.output)
        else:
            success = test_single_trajectory(args.path)

        sys.exit(0 if success else 1)

    except Exception as e:
        logger.error(f"Verification failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
