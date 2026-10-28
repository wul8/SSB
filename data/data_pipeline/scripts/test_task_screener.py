#!/usr/bin/env python3
"""
测试S3任务筛选器

在生成的Template任务上测试三道筛选:
1. 唯一解验证
2. 污染扫描
3. 难度分级

目标: 验证TaskScreener正确集成各组件
"""

import sys
from pathlib import Path

# 添加项目根目录到path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
import json
from screen.task_screener import TaskScreener
from screen.unique_solution_validator import UniqueSolutionValidator
from screen.contamination_scanner import ContaminationScanner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_task_screener():
    """测试任务筛选器"""

    # 任务目录(批量测试生成的Template任务)
    task_dir = Path("/tmp/template_batch_test")

    if not task_dir.exists():
        logger.error(f"任务目录不存在: {task_dir}")
        logger.info("请先运行 batch_test_template.py 生成测试任务")
        return

    # 查找任务JSON文件
    task_files = sorted(task_dir.glob("*_template_*.json"))

    if not task_files:
        logger.error(f"未找到任务文件: {task_dir}")
        return

    logger.info(f"找到{len(task_files)}个Template任务")

    # 创建验证器组件
    unique_solution_validator = UniqueSolutionValidator()

    # 污染扫描器需要官方数据集路径
    # 这里暂时不提供,测试时会跳过污染检查
    contamination_scanner = None

    # 创建任务筛选器
    screener = TaskScreener(
        contamination_scanner=contamination_scanner,
        unique_solution_validator=unique_solution_validator
    )

    print("\n" + "="*80)
    print("任务筛选器测试")
    print("="*80)
    print()

    # 测试单个任务
    test_task_file = task_files[0]
    logger.info(f"测试任务: {test_task_file.name}")
    print()

    result = screener.screen_task(
        test_task_file,
        check_unique_solution=True,
        check_contamination=False,  # 暂时跳过(需要官方数据集)
        check_difficulty=True
    )

    print()
    print("-" * 80)
    print("筛选结果:")
    print(f"  Task ID: {result.task_id}")
    print(f"  通过: {'✓' if result.passed else '✗'}")
    print(f"  唯一解: {'✓' if result.unique_solution else '✗'}")
    print(f"  污染检测: {'✓' if not result.contaminated else '✗'} (已跳过)")
    print(f"  难度验证: {'✓' if result.difficulty_valid else '✗'}")

    if result.difficulty_adjusted:
        print(f"  难度调整: {result.difficulty_adjusted}")

    if result.issues:
        print("  问题:")
        for issue in result.issues:
            print(f"    - {issue}")

    print("-" * 80)
    print()

    # 批量测试
    logger.info("开始批量筛选...")
    print()

    output_path = Path("/tmp/screening_report.json")

    stats = screener.batch_screen(
        task_dir=task_dir,
        output_path=output_path,
        check_unique_solution=True,
        check_contamination=False,  # 暂时跳过
        check_difficulty=True
    )

    print()
    print(f"详细报告已保存: {output_path}")
    print()

    # 读取并展示部分报告
    with open(output_path, 'r', encoding='utf-8') as f:
        report = json.load(f)

    print("="*80)
    print("筛选报告摘要")
    print("="*80)
    print()

    # 展示前5个任务的详细结果
    print("前5个任务详情:")
    for i, result in enumerate(report['results'][:5], 1):
        status = "✓" if result['passed'] else "✗"
        task_id = result['task_id']

        print(f"{i}. {status} {task_id}")

        if not result['passed'] and result['issues']:
            for issue in result['issues']:
                print(f"     - {issue}")

    print()
    print("="*80)

    return stats


def main():
    stats = test_task_screener()

    if stats:
        # 如果所有任务通过,返回成功
        if stats['failed'] == 0:
            logger.info("✓ 所有任务通过筛选!")
            sys.exit(0)
        else:
            logger.warning(f"⚠ {stats['failed']}/{stats['total']}个任务未通过筛选")
            sys.exit(0)  # 不算错误


if __name__ == "__main__":
    main()
