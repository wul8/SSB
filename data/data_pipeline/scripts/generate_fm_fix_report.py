#!/usr/bin/env python3
"""
生成FM input工作簿修复报告
"""

import json
from pathlib import Path
from datetime import datetime
from verify_fm_input_blank import verify_input_blank


def generate_report(batch_dir: str, output_file: str):
    """生成修复验证报告"""
    batch_path = Path(batch_dir)

    # 查找所有FM任务
    task_dirs = sorted([d for d in batch_path.iterdir()
                       if d.is_dir() and d.name.startswith('fm_')])

    results = []
    for task_dir in task_dirs:
        result = verify_input_blank(str(task_dir))
        results.append(result)

    # 统计
    total = len(results)
    blank_count = sum(1 for r in results if r.get('is_blank', False) and 'error' not in r)
    error_count = sum(1 for r in results if 'error' in r)
    non_blank_count = total - blank_count - error_count

    success_rate = (blank_count / total * 100) if total > 0 else 0

    # 生成Markdown报告
    report = f"""# FM Input工作簿修复验证报告

**验证时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**批次目录**: `{batch_dir}`
**任务数量**: {total}

---

## 修复摘要

✓ **修复成功率**: {success_rate:.1f}% ({blank_count}/{total})

| 状态 | 数量 | 占比 |
|------|------|------|
| ✓ 完全空白 | {blank_count} | {blank_count/total*100:.1f}% |
| ✗ 非空白 | {non_blank_count} | {non_blank_count/total*100:.1f}% |
| ⚠ 错误 | {error_count} | {error_count/total*100:.1f}% |

---

## 任务详情

"""

    for result in results:
        task_id = result['task_id']
        is_blank = result.get('is_blank', False)

        if 'error' in result:
            report += f"### ⚠ {task_id}\n"
            report += f"**状态**: 错误  \n"
            report += f"**原因**: {result['error']}\n\n"
        elif is_blank:
            report += f"### ✓ {task_id}\n"
            report += f"**状态**: 完全空白  \n"
            report += f"**非空单元格**: 0  \n"

            # 显示各区域详情
            details = result.get('details', {})
            if details:
                report += f"**区域验证**:\n"
                for region, info in details.items():
                    report += f"- `{region}`: {info['non_empty']} 非空, {info['formulas']} 公式\n"
            report += "\n"
        else:
            report += f"### ✗ {task_id}\n"
            report += f"**状态**: 非空白  \n"
            report += f"**非空单元格**: {result.get('non_empty_count', 0)}  \n"

            # 显示前5个非空单元格
            non_empty = result.get('non_empty_cells', [])
            if non_empty:
                report += f"**示例非空单元格**:\n"
                for cell in non_empty[:5]:
                    report += f"- `{cell['region']}` {cell['cell']}: {cell['value']}\n"
            report += "\n"

    report += """---

## 修复说明

**问题**: 原生成器为FM任务复制golden作为input，导致input包含完整公式

**修复方案**:
1. 修改 `RouteATaskGenerator._generate_input_workbook_fm()` 方法
2. 不再简单复制golden文件
3. 使用LLM生成清除answer_position区域的Python代码
4. 执行代码生成真正的空白input工作簿

**关键代码**:
```python
def _generate_input_workbook_fm(self, task_data: Dict, golden_path: Path, input_path: Path):
    \"\"\"为FM任务生成空白input工作簿\"\"\"
    # 使用LLM生成清除代码
    code = self._call_api(prompt_for_clearing_code)
    # 执行生成input
    exec(code, ...)
```

**验证标准**:
- answer_position中所有单元格必须为空
- 不能包含任何公式
- 数据区域外的单元格可以保留（如标题、格式）

"""

    # 写入报告
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding='utf-8')

    print(f"Report generated: {output_file}")
    print(f"\nSummary:")
    print(f"  Total: {total}")
    print(f"  Blank: {blank_count} ({success_rate:.1f}%)")
    print(f"  Non-blank: {non_blank_count}")
    print(f"  Errors: {error_count}")

    return success_rate == 100.0


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage: python generate_fm_fix_report.py <batch_dir> <output_file>")
        sys.exit(1)

    batch_dir = sys.argv[1]
    output_file = sys.argv[2]

    success = generate_report(batch_dir, output_file)
    sys.exit(0 if success else 1)
