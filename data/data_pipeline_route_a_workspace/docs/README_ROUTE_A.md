# 路线A：LLM生成路径

## 概述

路线A是SpreadsheetBench 2 SFT数据生产管线中的LLM自动生成路径，专注于构造高质量的FM（财务建模）和Visualization（可视化）任务。这些任务通过大语言模型从seed工作簿出发，自动生成完整的任务三元组（input, golden, task.json）。

## 任务类型

### FM（财务建模）任务
复杂的财务分析和建模任务，要求深入的财务知识和Excel专业技能。

**典型场景**:
- 三表模型构建（损益表、资产负债表、现金流量表）
- DCF估值计算
- 敏感性分析
- 情景建模
- LBO模型
- 合并财务报表

**难度**: 主要L3-L4  
**目标数量**: 200个任务

### Visualization（可视化）任务
专业的数据可视化和图表设计任务，强调视觉传达和洞察表达。

**典型场景**:
- 商业仪表板构建
- 趋势分析图表
- 对比可视化
- 地理数据可视化
- 组合图表设计

**难度**: 主要L2-L3  
**目标数量**: 100个任务

## 生成流程

### 1. Seed工作簿准备
```bash
# 收集和评分seed工作簿
python scripts/collect_seed_workbooks.py scan /path/to/candidates

# 导入高质量seed（质量评分≥70）
python scripts/collect_seed_workbooks.py import seed_library/ --min-score 70
```

### 2. LLM任务生成
```bash
# 生成FM任务
python scripts/generate_route_a_tasks.py \
    --task-type fm \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/fm_batch_001 \
    --count 20 \
    --difficulty-mix "L3:0.4,L4:0.6"

# 生成Visualization任务
python scripts/generate_route_a_tasks.py \
    --task-type visualization \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/viz_batch_001 \
    --count 10 \
    --difficulty-mix "L2:0.3,L3:0.7"
```

### 3. 自动验证
```bash
# 完整验证
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-report validation_report.json

# 查看结果
cat validation_report.json | jq .
```

### 4. 打包提交
```bash
# 打包批次
python scripts/package_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-dir packaged_batches \
    --batch-id fm_batch_001 \
    --validation-report validation_report.json
```

## LLM生成器架构

### 核心组件
1. **Seed Analyzer**: 分析seed工作簿结构、领域、复杂度
2. **Scenario Designer**: 基于seed特征生成真实业务场景
3. **Golden Constructor**: 构造完整的财务模型或可视化
4. **Input Constructor**: 从golden反推起点状态
5. **Instruction Writer**: 生成清晰的自然语言指令
6. **Metadata Filler**: 自动填充task.json所有字段

### 生成策略

**FM任务生成**:
- 分析seed的财务结构（三表、估值模型等）
- 生成符合行业标准的业务场景
- 确保公式逻辑正确、数据一致
- 自动评估难度（基于概念数量、公式复杂度）

**Visualization任务生成**:
- 识别seed中的数据表结构
- 生成合理的可视化需求
- 构造专业的图表和仪表板
- 自动生成Tier 1/2验证标准

## 工具链

### 生成工具
**generate_route_a_tasks.py** (待实现)

LLM驱动的任务生成器，功能包括:
- Seed工作簿选择和分析
- 业务场景自动设计
- Golden/Input工作簿构造
- Task.json元数据自动填写
- 批量生成和难度控制

```bash
# 基本用法
python scripts/generate_route_a_tasks.py \
    --task-type {fm|visualization} \
    --seed-dir /path/to/seeds \
    --output-dir /path/to/output \
    --count 20 \
    [--difficulty-mix "L3:0.4,L4:0.6"] \
    [--domains "Corporate Finance,M&A"] \
    [--model claude-3-5-sonnet-20241022]
```

### 验证工具
**validate_route_a_batch.py**

完整的任务质量验证脚本，检查:
- 文件完整性（task.json, input.xlsx, golden.xlsx）
- 元数据完整性（15个必填字段）
- S0门槛（LibreOffice重算一致性）
- 任务类型特定验证（FM concepts, Visualization criteria）

```bash
# 使用示例
python scripts/validate_route_a_batch.py \
    --task-dir /path/to/tasks \
    --output-report report.json \
    [--skip-s0]  # 可选：快速验证模式
```

### 打包工具
**package_route_a_batch.py**

标准化任务格式并生成提交包:
- 过滤未通过验证的任务
- 文件名标准化
- 生成批次索引（batch_index.json）
- 生成打包报告（packaging_report.json）

```bash
# 使用示例
python scripts/package_route_a_batch.py \
    --task-dir /path/to/tasks \
    --output-dir /path/to/output \
    --batch-id batch_001 \
    --validation-report validation_report.json
```

## 质量标准

### FM批次标准
- ✓ 至少15个任务
- ✓ 难度分布: L3≥40%, L4≥40%
- ✓ 领域多样: ≥3个不同domain
- ✓ 概念覆盖: ≥10个不同concepts
- ✓ 100%通过S0门槛检查
- ✓ 100%有唯一解或等价条件

### Visualization批次标准
- ✓ 至少8个任务
- ✓ 难度分布: L2≥30%, L3≥50%
- ✓ 图表多样: ≥5种不同类型
- ✓ Tier1 criteria覆盖≥70%
- ✓ 100%通过S0门槛检查

### 单任务标准
- ✓ Input信息充分，可完成任务
- ✓ Golden正确，代表唯一合理解
- ✓ Instruction清晰无歧义
- ✓ Criteria可验证，覆盖关键点
- ✓ 无答案泄漏
- ✓ 场景真实，符合业务需求

## 工作流程

```
1. 选择Seed工作簿
   ↓
2. LLM分析Seed结构和特征
   ↓
3. LLM设计业务场景
   ↓
4. LLM构造Golden工作簿（正确答案）
   ↓
5. LLM构造Input工作簿（移除答案）
   ↓
6. LLM编写Instruction（结构化指令）
   ↓
7. LLM填写Metadata（task.json）
   ↓
8. 自动验证（validate_route_a_batch.py）
   ↓
9. 人工审核抽检（20%样本）
   ↓
10. 批准并集成到主Pipeline
```

## 批次跟踪

### 批次状态流转
1. **Generating** - LLM生成中
2. **Pending Validation** - 等待自动验证
3. **Validation Failed** - 验证失败（需重新生成）
4. **Ready for Review** - 验证通过，等待抽检
5. **Under Review** - 人工审核中
6. **Revision Requested** - 审核要求修改
7. **Approved** - 审核通过
8. **Integrated** - 集成到主pipeline

### 批次元数据
每个批次维护一个状态文件（batch_status.json）记录:
- 批次ID和状态
- 创建/提交/批准日期
- 任务数量和类型分布
- LLM模型和参数
- 备注信息

## 常见问题

### Q1: 如何选择合适的Seed工作簿？
使用`scripts/collect_seed_workbooks.py`扫描并评分:
```bash
python scripts/collect_seed_workbooks.py scan /path/to/candidates
```
选择质量评分≥70、通过S0门槛、公式密度10-100的工作簿。

### Q2: S0门槛检查失败怎么办？
LLM生成的任务如果S0失败，通常需要重新生成：
- 检查生成日志了解失败原因
- 调整生成prompt或参数
- 使用不同的seed重新生成

### Q3: 如何确保任务有唯一解？
LLM生成器会：
- FM任务: 指令明确方法，criteria覆盖等价条件
- 避免指令模糊
- 确保golden是唯一合理解

### Q4: Visualization criteria如何生成？
LLM自动生成两级criteria:
- **Tier 1** (自动验证, ≥70%): 图表存在性、类型、数据源、标题、轴标签
- **Tier 2** (VLM验证, ~15%): 颜色合理性、格式美观性、洞察清晰度

### Q5: 批次应该多大？
- **FM批次**: 15-25个任务（生成时间~1-2小时）
- **Visualization批次**: 8-15个任务（生成时间~30-60分钟）
- **建议**: 小批次快速验证，易于调整参数

## 关键文件

### 文档
- `docs/ROUTE_A_QUICK_START.md` - 快速开始指南
- `docs/ROUTE_A_LLM_GENERATION_GUIDE.md` - LLM生成详细指南
- `docs/ROUTE_A_INFRASTRUCTURE_SUMMARY.md` - 基础设施总结

### 模板
- `generate/instruct/task_template.json` - 任务元数据模板
- `generate/instruct/fm_generation_prompt.md` - FM任务生成prompt模板
- `generate/instruct/viz_generation_prompt.md` - Visualization任务生成prompt模板

### 工具
- `scripts/generate_route_a_tasks.py` - LLM任务生成器（待实现）
- `scripts/validate_route_a_batch.py` - 批量验证脚本（357行）
- `scripts/package_route_a_batch.py` - 批量打包脚本（270行）

### 辅助
- `scripts/collect_seed_workbooks.py` - Seed收集和评分工具

## 技术集成

### 复用现有组件
- **WorkbookValidator** (ingest/validators.py): S0门槛检查
- **UniqueSolutionValidator** (screen/unique_solution_validator.py): 唯一解验证
- **Task Schema** (schemas/task.schema.json): 统一任务格式

### 与路线B对比

| 维度 | 路线A | 路线B |
|------|-------|-------|
| 任务类型 | FM, Visualization | Debugging, Template |
| 难度 | L3-L4 (FM), L2-L3 (Viz) | L1-L4自动分级 |
| 生成方式 | LLM从seed创造新任务 | 规则变换现有工作簿 |
| 产能 | 数十个/小时 | 数百个/小时 |
| 质量 | 高（LLM+人工抽检） | 中（算法保证） |
| 成本 | 中（LLM API调用） | 低（计算资源） |
| 适用场景 | 复杂推理、创意任务 | 规则化、可枚举任务 |
| 目标数量 | 300个 (FM: 200, Viz: 100) | 900个 (Debugging: 400, Template: 500) |

## 成功指标

### 产能指标
- FM任务产能: 目标10-15个/小时
- Visualization任务产能: 目标15-20个/小时
- 首次验证通过率: 目标≥70%
- 审核批准率: 目标≥90%

### 质量指标
- S0通过率: 目标≥95%
- 唯一解比例: 目标100%（FM）
- Criteria可验证性: 目标100%
- 污染率: 目标<1%

## 联系方式

- **技术支持**: pipeline-team@project.com
- **审核协调**: review-coord@project.com

---

**版本**: v2.0 (LLM生成版本)  
**最后更新**: 2026-08-17  
**状态**: 🚧 LLM生成器开发中，验证和打包工具已完成
