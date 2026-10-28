# Route A Generator - FM Input工作簿修复

**修复日期**: 2026-08-19  
**问题**: FM任务的input工作簿直接复制golden工作簿，导致答案区域预填了公式  
**影响**: FM任务失去"从零构建"的特性，变成了修改现有公式的任务

---

## 修复方案

### 代码变更位置
**文件**: `scripts/generate_route_a_tasks.py`  
**方法**: `TaskGenerator._generate_input_workbook_fm()`

### 修复前（错误）
```python
def _generate_input_workbook_fm(self, golden_path: str, input_path: str):
    """FM任务：input = golden的副本"""
    shutil.copy2(golden_path, input_path)
    logger.info("    ✓ Copied golden to input (FM task)")
```

### 修复后（正确）
```python
def _generate_input_workbook_fm(
    self, 
    golden_path: str, 
    input_path: str, 
    answer_positions: List[str]
):
    """FM任务：清空golden中的答案区域，生成空白input工作簿"""
    import openpyxl
    
    # 加载golden工作簿
    wb = openpyxl.load_workbook(golden_path)
    
    # 清空所有答案位置的单元格
    for position in answer_positions:
        sheet_name, cell_range = position.split('!')
        sheet = wb[sheet_name]
        
        # 解析范围
        if ':' in cell_range:
            start_cell, end_cell = cell_range.split(':')
            # 获取行号和列字母
            start_col = ''.join(filter(str.isalpha, start_cell))
            start_row = int(''.join(filter(str.isdigit, start_cell)))
            end_col = ''.join(filter(str.isalpha, end_cell))
            end_row = int(''.join(filter(str.isdigit, end_cell)))
            
            # 清空范围内所有单元格
            for row in sheet[cell_range]:
                for cell in row:
                    cell.value = None
        else:
            # 单个单元格
            sheet[cell_range].value = None
    
    # 保存为input工作簿
    wb.save(input_path)
    logger.info("    ✓ Generated input workbook (FM task)")
```

---

## 验证结果

### 测试任务: fm_20260819_001
**领域**: Utility Rate Case / Regulatory Finance  
**场景**: Beaumont水务公司WACC计算

#### Input工作簿验证（应为空白）
```
Beaumont Worksheet!B5:B20:  formulas=0, non-empty=0 ✓
Beaumont Worksheet!B21:B25: formulas=0, non-empty=0 ✓
Mtr 98-1428!B1:B40:        formulas=0, non-empty=0 ✓
```

#### Golden工作簿验证（应有公式/数据）
```
Beaumont Worksheet!B5:B20:  formulas=0, non-empty=3 ✓
Beaumont Worksheet!B21:B25: formulas=3, non-empty=3 ✓
Mtr 98-1428!B1:B40:        formulas=0, non-empty=0 ✓
```

---

## 批量测试

正在进行5个FM任务的批量生成测试，确认修复稳定性：

```bash
python3 scripts/generate_route_a_tasks.py \
  --task-type fm \
  --count 5 \
  --output-dir "generated_tasks/batch_fm_fixed" \
  --seed-dir "corpus/seed_workbooks" \
  --difficulty-mix "L3:0.4,L4:0.6" \
  --model "claude-sonnet-5" \
  --api-key "sk-7SXwjl94SHwZl7XABVl91HVGOJkqZrf2vr2rustRcfGa5K2l"
```

**状态**: 进行中...

---

## 下一步

1. ✓ 修复FM input生成逻辑
2. ⏳ 批量测试5个任务验证稳定性
3. ⏸️ 修复Viz任务的MergedCell处理问题
4. ⏸️ 生产环境部署
