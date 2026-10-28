#!/usr/bin/env python3
"""
测试Debugging生成器的所有10种错误类型

验证每种错误类型都能成功注入并生成有效任务
"""

import sys
from pathlib import Path

# 添加项目根目录到path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from generate.transform.debugging_generator import DebuggingGenerator
from config import DEBUGGING_ERROR_TYPES

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_all_error_types(demo_dir: Path, output_dir: Path):
    """测试所有10种错误类型"""

    # 使用0_ref_0.xlsx作为测试文件（有公式的文件）
    golden_path = demo_dir / "0_ref_0.xlsx"

    if not golden_path.exists():
        logger.error(f"测试文件不存在: {golden_path}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    generator = DebuggingGenerator(seed=42)

    results = {}

    logger.info(f"开始测试10种错误类型...")
    logger.info(f"Golden文件: {golden_path}")
    logger.info(f"输出目录: {output_dir}")
    print()

    for error_type in DEBUGGING_ERROR_TYPES:
        logger.info(f"测试错误类型: {error_type}")

        try:
            task = generator.generate(
                golden_path=golden_path,
                output_dir=output_dir,
                error_type=error_type
            )

            # 导出JSON
            json_path = output_dir / f"{task.task_id}.json"
            generator.export_task_json(task, json_path)

            # 记录结果
            results[error_type] = {
                "success": True,
                "error_count": len(task.injected_errors),
                "task_id": task.task_id
            }

            logger.info(f"  ✓ 成功: 注入{len(task.injected_errors)}个错误")

        except Exception as e:
            results[error_type] = {
                "success": False,
                "error": str(e)
            }
            logger.error(f"  ✗ 失败: {e}")

        print()

    # 打印总结
    print("=" * 80)
    print("测试总结")
    print("=" * 80)

    success_count = sum(1 for r in results.values() if r["success"])
    total_count = len(DEBUGGING_ERROR_TYPES)

    print(f"\n总体结果: {success_count}/{total_count} 成功")
    print()

    for error_type, result in results.items():
        if result["success"]:
            print(f"✓ {error_type:35s} - {result['error_count']}个错误")
        else:
            print(f"✗ {error_type:35s} - 失败: {result['error']}")

    print()
    print(f"生成的任务文件: {output_dir}")
    print("=" * 80)

    return results


def main():
    demo_dir = Path("/mnt/hhq/data/files_demo")
    output_dir = Path("/tmp/debugging_test_all_types")

    results = test_all_error_types(demo_dir, output_dir)

    # 返回成功状态
    success_count = sum(1 for r in results.values() if r["success"])
    if success_count == len(DEBUGGING_ERROR_TYPES):
        logger.info("✓ 所有错误类型测试通过!")
        sys.exit(0)
    else:
        logger.error(f"✗ {len(DEBUGGING_ERROR_TYPES) - success_count}个错误类型测试失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
