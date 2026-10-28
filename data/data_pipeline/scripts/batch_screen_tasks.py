#!/usr/bin/env python3
"""
批量筛选生成的任务

对S2生成的任务进行批量筛选:
1. Template任务筛选
2. Debugging任务筛选
3. 混合任务筛选

输出筛选报告和通过的任务列表
"""

import sys
from pathlib import Path

# 添加项目根目录到path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
import json
import argparse
from screen.task_screener import TaskScreener
from screen.unique_solution_validator import UniqueSolutionValidator
from screen.contamination_scanner import ContaminationScanner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def batch_screen_tasks(
    task_dir: Path,
    output_dir: Path,
    official_dataset_path: Path = None,
    check_contamination: bool = True
):
    """批量筛选任务"""

    if not task_dir.exists():
        logger.error(f"任务目录不存在: {task_dir}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    # 创建验证器组件
    unique_solution_validator = UniqueSolutionValidator()

    contamination_scanner = None
    if check_contamination and official_dataset_path:
        if official_dataset_path.exists():
            logger.info(f"加载污染扫描器: {official_dataset_path}")
            contamination_scanner = ContaminationScanner(str(official_dataset_path))
        else:
            logger.warning(f"官方数据集路径不存在,跳过污染检查: {official_dataset_path}")
            check_contamination = False
    elif check_contamination:
        logger.warning("未提供官方数据集路径,跳过污染检查")
        check_contamination = False

    # 创建任务筛选器
    screener = TaskScreener(
        contamination_scanner=contamination_scanner,
        unique_solution_validator=unique_solution_validator
    )

    # 查找所有任务JSON文件
    template_files = sorted(task_dir.glob("*_template_*.json"))
    debugging_files = sorted(task_dir.glob("*_debugging_*.json"))

    total_files = len(template_files) + len(debugging_files)

    if total_files == 0:
        logger.error(f"未找到任务文件: {task_dir}")
        return

    logger.info(f"找到{total_files}个任务文件")
    logger.info(f"  Template: {len(template_files)}")
    logger.info(f"  Debugging: {len(debugging_files)}")
    print()

    # 筛选Template任务
    template_report_path = output_dir / "template_screening_report.json"
    template_stats = None

    if template_files:
        logger.info("="*80)
        logger.info("筛选Template任务")
        logger.info("="*80)

        template_stats = screener.batch_screen(
            task_dir=task_dir,
            output_path=template_report_path,
            check_unique_solution=True,
            check_contamination=check_contamination,
            check_difficulty=True
        )

        logger.info(f"Template筛选报告: {template_report_path}")
        print()

    # 筛选Debugging任务
    debugging_report_path = output_dir / "debugging_screening_report.json"
    debugging_stats = None

    if debugging_files:
        logger.info("="*80)
        logger.info("筛选Debugging任务")
        logger.info("="*80)

        debugging_stats = screener.batch_screen(
            task_dir=task_dir,
            output_path=debugging_report_path,
            check_unique_solution=True,
            check_contamination=check_contamination,
            check_difficulty=True
        )

        logger.info(f"Debugging筛选报告: {debugging_report_path}")
        print()

    # 生成汇总报告
    summary = {
        "total_tasks": total_files,
        "template": {
            "total": len(template_files),
            "stats": template_stats
        },
        "debugging": {
            "total": len(debugging_files),
            "stats": debugging_stats
        }
    }

    summary_path = output_dir / "screening_summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # 打印汇总
    print()
    print("="*80)
    print("筛选汇总")
    print("="*80)
    print()

    if template_stats:
        print(f"Template任务: {template_stats['passed']}/{template_stats['total']} 通过 "
              f"({template_stats['passed']/template_stats['total']*100:.1f}%)")

    if debugging_stats:
        print(f"Debugging任务: {debugging_stats['passed']}/{debugging_stats['total']} 通过 "
              f"({debugging_stats['passed']/debugging_stats['total']*100:.1f}%)")

    total_passed = (template_stats['passed'] if template_stats else 0) + \
                   (debugging_stats['passed'] if debugging_stats else 0)

    print()
    print(f"总计: {total_passed}/{total_files} 通过 ({total_passed/total_files*100:.1f}%)")
    print()
    print(f"汇总报告: {summary_path}")
    print("="*80)

    return summary


def main():
    parser = argparse.ArgumentParser(description="批量筛选S2生成的任务")
    parser.add_argument(
        "task_dir",
        type=Path,
        help="任务JSON文件所在目录"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/screening_results"),
        help="筛选报告输出目录 (默认: /tmp/screening_results)"
    )
    parser.add_argument(
        "--official-dataset",
        type=Path,
        help="官方数据集路径(用于污染检测)"
    )
    parser.add_argument(
        "--skip-contamination",
        action="store_true",
        help="跳过污染检测"
    )

    args = parser.parse_args()

    batch_screen_tasks(
        task_dir=args.task_dir,
        output_dir=args.output_dir,
        official_dataset_path=args.official_dataset,
        check_contamination=not args.skip_contamination
    )


if __name__ == "__main__":
    main()
