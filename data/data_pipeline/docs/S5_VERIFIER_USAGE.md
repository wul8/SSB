# S5 轨迹验证器使用指南

## 快速开始

### 单个轨迹验证

```bash
python scripts/test_trajectory_verifier.py /path/to/task_dir
```

**输出示例**:
```
============================================================
VERIFICATION RESULT: debugging_demo_001
============================================================
Approved: True
Accuracy: 1.000
  - Modification: 1.000
  - Regression: 1.000
Recalculated: True
Protected Violations: 0
Formula Family Consistent: True
Invariants Failed: []
Excel Errors: 0
Style Preserved: True
============================================================
```

### 批量轨迹验证

```bash
python scripts/test_trajectory_verifier.py /path/to/trajectories_dir --batch
```

**生成报告**:
```bash
python scripts/test_trajectory_verifier.py trajectories/test_batch --batch \
    --output trajectories/test_batch/verification_report.json
```

## 验证标准

轨迹必须满足以下**所有**条件才能被批准进入正样本池：

### 1. 文件完整性 ✓
- task.json 存在
- input.xlsx 存在
- golden.xlsx 存在
- output.xlsx 存在

### 2. 重算一致性 ✓
- LibreOffice重新计算output.xlsx后，所有公式结果与原值一致
- 使用WorkbookValidator.check_recalc_consistency验证

### 3. 官方评分 = 1.0 ✓
- accuracy = 1.0 (100%正确)
- modification_accuracy = 1.0 (answer区域修改正确)
- regression_accuracy = 1.0 (非answer区域无意外修改)

### 4. Strict验证 ✓

#### 4.1 Protected Cells (受保护单元格)
- protected_violation = 0
- answer_position外的单元格不得被修改

#### 4.2 Formula Family (公式家族一致性)
- formula_family_consistent = True
- answer区域的公式模式与golden一致
- 拒绝半公式半硬编码的实现

#### 4.3 Invariants (不变量验证)
- invariants_failed = []
- 财务约束通过（资产负债平衡、三表勾稽等）

#### 4.4 Excel Errors (Excel错误)
- excel_errors = 0
- answer区域不包含 #REF!, #VALUE!, #DIV/0!等错误

#### 4.5 Style Preservation (样式保留)
- style_preserved = True
- 合并单元格和命名区域未被破坏

### 5. Visualization验证 (如适用) ✓
- Tier 1: openpyxl读取chart XML验证图表存在性和结构

## 验证报告格式

### 单个轨迹结果 (VerificationResult)

```json
{
  "task_id": "debugging_demo_001",
  "approved": true,
  "rejection_reasons": [],
  "accuracy": 1.0,
  "modification_accuracy": 1.0,
  "regression_accuracy": 1.0,
  "recalculated": true,
  "protected_violation": 0,
  "formula_family_consistent": true,
  "invariants_failed": [],
  "excel_errors": 0,
  "style_preserved": true,
  "visualization_tier1_passed": null
}
```

### 批量验证报告

```json
{
  "total": 10,
  "approved": 9,
  "rejected": 1,
  "approval_rate": 0.9,
  "rejection_breakdown": {
    "accuracy=0.875 < 1.0": 1,
    "2 protected cell violations": 1
  },
  "results": {
    "task_001": { ... },
    "task_002": { ... }
  }
}
```

## 常见拒绝原因及修复

### 1. accuracy < 1.0

**症状**: 官方评分不满分

**原因**:
- answer区域的值/公式与golden不匹配
- 计算结果有微小偏差（超过1%容差）

**修复**:
- 检查LLM rollout生成的操作是否完整
- 确保所有answer区域的单元格都被正确修改
- 检查公式引用是否正确

### 2. LibreOffice recalc failed

**症状**: 重算后结果不一致

**原因**:
- 循环引用
- 外部链接断开
- 不支持的函数

**修复**:
- 避免循环引用
- 使用工作簿内部引用
- 使用LibreOffice支持的函数

### 3. Protected cell violations

**症状**: 修改了answer_position外的单元格

**原因**:
- LLM rollout执行的批量操作范围过大
- 误修改了格式或隐藏属性

**修复**:
- 精确定位answer区域
- 只修改值/公式，不动格式
- 使用view_xlsx确认修改范围

### 4. Formula family mismatch

**症状**: 公式模式与golden不一致

**原因**:
- 使用硬编码而非公式
- 公式结构不同

**修复**:
- 确保使用与golden相同的公式模式
- 检查相对/绝对引用

### 5. Invariants failed

**症状**: 财务约束验证失败

**原因**:
- 资产≠负债+权益
- 三表勾稽关系断裂

**修复**:
- 检查关键公式的引用
- 确保期初/期末连续性

### 6. Excel errors in answer region

**症状**: answer区域包含错误标记

**原因**:
- 引用被删除的单元格
- 类型不匹配
- 除以零

**修复**:
- 验证所有引用有效
- 确保数据类型正确
- 检查除数不为零

### 7. Style not preserved

**症状**: 样式被破坏

**原因**:
- 合并单元格被取消
- 命名区域被删除

**修复**:
- 谨慎处理合并单元格
- 不要删除命名区域

## 工作流集成

### 在LLM rollout轨迹生成后自动验证

```bash
# 1. 生成LLM rollout轨迹
python scripts/batch_generate_trajectories.py \
    generated_tasks/test_batch_debugging \
    --output trajectories/test_batch

# 2. 验证轨迹
python scripts/test_trajectory_verifier.py \
    trajectories/test_batch --batch \
    --output trajectories/test_batch/verification_report.json

# 3. 过滤出通过验证的轨迹
python scripts/filter_approved_trajectories.py \
    trajectories/test_batch/verification_report.json \
    --output trajectories/approved/
```

### 在CI/CD中使用

```yaml
# .github/workflows/verify_trajectories.yml
name: Verify Trajectories

on:
  push:
    paths:
      - 'trajectories/**'

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.11
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Verify trajectories
        run: |
          python scripts/test_trajectory_verifier.py \
            trajectories/latest --batch \
            --output trajectories/latest/verification_report.json
      - name: Check approval rate
        run: |
          RATE=$(jq '.approval_rate' trajectories/latest/verification_report.json)
          if (( $(echo "$RATE < 0.95" | bc -l) )); then
            echo "Approval rate $RATE < 95%, failing CI"
            exit 1
          fi
```

## 性能优化

### 并行验证（未来功能）

```python
from verify.trajectory_verifier import TrajectoryVerifier
from concurrent.futures import ProcessPoolExecutor

verifier = TrajectoryVerifier()

with ProcessPoolExecutor(max_workers=8) as executor:
    futures = []
    for task_dir in task_dirs:
        future = executor.submit(verifier.verify, task_dir)
        futures.append(future)
    
    results = [f.result() for f in futures]
```

### 缓存WorkbookParser结果

```python
# 对于重复验证同一批轨迹，可以缓存解析结果
verifier = TrajectoryVerifier(cache_dir="/tmp/parser_cache")
```

## 调试技巧

### 查看详细日志

```bash
export LOG_LEVEL=DEBUG
python scripts/test_trajectory_verifier.py task_dir
```

### 比较input vs output

```bash
# 使用diff工具比较
python -c "
from verify.trajectory_verifier import TrajectoryVerifier
v = TrajectoryVerifier()
v._check_protected_cells('input.xlsx', 'output.xlsx', answer_positions)
"
```

### 检查公式归一化

```bash
python -c "
from verify.trajectory_verifier import TrajectoryVerifier
v = TrajectoryVerifier()
f1 = v._normalize_formula('=SUM(A1:A10)')
f2 = v._normalize_formula('= sum( a1 : a10 )')
print(f1 == f2)  # True
"
```

## 下一步

完成S5轨迹验证器后，下一步工作：

1. **在真实LLM rollout轨迹上测试**: 生成LLM rollout轨迹并运行批量验证
2. **实现过滤脚本**: 只保留approved=True的轨迹进入正样本池
3. **S6样本组装**: 将通过验证的轨迹转换为HuggingFace格式

## 参考文档

- [S5_TRAJECTORY_VERIFICATION.md](./S5_TRAJECTORY_VERIFICATION.md) - 详细设计文档
- [PROJECT_STATUS.md](./PROJECT_STATUS.md) - 项目进度跟踪
- [官方评分服务](../verify/scorer.py) - OfficialScorer实现
- [WorkbookParser](../parse/workbook_parser.py) - S1元数据提取
