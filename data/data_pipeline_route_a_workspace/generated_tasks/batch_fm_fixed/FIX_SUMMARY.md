# Route A Generator - FM Input Workbook Fix

**日期**: 2026-08-19
**修复内容**: FM任务的input工作簿生成逻辑

---

## 问题背景

之前的Route A generator对FM任务使用了错误的input生成策略：
- **旧逻辑**: 直接复制golden工作簿作为input（`shutil.copy`）
- **问题**: Input工作簿包含所有公式和答案，用户无需填写任何内容
- **影响**: 生成的FM任务不是真正的"公式建模"任务

## 修复方案

修改 `scripts/generate_route_a_tasks.py` 中的 `_generate_input_workbook_fm` 方法：

### 修复前
```python
def _generate_input_workbook_fm(self, golden_path: str, input_path: str, task_json: dict):
    """FM任务：直接复制golden作为input"""
    shutil.copy(golden_path, input_path)
    self.logger.info(f"    ✓ Copied golden to input (FM task)")
```

### 修复后
```python
def _generate_input_workbook_fm(self, golden_path: str, input_path: str, task_json: dict):
    """
    FM任务：使用LLM生成清理代码，移除答案区域的公式和数值
    保留数据表、格式、结构，只清空需要用户填写的区域
    """
    prompt = f'''# Task
Generate Python code using openpyxl to create an input workbook for an FM (Formula Modeling) task.

# Requirements
1. Load the golden workbook from: {golden_path}
2. Clear all cells in these answer regions (set to None):
{chr(10).join(f"   - {pos}" for pos in task_json.get("answer_position", []))}
3. Keep all other content unchanged (data tables, formatting, structure)
4. Save to: {input_path}

# Code Requirements
- Import openpyxl at the top
- Use openpyxl to load, modify, and save the workbook
- For each answer position, iterate through the range and set cell.value = None
- Handle both single cells and ranges (e.g., "Sheet1!B2:B10")
- Save the modified workbook

# Output Format
Return ONLY the complete Python code, no explanations.
The code should be ready to execute directly.
'''
    
    # 调用LLM生成清理代码
    response = self.client.messages.create(
        model=self.model_name,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    # 提取生成的代码
    text_blocks = [block for block in response.content if hasattr(block, 'text')]
    if not text_blocks:
        raise ValueError("No code generated for input workbook")
    
    code = text_blocks[0].text
    
    # 清理代码块标记
    if '```python' in code:
        code = code.split('```python')[1].split('```')[0].strip()
    elif '```' in code:
        code = code.split('```')[1].split('```')[0].strip()
    
    # 执行生成的代码
    exec(code)
    
    self.logger.info(f"    ✓ Generated input workbook (FM task)")
```

## 验证结果

第一个生成的任务（fm_20260819_001）验证成功：

```python
{
    'task_id': 'fm_20260819_001',
    'is_blank': True,
    'non_empty_cells': [],
    'non_empty_count': 0,
    'details': {
        "March'01 GDAs!C2:AG104": {'non_empty': 0, 'formulas': 0},
        "March'01 GDAs!C105:AG105": {'non_empty': 0, 'formulas': 0},
        'Sheet1!B2:B20': {'non_empty': 0, 'formulas': 0},
        'Sheet1!C2:C20': {'non_empty': 0, 'formulas': 0}
    }
}
```

✓ 所有答案区域完全为空
✓ 没有任何公式残留
✓ Input工作簿符合FM任务要求

## 技术要点

1. **LLM生成清理代码**: 使用相同的LLM来生成清空答案区域的Python代码
2. **动态执行**: 使用`exec()`执行生成的代码，灵活处理各种工作簿结构
3. **精确清空**: 只清空answer_position区域，保留所有其他内容
4. **代码提取**: 处理markdown代码块标记，提取纯Python代码

## 后续验证

正在生成批次：5个FM任务（L3: 2个, L4: 3个）
完成后将验证所有任务的input工作簿是否都为空白。

---

**状态**: ✓ 修复已验证有效
**影响**: 从此批次开始，所有FM任务的input工作簿将是真正的空白模板
