# Route A LLM生成器使用指南

## 概述

`generate_route_a_tasks.py` 是路线A的核心LLM生成器，用于自动生成FM和Visualization任务。该脚本集成了Claude API，实现了从seed工作簿到完整任务包的全自动生成流程。

**生成能力**:
- FM任务: 10-15个/小时
- Visualization任务: 15-20个/小时
- 支持自定义难度分布
- 自动重试和错误处理

---

## 快速开始

### 1. 环境准备

```bash
# 设置API密钥
export ANTHROPIC_API_KEY="sk-ant-xxx"

# 或者在命令中指定
--api-key "sk-ant-xxx"
```

### 2. 准备Seed库

```bash
# 使用collect_seed_workbooks.py收集高质量seed
python scripts/collect_seed_workbooks.py scan /path/to/candidates
python scripts/collect_seed_workbooks.py import seed_library/ --min-score 70
```

### 3. 生成任务

#### FM任务示例

```bash
# 生成10个FM任务（默认L3:40%, L4:60%）
python scripts/generate_route_a_tasks.py \
    --task-type fm \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/fm_batch_001 \
    --count 10

# 自定义难度分布
python scripts/generate_route_a_tasks.py \
    --task-type fm \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/fm_batch_002 \
    --count 20 \
    --difficulty-mix "L3:0.5,L4:0.5"
```

#### Visualization任务示例

```bash
# 生成10个Visualization任务（默认L2:30%, L3:70%）
python scripts/generate_route_a_tasks.py \
    --task-type viz \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/viz_batch_001 \
    --count 10

# 更多L3任务
python scripts/generate_route_a_tasks.py \
    --task-type visualization \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/viz_batch_002 \
    --count 15 \
    --difficulty-mix "L2:0.2,L3:0.8"
```

---

## 生成流程

### 6步自动化流程

```
1. Seed Analysis
   ├─ 读取seed工作簿
   ├─ 提取sheet结构、公式数量、列标题
   └─ 检测领域（Corporate Finance, Business Analytics等）

2. Scenario Design
   ├─ 调用Claude API分析seed
   ├─ 设计真实财务/可视化场景
   └─ 生成JSON格式的场景描述

3. Golden Workbook Generation
   ├─ Claude API生成openpyxl代码
   ├─ 代码包含真实数据和公式
   ├─ 执行代码生成{task_id}_golden.xlsx
   └─ 验证文件生成成功

4. Input Workbook Generation
   ├─ FM任务: input = golden（用户需理解现有模型）
   └─ Visualization任务: 复制数据，删除图表

5. Instruction Generation
   ├─ 调用Claude API生成任务指令
   ├─ Markdown格式: 背景/任务/要求/提示
   └─ 150-300字，清晰无歧义

6. Task Assembly
   ├─ 生成criteria和answer_position
   ├─ 填充metadata（route, domain, concepts, lineage等）
   └─ 保存task.json
```

### 输出结构

```
generated_tasks/fm_batch_001/
├── fm_20260818_001/
│   ├── task.json
│   ├── fm_20260818_001_input.xlsx
│   └── fm_20260818_001_golden.xlsx
├── fm_20260818_002/
│   ├── task.json
│   ├── fm_20260818_002_input.xlsx
│   └── fm_20260818_002_golden.xlsx
├── ...
└── generation_report.json
```

---

## 命令行参数

### 必需参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--task-type` | 任务类型 | `fm`, `visualization`, `viz` |
| `--seed-dir` | Seed工作簿目录 | `seed_library/` |
| `--output-dir` | 输出目录 | `generated_tasks/batch_001` |

### 可选参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--count` | 10 | 生成任务数量 |
| `--difficulty-mix` | FM: "L3:0.4,L4:0.6"<br>Viz: "L2:0.3,L3:0.7" | 难度分布 |
| `--api-key` | 从环境变量读取 | Anthropic API密钥 |
| `--model` | `claude-3-5-sonnet-20241022` | Claude模型 |
| `--log-level` | `INFO` | 日志级别 |

---

## 质量保证

### 自动验证

生成后自动执行验证流程：

```bash
# 验证生成的批次
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-report fm_batch_001_validation.json

# 快速验证（跳过S0检查）
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-report fm_batch_001_validation.json \
    --skip-s0
```

### 打包提交

```bash
# 打包通过验证的任务
python scripts/package_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-dir packaged_batches \
    --batch-id fm_batch_001 \
    --validation-report fm_batch_001_validation.json
```

### 质量标准

#### FM批次标准
- **最小规模**: ≥15个任务
- **难度分布**: L3≥40%, L4≥40%
- **领域多样性**: ≥3个不同domain
- **首次验证通过率**: 目标≥80%

#### Visualization批次标准
- **最小规模**: ≥8个任务
- **难度分布**: L2≥30%, L3≥50%
- **图表类型多样性**: ≥5种不同类型
- **首次验证通过率**: 目标≥80%

---

## 错误处理

### 常见问题

#### 1. API调用失败

**症状**: `API call failed after 3 attempts`

**原因**: API密钥无效、网络问题、速率限制

**解决**:
```bash
# 检查API密钥
echo $ANTHROPIC_API_KEY

# 降低并发（减少--count）
--count 5

# 增加重试间隔（代码会自动exponential backoff）
```

#### 2. 代码执行超时

**症状**: `Code execution timeout (>60s)`

**原因**: 生成的Python代码过于复杂或有死循环

**解决**:
- 检查生成的临时脚本（错误时会保留）
- 简化seed工作簿结构
- 调整prompt模板（降低复杂度要求）

#### 3. S0门槛失败

**症状**: 验证报告显示`S0 threshold check failed`

**原因**: 
- 生成的工作簿包含公式错误
- LibreOffice重算不一致

**解决**:
```bash
# 重新生成失败的任务
# 使用不同的seed或调整difficulty

# 检查具体错误
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-report validation.json \
    --log-level DEBUG
```

#### 4. 难度分布不符合要求

**症状**: 批次中L3/L4比例不满足标准

**原因**: 随机采样导致的偏差

**解决**:
```bash
# 生成更多任务以平衡分布
--count 25

# 或明确指定难度分布
--difficulty-mix "L3:0.5,L4:0.5"
```

---

## 性能优化

### 1. 批量生成策略

```bash
# 小批次测试（5个任务，验证prompt质量）
python scripts/generate_route_a_tasks.py \
    --task-type fm --count 5 \
    --output-dir generated_tasks/test_batch

# 中批次生产（15-20个任务）
python scripts/generate_route_a_tasks.py \
    --task-type fm --count 20 \
    --output-dir generated_tasks/fm_batch_001

# 避免单次生成过多任务（>30）
# API成本高，失败风险大
```

### 2. Seed选择策略

```bash
# 使用高质量seed（质量分≥70）
python scripts/collect_seed_workbooks.py import seed_library/ --min-score 70

# Seed库规模建议
# FM: 50-100个seed（财务建模多样性）
# Visualization: 30-50个seed（数据可视化场景）
```

### 3. 并行生成

```bash
# 在不同终端并行生成不同批次
# Terminal 1
python scripts/generate_route_a_tasks.py \
    --task-type fm --count 10 \
    --output-dir generated_tasks/fm_batch_001

# Terminal 2
python scripts/generate_route_a_tasks.py \
    --task-type viz --count 10 \
    --output-dir generated_tasks/viz_batch_001

# 注意：共享API速率限制，建议总并发≤2
```

---

## 生成报告解读

### generation_report.json结构

```json
{
  "task_type": "fm",
  "count_requested": 10,
  "count_succeeded": 9,
  "count_failed": 1,
  "difficulty_distribution": {
    "L3": 0.4,
    "L4": 0.6
  },
  "model": "claude-3-5-sonnet-20241022",
  "timestamp": "2026-08-18T10:30:45",
  "results": [
    {
      "task_id": "fm_20260818_001",
      "success": true,
      "error": null,
      "generation_time_seconds": 45.3
    },
    {
      "task_id": "fm_20260818_002",
      "success": false,
      "error": "Code execution timeout (>60s)",
      "generation_time_seconds": 60.0
    }
  ]
}
```

### 关键指标

- **成功率**: `count_succeeded / count_requested`
  - 目标: ≥80%
  - <70%: 检查seed质量或prompt模板

- **平均生成时间**: `avg(generation_time_seconds)`
  - FM: 40-60秒/任务 (理想 10-15/小时)
  - Viz: 30-45秒/任务 (理想 15-20/小时)

- **失败原因分布**:
  - `Failed to analyze seed`: seed文件损坏
  - `Failed to design scenario`: API调用失败或JSON解析错误
  - `Failed to generate golden workbook`: 代码生成或执行失败
  - `Code execution timeout`: 代码过于复杂

---

## 完整工作流示例

### 场景：生成首批FM批次（20个任务）

```bash
# Step 1: 准备环境
export ANTHROPIC_API_KEY="sk-ant-xxx"
cd /mnt/hhq/data/data_pipeline

# Step 2: 准备seed库（如未准备）
python scripts/collect_seed_workbooks.py scan /path/to/sheetpedia
python scripts/collect_seed_workbooks.py import seed_library/ --min-score 70

# Step 3: 小批次测试（5个任务）
python scripts/generate_route_a_tasks.py \
    --task-type fm \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/test_batch \
    --count 5

# Step 4: 验证测试批次
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/test_batch \
    --output-report test_validation.json

# Step 5: 如果测试通过（通过率≥80%），生成生产批次
python scripts/generate_route_a_tasks.py \
    --task-type fm \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/fm_batch_001 \
    --count 20 \
    --difficulty-mix "L3:0.4,L4:0.6"

# Step 6: 验证生产批次
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-report fm_batch_001_validation.json

# Step 7: 打包通过验证的任务
python scripts/package_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-dir packaged_batches \
    --batch-id fm_batch_001 \
    --validation-report fm_batch_001_validation.json

# Step 8: 人工抽检（20%样本）
# 随机选择4个任务进行人工审核

# Step 9: 如果抽检通过，提交审核
# 上传packaged_batches/fm_batch_001到共享存储
```

---

## 成本估算

### API调用成本

**Claude 3.5 Sonnet定价** (2024年价格):
- Input: $3 / 1M tokens
- Output: $15 / 1M tokens

**每个任务估算**:
- FM任务: ~20K input tokens, ~8K output tokens
  - 成本: $0.06 + $0.12 = **$0.18/任务**
- Visualization任务: ~15K input tokens, ~6K output tokens
  - 成本: $0.045 + $0.09 = **$0.135/任务**

**批次成本**:
- FM批次（20个任务）: ~$3.60
- Visualization批次（10个任务）: ~$1.35
- **总计300个任务**: ~$48（FM: 200 × $0.18）+ $13.5（Viz: 100 × $0.135）= **~$61.50**

---

## 下一步

生成器实现完成后，下一步工作：

1. **准备Seed库** (W5)
   - 目标: 200个高质量seed（质量分≥70）
   - 使用`collect_seed_workbooks.py`收集

2. **首批测试生成** (W5)
   - FM: 5个测试任务
   - Viz: 5个测试任务
   - 验证生成质量和通过率

3. **优化Prompt模板** (W5)
   - 基于测试结果调整prompt
   - 提高首次验证通过率

4. **规模化生产** (W6-W8)
   - FM: 200个任务（10-15批次）
   - Visualization: 100个任务（8-10批次）

---

## 参考文档

- **Prompt模板**: `generate/instruct/fm_generation_prompt.md`, `viz_generation_prompt.md`
- **验证脚本**: `scripts/validate_route_a_batch.py`
- **打包脚本**: `scripts/package_route_a_batch.py`
- **任务模板**: `generate/instruct/task_template.json`
- **完整工作流**: `docs/ROUTE_A_SUBMISSION_WORKFLOW.md`
- **基础设施总结**: `docs/ROUTE_A_INFRASTRUCTURE_SUMMARY.md`

---

**文档版本**: v1.0  
**最后更新**: 2026-08-18  
**维护者**: Pipeline团队
