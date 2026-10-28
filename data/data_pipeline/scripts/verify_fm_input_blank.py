#!/usr/bin/env python3
"""
验证FM任务的input工作簿是否为空白

检查所有answer_position区域的单元格应该都是空的（None值）
"""

import json
import sys
from pathlib import Path
import openpyxl


def verify_input_blank(task_dir: str) -> dict:
    """
    验证input工作簿的答案区域是否为空白

    Returns:
        dict with keys: task_id, is_blank, non_empty_cells, details
    """
    task_path = Path(task_dir)
    task_id = task_path.name

    # 加载task.json
    task_json_path = task_path / "task.json"
    if not task_json_path.exists():
        return {
            "task_id": task_id,
            "is_blank": False,
            "error": "task.json not found"
        }

    with open(task_json_path) as f:
        task_json = json.load(f)

    # 加载input工作簿
    input_path = task_path / task_json["input_workbook"]
    if not input_path.exists():
        return {
            "task_id": task_id,
            "is_blank": False,
            "error": f"input workbook not found: {task_json['input_workbook']}"
        }

    wb = openpyxl.load_workbook(input_path)

    # 检查每个answer_position
    non_empty_cells = []
    details = {}

    for position in task_json.get("answer_position", []):
        sheet_name, cell_range = position.split('!')
        sheet = wb[sheet_name]

        non_empty_count = 0
        formula_count = 0

        # 解析范围
        if ':' in cell_range:
            for row in sheet[cell_range]:
                for cell in row:
                    if cell.value is not None:
                        non_empty_count += 1
                        non_empty_cells.append(f"{sheet_name}!{cell.coordinate}")
                    if hasattr(cell, 'value') and isinstance(cell.value, str) and cell.value.startswith('='):
                        formula_count += 1
        else:
            # 单个单元格
            cell = sheet[cell_range]
            if cell.value is not None:
                non_empty_count += 1
                non_empty_cells.append(f"{sheet_name}!{cell.coordinate}")
            if hasattr(cell, 'value') and isinstance(cell.value, str) and cell.value.startswith('='):
                formula_count += 1

        details[position] = {
            "non_empty": non_empty_count,
            "formulas": formula_count
        }

    is_blank = len(non_empty_cells) == 0

    return {
        "task_id": task_id,
        "is_blank": is_blank,
        "non_empty_cells": non_empty_cells,
        "non_empty_count": len(non_empty_cells),
        "details": details
    }


def verify_batch(output_dir: str):
    """验证批次中所有任务"""
    output_path = Path(output_dir)

    if not output_path.exists():
        print(f"Error: Directory not found: {output_dir}")
        sys.exit(1)

    # 找到所有任务目录
    task_dirs = [d for d in output_path.iterdir() if d.is_dir() and d.name.startswith('fm_')]

    if not task_dirs:
        print(f"No FM tasks found in {output_dir}")
        sys.exit(0)

    print(f"Verifying {len(task_dirs)} tasks...\n")

    all_blank = True
    results = []

    for task_dir in sorted(task_dirs):
        result = verify_input_blank(str(task_dir))
        results.append(result)

        if result.get("error"):
            print(f"✗ {result['task_id']}: ERROR - {result['error']}")
            all_blank = False
        elif result["is_blank"]:
            print(f"✓ {result['task_id']}: BLANK (all answer regions empty)")
        else:
            print(f"✗ {result['task_id']}: NOT BLANK ({result['non_empty_count']} non-empty cells)")
            all_blank = False
            print(f"  Non-empty cells: {', '.join(result['non_empty_cells'][:5])}")
            if len(result['non_empty_cells']) > 5:
                print(f"  ... and {len(result['non_empty_cells']) - 5} more")

    print(f"\n{'='*60}")
    print(f"Summary: {len([r for r in results if r.get('is_blank')])} / {len(results)} tasks have blank input workbooks")

    if all_blank:
        print("✓ All input workbooks are properly blank")
        sys.exit(0)
    else:
        print("✗ Some input workbooks have non-empty cells")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 verify_fm_input_blank.py <output_dir>")
        sys.exit(1)

    verify_batch(sys.argv[1])
