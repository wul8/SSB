#!/usr/bin/env python3
"""
测试Template生成器

验证Template生成器能够:
1. 识别数据区域
2. 清空数据单元格(保留公式和格式)
3. 生成自然语言指令
4. 生成有效的input/golden/task.json
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


def test_template_generator(demo_dir: Path, output_dir: Path):
    """测试Template生成器"""

    # 使用0_ref_0.xlsx作为测试文件（有公式的财务模型）
    golden_path = demo_dir / "0_ref_0.xlsx"

    if not golden_path.exists():
        logger.error(f"测试文件不存在: {golden_path}")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    generator = TemplateGenerator(seed=42)

    logger.info(f"测试Template生成器...")
    logger.info(f"Golden文件: {golden_path}")
    logger.info(f"输出目录: {output_dir}")
    print()

    try:
        task = generator.generate(
            golden_path=golden_path,
            output_dir=output_dir
        )

        # 导出JSON
        json_path = output_dir / f"{task.task_id}.json"
        generator.export_task_json(task, json_path)

        # 验证输出文件存在
        assert task.input_path.exists(), f"Input文件不存在: {task.input_path}"
        assert task.golden_path.exists(), f"Golden文件不存在: {task.golden_path}"
        assert json_path.exists(), f"JSON文件不存在: {json_path}"

        # 验证基本属性
        assert len(task.answer_position) > 0, "没有清空任何单元格"
        assert len(task.data_regions) > 0, "没有识别到数据区域"
        assert task.difficulty in ["L1", "L2", "L3", "L4"], f"无效的难度: {task.difficulty}"

        logger.info(f"✓ 测试通过!")
        logger.info(f"  任务ID: {task.task_id}")
        logger.info(f"  难度: {task.difficulty}")
        logger.info(f"  清空单元格数: {len(task.answer_position)}")
        logger.info(f"  数据区域数: {len(task.data_regions)}")
        logger.info(f"  公式单元格数: {task.metadata['formula_cells_total']}")

        print()
        print("=" * 80)
        print("生成的任务指令:")
        print("=" * 80)
        print(task.instruction)
        print()
        print("=" * 80)
        print("数据区域:")
        print("=" * 80)
        for i, region in enumerate(task.data_regions, 1):
            print(f"{i}. {region.to_range_str()}")
            print(f"   - 单元格数: {region.cell_count}")
            print(f"   - 描述: {region.description}")
        print("=" * 80)

        return True

    except Exception as e:
        logger.error(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    demo_dir = Path("/mnt/hhq/data/files_demo")
    output_dir = Path("/tmp/template_test")

    success = test_template_generator(demo_dir, output_dir)

    if success:
        logger.info("✓ Template生成器测试通过!")
        sys.exit(0)
    else:
        logger.error("✗ Template生成器测试失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
