#!/usr/bin/env python3
"""
S4 Scaffold共享模块

被rollout/llm_rollout_generator.py和rollout/scaffold_aligner.py共用的
scaffold格式/消息构造代码：system prompt、user message模板、view_xlsx
observation渲染逻辑，以及output_path解析。这些内容与"轨迹是怎么生成的"
(LLM rollout / recovery_inject)无关，纯粹是SpreadsheetBench-2官方
SWE-agent scaffold的格式复刻，因此独立于任何一条轨迹生成路径存在。
"""

from pathlib import Path
from typing import Dict

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from config import SCAFFOLD_CONFIG

# Scaffold规范的System Prompt(与config.SCAFFOLD_CONFIG["system_prompt"]逐字一致)
SYSTEM_PROMPT = (
    "You are a helpful Spreadsheet Automation Engineer that interacts with a computer "
    "shell to solve data tasks. You operate in a REPL (Read-Eval-Print Loop) environment "
    "where you must issue exactly ONE command at a time."
)

# 与config.SCAFFOLD_CONFIG逐字对齐的instance_template(SWE-agent config/spreadsheet.yaml)。
# {spreadsheet_path}在"Recommended Workflow"示例里出现了3次，不只是Input/Output字段——
# 必须整段一起.format()替换，否则示例命令里残留占位符文本会泄漏scaffold细节给下游。
USER_MESSAGE_TEMPLATE = """<task_context>

## Important
- When completing spreadsheet tasks, strictly avoid altering any cells that already contain values unless explicitly instructed. Modify only the cells that are required for the task.
- You need to complete the instructions and ensure that the original formatting is preserved as much as possible.

## Tools
You are provided with four tools: `bash`, `view_xlsx` and `submit`. You must use these tools to complete the target task.
**Important: You can only call ONE tool at a time per response.**
- `bash`: run shell commands (e.g., file operations, calling Python scripts with `python3`)
- `view_xlsx`: inspect `.xlsx` files (list sheets, view sheet contents, see original formulas and values)
- `submit`: finalize and submit your solution after verification

## Environment
You can complete the corresponding spreadsheet tasks using the following Python environment:
`Pandas`, `openpyxl`, `numpy` and `LibreOffice`
You can use these environments to manipulate the spreadsheet data.

## Recommended Workflow
1. **Inspect**: Use `view_xlsx` to inspect the data. This will allow you to understand the structure and contents of the spreadsheet.
   - You must choose mode `list` or `content` to inspect the data.
   - List all sheets: `view_xlsx {spreadsheet_path} list`
   - View specific sheet: `view_xlsx {spreadsheet_path} content "Sheet1"`
   - View row range: `view_xlsx {spreadsheet_path} content "Sheet1" 1 50`

2. **Plan**: Decide how to manipulate the data using `openpyxl` or `LibreOffice`.

3. **Implement**: Create a python script (e.g., `process_data.py`) that performs the edit.
   - You can use `bash` tool to write Python code directly, e.g., cat > /tmp/script.py << 'EOF' ... EOF), which can then be used to verify syntax correctness.

4. **Execute**: Run the python script using `python3 /tmp/script.py`

5. **Verify**: Check the output file exists, ensure the answer is correct.
   - Do NOT combine verify and submit commands (e.g., `python3 script.py && submit`). Run them separately to ensure verification is complete before submission.
   - Ensure the existing structure, layout, and formatting of the model are preserved throughout the process.

6. **Submit**: When verification is successful, run `submit`.

</task_context>

<instructions>

## Task instructions
You need to process a spreadsheet file based on specific instructions.
**Instruction:** {instruction}

## Input and Output
You are provided with an input spreadsheet file and you need to generate an output spreadsheet file based on the output_path.
**Input File:** {spreadsheet_path}
**Output Path:** {output_path}

</instructions>"""


def build_user_message(instruction: str, spreadsheet_path, output_path) -> str:
    """按官方SWE-agent scaffold的instance_template逐字对齐生成user message"""
    return USER_MESSAGE_TEMPLATE.format(
        instruction=instruction,
        spreadsheet_path=spreadsheet_path,
        output_path=output_path,
    )


def resolve_output_path(task_id: str) -> Path:
    """按SCAFFOLD_CONFIG["output_path_pattern"]算出独立输出目录下的output路径

    对齐SpreadsheetBench-2官方SWE-agent scaffold：output.xlsx不与input.xlsx
    同目录，而是落在独立的/mnt/spreadsheet_output/下，按task_id命名。
    """
    return Path(SCAFFOLD_CONFIG["output_path_pattern"].format(id=task_id))


def _get_data_range(sheet):
    """复刻tools/view_xlsx/bin/view_xlsx的get_data_range: 扫描整张sheet算出

    有数据的行列边界(min_row, max_row, min_col, max_col)。
    """
    min_row = max_row = min_col = max_col = None
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value is not None:
                if min_row is None or cell.row < min_row:
                    min_row = cell.row
                if max_row is None or cell.row > max_row:
                    max_row = cell.row
                if min_col is None or cell.column < min_col:
                    min_col = cell.column
                if max_col is None or cell.column > max_col:
                    max_col = cell.column
    return min_row, max_row, min_col, max_col


def render_view_xlsx_observation(workbook_path, arguments: Dict) -> str:
    """按官方scaffold的tools/view_xlsx/bin/view_xlsx脚本真实输出格式渲染observation

    与config.SCAFFOLD_CONFIG["observation_format"]对齐。

    arguments: {"file_path"(仅展示用,实际IO用workbook_path), "mode": "list"|"content",
                "sheet": Optional[str], "start_row": Optional[int], "end_row": Optional[int]}
    """
    workbook_path = Path(workbook_path)
    mode = arguments.get("mode") or "content"
    sheet_name = arguments.get("sheet")
    start_row = arguments.get("start_row")
    end_row = arguments.get("end_row")

    if not workbook_path.exists():
        return f"Error: File '{workbook_path}' does not exist"
    if not workbook_path.is_file():
        return f"Error: '{workbook_path}' is not a file"
    if workbook_path.suffix.lower() not in (".xlsx", ".xlsm"):
        return f"Error: File must be an Excel file (.xlsx or .xlsm), got: {workbook_path.suffix}"

    lines = [f"Loading workbook: {workbook_path}"]

    try:
        wb = load_workbook(workbook_path, data_only=False)
    except Exception as e:
        return f"Error processing Excel file: {e}"

    hidden_states = ("hidden", "veryHidden")
    visible_sheets = [n for n in wb.sheetnames if wb[n].sheet_state not in hidden_states]

    if mode == "list":
        lines.append(f"Sheets: {visible_sheets}")
        wb.close()
        return "\n".join(lines)

    if sheet_name:
        if sheet_name not in wb.sheetnames:
            wb.close()
            lines.append(f"\nError: Sheet '{sheet_name}' not found in workbook")
            lines.append(f"Available sheets: {visible_sheets}")
            return "\n".join(lines)
        target_name = sheet_name
    else:
        if not visible_sheets:
            wb.close()
            lines.append("Error: No visible sheets in workbook")
            return "\n".join(lines)
        target_name = visible_sheets[0]

    ws = wb[target_name]
    min_row, max_row, min_col, max_col = _get_data_range(ws)

    if min_row is None:
        wb.close()
        lines.append(f"Sheet '{ws.title}' is empty (no data found)")
        return "\n".join(lines)

    actual_start = start_row if start_row is not None else min_row
    actual_end = end_row if end_row is not None else max_row
    if actual_start < 1:
        actual_start = 1
    if actual_end < actual_start:
        wb.close()
        lines.append(f"Error: end_row ({actual_end}) must be >= start_row ({actual_start})")
        return "\n".join(lines)

    start_col = min_col or 1
    end_col = max_col or ws.max_column
    start_col_letter = get_column_letter(start_col)
    end_col_letter = get_column_letter(end_col)
    range_notation = f"'{ws.title}'!{start_col_letter}{actual_start}:{end_col_letter}{actual_end}"

    lines.append(f"\nSheet: {ws.title}")
    lines.append(f"Data range: {range_notation}")
    lines.append(f"Rows: {actual_start} to {actual_end} (total: {actual_end - actual_start + 1})")
    lines.append(f"Columns: {start_col_letter} to {end_col_letter}")
    lines.append("")

    chunk_size = 100
    current_row = actual_start
    while current_row <= actual_end:
        chunk_end = min(current_row + chunk_size - 1, actual_end)
        if actual_end - actual_start + 1 > chunk_size:
            lines.append(f"[Rows {current_row} to {chunk_end}]")
        for row_idx in range(current_row, chunk_end + 1):
            row_values = [
                ws.cell(row=row_idx, column=col_idx).value
                for col_idx in range(start_col, end_col + 1)
            ]
            lines.append(f"Row {row_idx}: {row_values}")
        current_row = chunk_end + 1
        if current_row <= actual_end:
            lines.append("")

    wb.close()
    observation = "\n".join(lines)

    if len(observation) > 10000:
        half = 4900
        observation = observation[:half] + "\n<elided_chars>\n" + observation[-half:]

    return observation
