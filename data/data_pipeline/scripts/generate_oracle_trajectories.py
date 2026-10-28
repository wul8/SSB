#!/usr/bin/env python3
"""
生成Oracle轨迹

将golden工作簿复制为output工作簿，创建完美的参考轨迹用于验证器测试。

用法:
    python scripts/generate_oracle_trajectories.py generated_tasks/test_batch_fm trajectories/oracle_test_batch
"""

import sys
import shutil
import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


def generate_oracle_trajectory(task_dir: Path, output_dir: Path):
    """
    为单个任务生成oracle轨迹

    Args:
        task_dir: 任务目录（包含task.json, input.xlsx, golden.xlsx）
        output_dir: 输出目录
    """
    task_id = task_dir.name

    # 读取task.json
    task_json_path = task_dir / "task.json"
    if not task_json_path.exists():
        logger.warning(f"Skipping {task_id}: task.json not found")
        return False

    with open(task_json_path) as f:
        task_json = json.load(f)

    # 检查文件存在性
    input_workbook = task_json.get("input_workbook")
    golden_workbook = task_json.get("golden_workbook")

    if not input_workbook or not golden_workbook:
        logger.warning(f"Skipping {task_id}: missing workbook filenames in task.json")
        return False

    input_path = task_dir / input_workbook
    golden_path = task_dir / golden_workbook

    if not input_path.exists():
        logger.warning(f"Skipping {task_id}: {input_workbook} not found")
        return False

    if not golden_path.exists():
        logger.warning(f"Skipping {task_id}: {golden_workbook} not found")
        return False

    # 创建输出目录
    trajectory_dir = output_dir / task_id
    trajectory_dir.mkdir(parents=True, exist_ok=True)

    # 复制文件
    shutil.copy2(task_json_path, trajectory_dir / "task.json")
    shutil.copy2(input_path, trajectory_dir / "input.xlsx")
    shutil.copy2(golden_path, trajectory_dir / "golden.xlsx")
    shutil.copy2(golden_path, trajectory_dir / "output.xlsx")  # Oracle: output = golden

    logger.info(f"✓ Generated oracle trajectory: {task_id}")
    return True


def main():
    if len(sys.argv) != 3:
        print("Usage: python scripts/generate_oracle_trajectories.py <tasks_dir> <output_dir>")
        print("Example: python scripts/generate_oracle_trajectories.py generated_tasks/test_batch_fm trajectories/oracle_test_batch")
        sys.exit(1)

    tasks_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    if not tasks_dir.exists():
        logger.error(f"Tasks directory not found: {tasks_dir}")
        sys.exit(1)

    logger.info(f"Generating oracle trajectories from: {tasks_dir}")
    logger.info(f"Output directory: {output_dir}")

    # 扫描所有任务目录
    task_dirs = [d for d in tasks_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]

    logger.info(f"Found {len(task_dirs)} task directories")

    success_count = 0
    for task_dir in sorted(task_dirs):
        if generate_oracle_trajectory(task_dir, output_dir):
            success_count += 1

    logger.info("\n" + "="*60)
    logger.info(f"Generated {success_count}/{len(task_dirs)} oracle trajectories")
    logger.info(f"Output directory: {output_dir}")
    logger.info("="*60)


if __name__ == "__main__":
    main()
