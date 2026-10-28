#!/usr/bin/env python3
"""
批量验证轨迹脚本

用法:
    python scripts/verify_trajectories.py trajectories/oracle_test_batch
"""

import sys
import json
import logging
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from verify.trajectory_verifier import TrajectoryVerifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/verify_trajectories.py <trajectories_dir>")
        sys.exit(1)

    trajectories_dir = sys.argv[1]

    logger.info(f"Verifying trajectories in: {trajectories_dir}")

    verifier = TrajectoryVerifier()
    report = verifier.verify_batch(trajectories_dir)

    # 保存报告
    report_path = Path(trajectories_dir) / "verification_report.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"\nVerification report saved to: {report_path}")

    # 打印摘要
    logger.info("\n" + "="*60)
    logger.info("VERIFICATION SUMMARY")
    logger.info("="*60)
    logger.info(f"Total trajectories: {report['total']}")
    logger.info(f"✓ Approved: {report['approved']} ({report['approval_rate']:.1%})")
    logger.info(f"✗ Rejected: {report['rejected']} ({1-report['approval_rate']:.1%})")

    if report['rejection_breakdown']:
        logger.info("\nRejection reasons:")
        for reason, count in sorted(report['rejection_breakdown'].items(),
                                     key=lambda x: x[1], reverse=True):
            logger.info(f"  - {reason}: {count}")


if __name__ == "__main__":
    main()
