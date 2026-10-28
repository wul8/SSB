#!/usr/bin/env python3
"""
批量验证FM任务的input工作簿是否为空白
"""

import sys
from pathlib import Path
from verify_fm_input_blank import verify_input_blank


def batch_verify(batch_dir: str):
    """验证批次中所有FM任务的input工作簿"""
    batch_path = Path(batch_dir)

    if not batch_path.exists():
        print(f"Error: Batch directory not found: {batch_dir}")
        return

    # 查找所有FM任务目录
    task_dirs = sorted([d for d in batch_path.iterdir()
                       if d.is_dir() and d.name.startswith('fm_')])

    if not task_dirs:
        print(f"No FM tasks found in {batch_dir}")
        return

    print(f"Found {len(task_dirs)} FM tasks to verify\n")
    print("=" * 80)

    all_blank = True
    results = []

    for task_dir in task_dirs:
        result = verify_input_blank(str(task_dir))
        results.append(result)

        task_id = result['task_id']
        is_blank = result.get('is_blank', False)

        if 'error' in result:
            print(f"✗ {task_id}: ERROR - {result['error']}")
            all_blank = False
        elif is_blank:
            print(f"✓ {task_id}: All answer regions are blank")
        else:
            print(f"✗ {task_id}: NOT blank - {len(result.get('non_empty_cells', []))} non-empty cells")
            all_blank = False

            # 显示前5个非空单元格
            for cell_info in result.get('non_empty_cells', [])[:5]:
                print(f"    {cell_info['region']}: {cell_info['cell']} = {cell_info['value']}")

    print("=" * 80)
    print(f"\nSummary:")
    print(f"  Total tasks: {len(results)}")
    print(f"  All blank: {'YES ✓' if all_blank else 'NO ✗'}")

    # 统计详情
    blank_count = sum(1 for r in results if r.get('is_blank', False) and 'error' not in r)
    error_count = sum(1 for r in results if 'error' in r)
    non_blank_count = len(results) - blank_count - error_count

    print(f"  Blank: {blank_count}")
    print(f"  Non-blank: {non_blank_count}")
    print(f"  Errors: {error_count}")

    return all_blank


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python batch_verify_fm_inputs.py <batch_directory>")
        sys.exit(1)

    batch_dir = sys.argv[1]
    success = batch_verify(batch_dir)
    sys.exit(0 if success else 1)
