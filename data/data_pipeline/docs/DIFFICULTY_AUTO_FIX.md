# 难度自动修正功能

## 背景

在Enron Batch1管线运行中发现，S2生成阶段的难度标注算法存在系统性偏差，导致大量Debugging任务被标注为L2，但实际难度应该是L3。这些任务本身质量完全没有问题（有唯一解、无污染），仅因为难度标注不准确而被S3筛选拒绝。

## 问题统计

- **Enron Batch1**: 32个Debugging任务中，31个仅因难度问题被拒
  - 30个任务: L2 → L3
  - 1个任务: L2 → L1
  - 任务本身质量：✓ 有唯一解 ✓ 无污染

## 解决方案

在S3筛选阶段新增**难度自动修正**功能：

### 工作原理

1. **检测难度偏差**: S3重新计算任务难度得分，与标注对比
2. **自动修正**: 如果检测到偏差，直接修改任务JSON中的`difficulty`字段
3. **标记通过**: 修正后的任务视为通过难度检查，不会被拒绝
4. **记录日志**: 在筛选报告中标记为"Difficulty auto-fixed"

### 启用方式

```python
from screen.task_screener import TaskScreener

# 创建筛选器时启用自动修正（默认开启）
screener = TaskScreener(
    contamination_scanner=scanner,
    unique_solution_validator=validator,
    auto_fix_difficulty=True  # 默认True
)

# 筛选任务
result = screener.screen_task(
    task_json_path,
    check_difficulty=True
)
```

### 禁用方式

如果需要保持原有的拒绝行为（不自动修正），可以显式禁用：

```python
screener = TaskScreener(
    auto_fix_difficulty=False  # 禁用自动修正
)
```

## 效果对比

### 修正前 (Enron Batch1)

```
总任务数: 88个
通过: 51个 (57.95%)
  - Debugging: 0个 (0%)
  - Template: 51个 (91%)
拒绝: 37个
  - 31个Debugging任务仅因难度问题被拒
```

### 修正后

```
总任务数: 88个
通过: 82个 (93.2%)
  - Debugging: 31个 (96.9%)
  - Template: 51个 (91%)
拒绝: 6个
  - 1个污染任务
  - 5个其他问题
自动修正: 31个
```

**提升效果**: 通过率从57.95%提升到93.2%，挽救了31个高质量任务！

## 难度计算规则

S3使用以下规则重新计算难度得分（0-100分）：

| 因素 | 权重 | 评分规则 |
|------|------|----------|
| 答案单元格数 | 30分 | <10: 5分; 10-30: 15分; 30-50: 25分; ≥50: 30分 |
| 公式单元格数 | 30分 | <10: 5分; 10-50: 15分; 50-100: 25分; ≥100: 30分 |
| Sheet数量 | 20分 | ≤2: 5分; 3-5: 10分; 6-10: 15分; >10: 20分 |
| 不变量约束 | 20分 | 0个: 0分; 1-2个: 10分; ≥3个: 20分 |

得分映射到难度级别：
- **L1**: 0-29分
- **L2**: 30-49分
- **L3**: 50-69分
- **L4**: 70-100分

## 日志示例

### 自动修正日志

```
2026-09-03 16:30:15 - INFO - ✓ 自动修正难度: 001_001_native_003_double_counting_4657 L2 → L3
2026-09-03 16:30:15 - INFO - 筛选结果: 001_001_native_003_double_counting_4657 - ✓ 通过
2026-09-03 16:30:15 - INFO -   - Difficulty auto-fixed: L2 → L3
```

### 筛选报告

```json
{
  "task_id": "001_001_native_003_double_counting_4657",
  "passed": true,
  "unique_solution": true,
  "contaminated": false,
  "difficulty_valid": true,
  "difficulty_adjusted": "L3",
  "issues": ["Difficulty auto-fixed: L2 → L3"]
}
```

### 统计输出

```
================================================================================
任务筛选总结
================================================================================
总任务数: 88
通过: 82 (93.2%)
失败: 6 (6.8%)

处理详情:
  难度自动修正: 31
  唯一解验证失败: 4
  污染检测命中: 2
  难度标注偏差(未修正): 0
================================================================================
```

## 适用场景

### ✅ 适合自动修正

- Debugging任务的难度标注系统性偏差
- Template任务的难度计算偏差
- 任务其他方面质量良好（有唯一解、无污染）

### ⚠️ 不适合自动修正

- 如果难度计算规则本身有问题，应该修改计算规则而非自动修正
- 需要人工审核难度标注的场景

## 测试

运行单元测试验证功能：

```bash
cd /mnt/hhq/data/data_pipeline
python3 scripts/test_auto_fix_difficulty.py
```

测试覆盖：
1. 不自动修正模式（保持原有拒绝行为）
2. 自动修正模式（修正难度并通过）

## 相关文件

- **核心实现**: `screen/task_screener.py`
- **测试脚本**: `scripts/test_auto_fix_difficulty.py`
- **案例研究**: `generated_tasks/route_b_enron_batch1/FINAL_REPORT.md`

## 更新日志

- **2026-09-03**: 首次实现难度自动修正功能
  - 新增 `auto_fix_difficulty` 参数（默认True）
  - 新增 `_fix_difficulty()` 方法
  - 更新筛选统计，新增 `difficulty_auto_fixed` 计数
  - Enron Batch1验证：成功挽救31个Debugging任务
