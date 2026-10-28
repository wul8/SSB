#!/usr/bin/env python3
"""
测试难度自动修正功能

创建一个测试任务，故意设置错误的难度标注，
然后运行筛选器验证自动修正功能是否正常工作。
"""

import json
import shutil
import tempfile
from pathlib import Path
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from screen.task_screener import TaskScreener


def create_test_task(output_dir: Path) -> Path:
    """创建一个测试任务（故意标注为L2，实际应该是L3）"""
    task_data = {
        "task_id": "test_001_debugging_task",
        "task_type": "debugging",
        "difficulty": "L2",  # 故意标注错误
        "workbook_id": "test_workbook",
        "input_path": "test_input.xlsx",
        "golden_path": "test_golden.xlsx",
        "answer_position": ["A1", "A2", "A3", "B1", "B2"],  # 5个答案位置
        "instruction": "Fix the errors in the spreadsheet",
        "metadata": {
            "formula_cells_total": 80,  # 大量公式
            "sheets": ["Sheet1", "Sheet2", "Sheet3"],  # 3个sheet
            "invariants": {
                "checks": ["sum", "average"]  # 2个约束
            }
        }
    }

    # 根据这个配置，计算得分应该是：
    # answer_count=5 -> 5分
    # formula_count=80 -> 25分
    # sheet_count=3 -> 10分
    # invariant_count=2 -> 10分
    # 总分 = 50分 -> L2边界，但实际可能被判定为L3

    task_file = output_dir / f"{task_data['task_id']}.json"
    with open(task_file, 'w', encoding='utf-8') as f:
        json.dump(task_data, f, indent=2, ensure_ascii=False)

    print(f"✓ 创建测试任务: {task_file}")
    return task_file


def test_without_auto_fix():
    """测试：不自动修正难度"""
    print("\n" + "="*70)
    print("测试1: 不自动修正难度 (auto_fix_difficulty=False)")
    print("="*70)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        task_file = create_test_task(tmpdir)

        # 创建筛选器（不自动修正）
        screener = TaskScreener(auto_fix_difficulty=False)

        # 筛选任务
        result = screener.screen_task(
            task_file,
            check_unique_solution=False,
            check_contamination=False,
            check_difficulty=True
        )

        print(f"\n筛选结果:")
        print(f"  任务ID: {result.task_id}")
        print(f"  通过: {result.passed}")
        print(f"  难度有效: {result.difficulty_valid}")
        print(f"  建议难度: {result.difficulty_adjusted}")
        print(f"  问题列表: {result.issues}")

        # 验证JSON文件未被修改
        with open(task_file, 'r') as f:
            task_data = json.load(f)
        print(f"  JSON文件中的难度: {task_data['difficulty']}")

        assert not result.passed, "预期：任务应该不通过"
        assert task_data['difficulty'] == 'L2', "预期：难度未被修改"
        print("\n✓ 测试通过：难度未自动修正")


def test_with_auto_fix():
    """测试：自动修正难度"""
    print("\n" + "="*70)
    print("测试2: 自动修正难度 (auto_fix_difficulty=True)")
    print("="*70)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        task_file = create_test_task(tmpdir)

        # 创建筛选器（自动修正）
        screener = TaskScreener(auto_fix_difficulty=True)

        # 筛选任务
        result = screener.screen_task(
            task_file,
            check_unique_solution=False,
            check_contamination=False,
            check_difficulty=True
        )

        print(f"\n筛选结果:")
        print(f"  任务ID: {result.task_id}")
        print(f"  通过: {result.passed}")
        print(f"  难度有效: {result.difficulty_valid}")
        print(f"  建议难度: {result.difficulty_adjusted}")
        print(f"  问题列表: {result.issues}")

        # 验证JSON文件已被修改
        with open(task_file, 'r') as f:
            task_data = json.load(f)
        print(f"  JSON文件中的难度: {task_data['difficulty']}")

        assert result.passed, "预期：任务应该通过"
        assert result.difficulty_valid, "预期：难度应该有效"
        assert 'auto-fixed' in str(result.issues).lower(), "预期：问题列表包含auto-fixed"
        print("\n✓ 测试通过：难度已自动修正")


def main():
    print("="*70)
    print("TaskScreener 难度自动修正功能测试")
    print("="*70)

    try:
        test_without_auto_fix()
        test_with_auto_fix()

        print("\n" + "="*70)
        print("✅ 所有测试通过！")
        print("="*70)

    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
