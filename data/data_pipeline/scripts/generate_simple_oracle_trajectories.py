#!/usr/bin/env python3
"""
简单Oracle轨迹生成器

为测试S5验证器，生成最简单的oracle轨迹：
- 直接复制golden.xlsx作为output.xlsx
- 这代表"完美执行"的轨迹

用法：
    python scripts/generate_simple_oracle_trajectories.py generated_tasks/test_batch_fm
    python scripts/generate_simple_oracle_trajectories.py generated_tasks/test_batch_fm --output trajectories/test_fm
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def generate_oracle_trajectory(task_dir: Path, output_dir: Path = None):
    """
    为单个任务生成oracle轨迹

    Args:
        task_dir: 任务目录（包含task.json, input.xlsx, golden.xlsx）
        output_dir: 输出目录（如果为None，则在原地生成）
    """
    task_id = task_dir.name

    # 检查必需文件
    golden_path = None
    for pattern in ['*_golden.xlsx', 'golden.xlsx']:
        matches = list(task_dir.glob(pattern))
        if matches:
            golden_path = matches[0]
            break

    if not golden_path or not golden_path.exists():
        logger.warning(f"✗ {task_id}: golden.xlsx not found")
        return False

    # 确定输出位置
    if output_dir:
        target_dir = output_dir / task_id
        target_dir.mkdir(parents=True, exist_ok=True)

        # 复制所有文件到目标目录
        for file in task_dir.glob('*'):
            if file.is_file():
                shutil.copy2(file, target_dir / file.name)

        output_path = target_dir / 'output.xlsx'
        golden_source = target_dir / golden_path.name
    else:
        target_dir = task_dir
        output_path = task_dir / 'output.xlsx'
        golden_source = golden_path

    # 生成oracle轨迹：复制golden作为output
    shutil.copy2(golden_source, output_path)

    logger.info(f"✓ {task_id}: Oracle trajectory generated at {output_path}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Generate simple oracle trajectories for testing S5 verifier",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 在原地生成（修改原任务目录）
    python scripts/generate_simple_oracle_trajectories.py generated_tasks/test_batch_fm

    # 生成到独立目录
    python scripts/generate_simple_oracle_trajectories.py generated_tasks/test_batch_fm \\
        --output trajectories/test_fm_oracle
        """
    )

    parser.add_argument(
        'tasks_dir',
        help='Directory containing task subdirectories'
    )

    parser.add_argument(
        '--output',
        help='Output directory for trajectories (optional, defaults to in-place)'
    )

    args = parser.parse_args()

    # 验证任务目录
    tasks_path = Path(args.tasks_dir)
    if not tasks_path.exists():
        logger.error(f"Tasks directory not found: {args.tasks_dir}")
        sys.exit(1)

    # 准备输出目录
    output_path = Path(args.output) if args.output else None
    if output_path:
        output_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output directory: {output_path}")

    # 扫描任务目录
    task_dirs = [d for d in tasks_path.iterdir() if d.is_dir()]

    if not task_dirs:
        logger.error(f"No task directories found in {args.tasks_dir}")
        sys.exit(1)

    logger.info(f"Found {len(task_dirs)} tasks")

    # 生成轨迹
    success_count = 0
    for task_dir in task_dirs:
        if generate_oracle_trajectory(task_dir, output_path):
            success_count += 1

    # 总结
    logger.info(f"\n{'='*60}")
    logger.info(f"GENERATION SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Total: {len(task_dirs)}")
    logger.info(f"Success: {success_count}")
    logger.info(f"Failed: {len(task_dirs) - success_count}")
    logger.info(f"Success rate: {success_count/len(task_dirs)*100:.1f}%")

    if output_path:
        logger.info(f"\nTrajectories saved to: {output_path}")

    sys.exit(0 if success_count == len(task_dirs) else 1)


if __name__ == '__main__':
    main()
