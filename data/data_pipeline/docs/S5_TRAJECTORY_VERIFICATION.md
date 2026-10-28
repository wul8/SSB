# S5 轨迹验证器 - 设计文档

## 概述

S5轨迹验证器是SFT数据管线的质量把关模块，负责验证LLM rollout轨迹（或任何生成的轨迹）是否满足严格标准。**只有accuracy=1.0且通过所有strict检查的轨迹才能进入正样本池。**

## 核心设计原则

1. **零容忍策略**: accuracy必须为1.0，任何偏差都会被拒绝
2. **Strict验证**: 超越官方评分，检查protected cells、formula family、invariants等
3. **复用现有组件**: 集成WorkbookValidator、OfficialScorer、WorkbookParser
4. **Visualization支持**: 两级验证策略覆盖图表任务
5. **可追溯性**: 详细的rejection_reasons便于调试和改进

## 验证流程

```
Trajectory → TrajectoryVerifier.verify()
    ↓
    ├─ 1. 文件存在性检查 (task.json, input.xlsx, golden.xlsx, output.xlsx)
    ├─ 2. LibreOffice重算检查 (output.xlsx可重算)
    ├─ 3. 官方评分 (modification_accuracy, regression_accuracy)
    ├─ 4. Strict验证
    │   ├─ Protected cells检查 (answer_position外无修改)
    │   ├─ Formula family检查 (公式模式一致性)
    │   ├─ Invariants检查 (财务约束验证)
    │   ├─ Excel errors检查 (#REF!, #VALUE!等)
    │   └─ Style preservation检查 (合并单元格、命名区域)
    └─ 5. Visualization验证 (如适用)
        ├─ Tier 1: openpyxl读取chart XML (~70%的criteria)
        └─ Tier 2: VLM抽检 (可选, ~15%的criteria)
    ↓
VerificationResult (approved: bool, rejection_reasons: List[str])
```

## 批准标准

轨迹必须同时满足以下所有条件才能进入正样本池：

### 1. 文件完整性
- `task.json` 存在且格式正确
- `input.xlsx` 存在
- `golden.xlsx` 存在
- `output.xlsx` 存在（轨迹执行后的输出）

### 2. 重算一致性
- `recalculated = True`
- LibreOffice重新计算后，output.xlsx的所有公式结果与原值一致
- 使用WorkbookValidator.check_recalc_consistency验证

### 3. 官方评分 = 1.0
- `modification_accuracy = 1.0` (answer_position区域内的修改100%正确)
- `regression_accuracy = 1.0` (answer_position外的区域无意外修改)
- 使用OfficialScorer计算评分

### 4. Strict验证全部通过

#### 4.1 Protected Cells (受保护单元格)
- `protected_violation = 0`
- answer_position外的所有单元格值/公式/格式不得被修改
- 对比input.xlsx和output.xlsx检测违规

#### 4.2 Formula Family (公式家族一致性)
- `formula_family_consistent = True`
- 检查output.xlsx中answer区域内的公式是否与golden.xlsx的公式模式一致
- 使用WorkbookParser.parse()提取FormulaGraph进行比较
- 拒绝半公式半硬编码的混合实现

#### 4.3 Invariants (不变量验证)
- `invariants_failed = []`
- 验证财务约束（如资产负债平衡、三表勾稽）
- 使用WorkbookParser.parse()提取Invariants并验证output.xlsx

#### 4.4 Excel Errors (Excel错误检查)
- `excel_errors = 0`
- answer_position区域内不得包含 #REF!, #VALUE!, #DIV/0!, #N/A, #NAME?, #NUM!, #NULL!
- 扫描output.xlsx的answer区域检测错误

#### 4.5 Style Preservation (样式保留)
- `style_preserved = True`
- 合并单元格区域不得被意外取消合并
- 命名区域不得被删除或修改
- 对比input.xlsx和output.xlsx的StyleMap

### 5. Visualization验证 (如适用)

#### Tier 1: Chart Structure (图表结构, ~70%覆盖率)
使用openpyxl读取chart XML，验证：
- 图表存在性和类型
- 数据源引用正确
- 坐标轴标签和标题
- 图例位置

#### Tier 2: Visual Accuracy (视觉准确性, ~15%抽检)
使用Excel COM + VLM验证：
- 图表渲染正确性
- 颜色和格式细节
- 数据标签显示

## 使用方法

### 单个轨迹验证

```python
from verify.trajectory_verifier import TrajectoryVerifier

verifier = TrajectoryVerifier()
result = verifier.verify("/path/to/task_dir")

if result.approved:
    print("✓ 轨迹已批准进入正样本池")
else:
    print(f"✗ 轨迹被拒绝: {', '.join(result.rejection_reasons)}")
    print(f"Accuracy: {result.accuracy}")
    print(f"Protected violations: {result.protected_violation}")
    print(f"Formula family consistent: {result.formula_family_consistent}")
```

### 批量轨迹验证

```python
from verify.trajectory_verifier import TrajectoryVerifier

verifier = TrajectoryVerifier()
report = verifier.verify_batch("/path/to/trajectories_dir")

print(f"Total: {report['total']}")
print(f"Approved: {report['approved']} ({report['approval_rate']:.1%})")
print(f"Rejected: {report['rejected']}")

for task_id, result in report['results'].items():
    if not result.approved:
        print(f"\n{task_id}: {', '.join(result.rejection_reasons)}")
```

### 命令行工具

```bash
# 单个轨迹验证
python scripts/test_trajectory_verifier.py /path/to/task_dir

# 批量验证（需要生成LLM rollout轨迹后才能测试）
python scripts/test_trajectory_verifier.py /path/to/trajectories_dir --batch
```

## 技术实现

### 核心类

#### TrajectoryVerifier
主验证器类，协调所有验证步骤。

**依赖**:
- `WorkbookValidator`: S0重算一致性检查
- `OfficialScorer`: 官方评分计算
- `WorkbookParser`: S1元数据提取（FormulaGraph, Invariants, StyleMap）

**主要方法**:
- `verify(task_dir: str) -> VerificationResult`: 验证单个轨迹
- `verify_batch(trajectories_dir: str) -> Dict`: 批量验证并生成报告

#### VerificationResult
验证结果数据类，包含完整的验证信息。

**字段**:
```python
@dataclass
class VerificationResult:
    task_id: str
    approved: bool
    rejection_reasons: List[str]
    
    # 官方评分
    accuracy: float
    modification_accuracy: float
    regression_accuracy: float
    
    # Strict验证
    recalculated: bool
    protected_violation: int
    formula_family_consistent: bool
    invariants_failed: List[str]
    excel_errors: int
    style_preserved: bool
    
    # Visualization (如适用)
    visualization_tier1_passed: Optional[bool] = None
    visualization_tier2_passed: Optional[bool] = None
```

### 关键算法

#### 1. Protected Cells检查

```python
def _check_protected_cells(input_wb, output_wb, answer_positions):
    """检测answer_position外的修改"""
    violations = 0
    answer_cells = parse_answer_positions(answer_positions)
    
    for sheet_name in input_wb.sheetnames:
        input_ws = input_wb[sheet_name]
        output_ws = output_wb[sheet_name]
        
        for row in input_ws.iter_rows():
            for cell in row:
                coord = f"{sheet_name}!{cell.coordinate}"
                if coord in answer_cells:
                    continue  # 跳过answer区域
                
                # 检查值、公式、格式是否被修改
                if cell_modified(input_ws[cell.coordinate], 
                                output_ws[cell.coordinate]):
                    violations += 1
    
    return violations
```

#### 2. Formula Family检查

```python
def _check_formula_family(golden_wb, output_wb, answer_positions):
    """检查公式模式一致性"""
    golden_graph = WorkbookParser.parse(golden_wb).formula_graph
    output_graph = WorkbookParser.parse(output_wb).formula_graph
    
    answer_cells = parse_answer_positions(answer_positions)
    
    for cell in answer_cells:
        golden_formula = golden_graph.get_formula(cell)
        output_formula = output_graph.get_formula(cell)
        
        if golden_formula:  # golden中是公式
            if not output_formula:
                return False  # output中是硬编码，不一致
            
            # 检查公式家族是否匹配（归一化后的R1C1模式）
            if normalize(golden_formula) != normalize(output_formula):
                return False
    
    return True
```

#### 3. Invariants验证

```python
def _check_invariants(output_wb, task_json):
    """验证财务约束"""
    metadata = WorkbookParser.parse(output_wb)
    failed_invariants = []
    
    for invariant in metadata.invariants:
        if invariant.type == "balance_sheet_balance":
            if not check_balance_sheet(output_wb, invariant):
                failed_invariants.append(invariant.name)
        
        elif invariant.type == "cashflow_statement_link":
            if not check_cashflow_link(output_wb, invariant):
                failed_invariants.append(invariant.name)
        
        # ... 其他约束类型
    
    return failed_invariants
```

#### 4. Excel Errors检查

```python
def _check_excel_errors(output_wb, answer_positions):
    """统计Excel错误"""
    error_markers = {"#REF!", "#VALUE!", "#DIV/0!", "#N/A", 
                     "#NAME?", "#NUM!", "#NULL!"}
    error_count = 0
    
    answer_cells = parse_answer_positions(answer_positions)
    
    for cell_ref in answer_cells:
        sheet, coord = parse_cell_ref(cell_ref)
        cell = output_wb[sheet][coord]
        
        if isinstance(cell.value, str) and cell.value in error_markers:
            error_count += 1
    
    return error_count
```

## 验证统计

验证器会收集以下统计信息（用于质量监控）：

- **Total trajectories**: 验证的轨迹总数
- **Approved**: 通过验证的数量
- **Approval rate**: 通过率（目标≥95%）
- **Rejection breakdown**: 各类拒绝原因的分布
  - Recalc failed: 重算失败
  - Accuracy < 1.0: 官方评分不满分
  - Protected violation: 修改了受保护区域
  - Formula family mismatch: 公式模式不一致
  - Invariants failed: 约束验证失败
  - Excel errors: 包含Excel错误
  - Style not preserved: 样式被破坏
  - Visualization failed: 可视化验证失败

## 质量保证

### 单元测试

```bash
# 测试protected cells检查
pytest tests/test_trajectory_verifier.py::test_protected_cells

# 测试formula family检查
pytest tests/test_trajectory_verifier.py::test_formula_family

# 测试invariants验证
pytest tests/test_trajectory_verifier.py::test_invariants
```

### 集成测试

使用已知的高质量LLM rollout轨迹验证完整流程：

```bash
# 生成LLM rollout轨迹
python scripts/batch_generate_trajectories.py \
    generated_tasks/test_batch_debugging \
    --output trajectories/test_debugging

# 验证轨迹
python scripts/test_trajectory_verifier.py \
    trajectories/test_debugging --batch

# 预期结果: 高通过率（LLM rollout轨迹经筛选后应基本完美）
```

## 常见拒绝原因及修复

### 1. Protected Violation (最常见)

**症状**: 修改了answer_position外的单元格

**原因**:
- LLM rollout执行的批量操作范围过大
- 误修改了格式或隐藏属性
- 清空了临时计算单元格

**修复**:
- 缩小批量操作范围，精确定位answer区域
- 只修改值/公式，不动格式
- 保留所有非answer区域的单元格

### 2. Formula Family Mismatch

**症状**: output中的公式与golden模式不一致

**原因**:
- 硬编码了部分值而非使用公式
- 使用了不同的公式实现方式
- 相对/绝对引用不一致

**修复**:
- 确保answer区域全部使用公式（如果golden用公式）
- 复制golden的公式模式
- 检查$符号的使用

### 3. Invariants Failed

**症状**: 财务约束验证失败

**原因**:
- 资产≠负债+权益
- 现金流量表与资产负债表不勾稽
- 利润表净利润与留存收益不匹配

**修复**:
- 检查关键公式的单元格引用
- 确保三表联动公式正确
- 验证期初/期末余额的连续性

### 4. Excel Errors

**症状**: answer区域包含#REF!或#VALUE!等错误

**原因**:
- 引用了被删除的单元格/sheet
- 类型不匹配（文本用于数值运算）
- 除以零

**修复**:
- 检查所有单元格引用是否有效
- 确保数据类型正确
- 添加IFERROR()保护（如果golden中有）

### 5. Style Not Preserved

**症状**: 合并单元格被取消或命名区域被删除

**原因**:
- openpyxl操作时意外取消了合并
- 删除了包含命名区域的单元格
- 复制粘贴时未保留格式

**修复**:
- 使用merge_cells()和unmerge_cells()谨慎操作
- 不要删除命名区域引用的单元格
- 复制时保留所有格式

## 未来扩展

### 1. Model-generated轨迹验证

当前验证器主要针对LLM rollout轨迹。未来需要支持：
- LLM生成的轨迹（可能包含中间错误和自我修正）
- 多路径轨迹（尝试多种方法最终成功）
- 部分成功轨迹（用于负样本或DPO）

### 2. 渐进式验证

支持checkpoint验证：
- 验证轨迹中间步骤的正确性
- 识别第一个错误发生的位置
- 生成step-level的正确性标注（用于PRM训练）

### 3. Visualization Tier 2集成

当Windows + Excel COM环境可用时：
- 导出图表为PNG
- 调用VLM（GPT-4V或Claude）验证视觉准确性
- 生成视觉质量评分

### 4. 性能优化

- 并行化批量验证
- 缓存WorkbookParser结果
- 增量验证（只验证变更部分）

## 总结

S5轨迹验证器实现了**零容忍的质量标准**：
- ✓ 100%准确性（accuracy = 1.0）
- ✓ 完整的strict验证（5项检查）
- ✓ 复用现有组件（WorkbookValidator, OfficialScorer, WorkbookParser）
- ✓ Visualization两级验证架构
- ✓ 详细的拒绝原因追溯

**下一步**: 在真实生成的LLM rollout轨迹上运行批量验证，确认95%+的通过率。
