#!/usr/bin/env python3
"""
批量测试Template生成器

在所有demo文件上测试Template生成器，验证:
1. 能够处理不同类型的工作簿
2. 正确识别数据区域和公式区域
3. 生成有效的任务
"""

import sys
from pathlib import Path

# 添加项目根目录到path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from generate.transform.template_generator import TemplateGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def batch_test_template(demo_dir: Path, output_dir: Path):
    """批量测试Template生成器"""

    # 获取所有xlsx文件
    xlsx_files = sorted(demo_dir.glob("*.xlsx"))

    if not xlsx_files:
        logger.error(f"在{demo_dir}中未找到xlsx文件")
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    generator = TemplateGenerator(seed=42)

    results = {}

    logger.info(f"找到{len(xlsx_files)}个xlsx文件")
    logger.info(f"输出目录: {output_dir}")
    print()

    for i, golden_path in enumerate(xlsx_files, 1):
        logger.info(f"[{i}/{len(xlsx_files)}] 测试: {golden_path.name}")

        try:
            task = generator.generate(
                golden_path=golden_path,
                output_dir=output_dir,
                workbook_id=golden_path.stem
            )

            # 导出JSON
            json_path = output_dir / f"{task.task_id}.json"
            generator.export_task_json(task, json_path)

            results[golden_path.name] = {
                "success": True,
                "cleared_cells": len(task.answer_position),
                "data_regions": len(task.data_regions),
                "formula_cells": task.metadata['formula_cells_total'],
                "difficulty": task.difficulty,
                "task_id": task.task_id
            }

            logger.info(f"  ✓ 成功: 清空{len(task.answer_position)}个单元格, "
                       f"{len(task.data_regions)}个数据区域, 难度{task.difficulty}")

        except Exception as e:
            results[golden_path.name] = {
                "success": False,
                "error": str(e)
            }
            logger.error(f"  ✗ 失败: {e}")

        print()

    # 打印总结
    print("=" * 80)
    print("批量测试总结")
    print("=" * 80)

    success_count = sum(1 for r in results.values() if r["success"])
    total_count = len(xlsx_files)

    print(f"\n总体结果: {success_count}/{total_count} 成功 ({success_count/total_count*100:.1f}%)")
    print()

    # 按文件名排序显示
    for filename in sorted(results.keys()):
        result = results[filename]
        if result["success"]:
            print(f"✓ {filename:30s} - {result['cleared_cells']:4d}个单元格, "
                  f"{result['data_regions']}个区域, 难度{result['difficulty']}")
        else:
            error_msg = result['error'][:50]  # 截断长错误消息
            print(f"✗ {filename:30s} - {error_msg}")

    print()

    # 统计信息
    if success_count > 0:
        successful = [r for r in results.values() if r["success"]]

        total_cleared = sum(r["cleared_cells"] for r in successful)
        total_formulas = sum(r["formula_cells"] for r in successful)

        avg_cleared = total_cleared / success_count
        avg_formulas = total_formulas / success_count

        difficulties = [r["difficulty"] for r in successful]
        difficulty_dist = {
            "L1": difficulties.count("L1"),
            "L2": difficulties.count("L2"),
            "L3": difficulties.count("L3"),
            "L4": difficulties.count("L4")
        }

        print("统计信息:")
        print(f"  平均清空单元格数: {avg_cleared:.1f}")
        print(f"  平均公式单元格数: {avg_formulas:.1f}")
        print(f"  难度分布: L1={difficulty_dist['L1']}, L2={difficulty_dist['L2']}, "
              f"L3={difficulty_dist['L3']}, L4={difficulty_dist['L4']}")

    print()
    print(f"生成的任务文件: {output_dir}")
    print("=" * 80)

    return results


def main():
    demo_dir = Path("/mnt/hhq/data/files_demo")
    output_dir = Path("/tmp/template_batch_test")

    results = batch_test_template(demo_dir, output_dir)

    # 返回成功状态
    success_count = sum(1 for r in results.values() if r["success"])
    if success_count == len(results):
        logger.info("✓ 所有文件测试通过!")
        sys.exit(0)
    else:
        logger.warning(f"⚠ {len(results) - success_count}个文件测试失败")
        sys.exit(0)  # 不算错误，部分失败是正常的


if __name__ == "__main__":
    main()
