# 路线A任务提交流程

## 概述

本文档描述LLM自动生成的FM和Visualization任务的提交和验证流程。

## 角色和职责

### Pipeline开发者
- 配置和运行LLM生成器
- 准备高质量seed工作簿库
- 监控生成质量和产能
- 调整生成参数优化输出

### 审核员
- 验证生成的任务批次
- 人工抽检20%样本
- 批准或拒绝任务批次

### Pipeline工程师
- 维护LLM生成器和验证工具
- 集成批准的任务到主pipeline
- 监控任务质量指标

## 提交流程

### Step 1: 准备Seed工作簿库

运行LLM生成器前，需要准备高质量seed库：

```bash
# 扫描候选seed工作簿并评分
python scripts/collect_seed_workbooks.py scan /path/to/candidates

# 导入高质量seed（质量评分≥70）
python scripts/collect_seed_workbooks.py import seed_library/ --min-score 70

# 查看seed库统计
python scripts/collect_seed_workbooks.py stats seed_library/
```

**Seed质量要求**:
- 通过S0门槛（重算一致性）
- 公式密度10-100（不能太少或太多）
- 结构清晰（2-10个sheets）
- 领域相关（财务建模或数据分析）

### Step 2: 生成任务批次

使用LLM生成器自动生成任务：

```bash
# 生成FM任务批次
python scripts/generate_route_a_tasks.py \
    --task-type fm \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/fm_batch_001 \
    --count 20 \
    --difficulty-mix "L3:0.4,L4:0.6" \
    --domains "Corporate Finance,M&A,Project Finance" \
    --model claude-3-5-sonnet-20241022

# 生成Visualization任务批次
python scripts/generate_route_a_tasks.py \
    --task-type visualization \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/viz_batch_001 \
    --count 10 \
    --difficulty-mix "L2:0.3,L3:0.7" \
    --model claude-3-5-sonnet-20241022
```

LLM生成器将自动完成：
1. 分析seed工作簿结构和特征
2. 生成真实的业务场景
3. 构造golden工作簿（完整答案）
4. 构造input工作簿（移除答案）
5. 生成自然语言指令
6. 自动填写task.json元数据

生成后的任务按以下结构组织：

```
batch_001/
├── fm_001_dcf_valuation/
│   ├── task.json
│   ├── fm_001_dcf_valuation_input.xlsx
│   └── fm_001_dcf_valuation_golden.xlsx
├── fm_002_revenue_forecast/
│   ├── task.json
│   ├── fm_002_revenue_forecast_input.xlsx
│   └── fm_002_revenue_forecast_golden.xlsx
└── viz_001_revenue_chart/
    ├── task.json
    ├── viz_001_revenue_chart_input.xlsx
    └── viz_001_revenue_chart_golden.xlsx
```

**目录命名规范**:
- FM任务: `fm_{序号}_{简短描述}`
- Visualization任务: `viz_{序号}_{简短描述}`

**文件命名规范**:
- task.json: 固定名称
- 工作簿: `{任务目录名}_input.xlsx` 和 `{任务目录名}_golden.xlsx`

### Step 3: 自动验证

使用验证脚本检查生成的任务质量：

```bash
cd /mnt/hhq/data/data_pipeline

# 完整验证（包含S0检查）
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-report fm_batch_001_validation.json
```

**验证项目**:
- ✓ 文件完整性（task.json, input.xlsx, golden.xlsx存在）
- ✓ 元数据完整性（所有必填字段存在）
- ✓ S0门槛检查（input和golden都能通过重算一致性）
- ✓ 任务类型和难度正确性
- ✓ Criteria和answer_position非空
- ✓ FM任务concepts字段非空
- ✓ Visualization任务visualization_criteria结构正确

**快速验证模式**（跳过S0检查，开发时使用）:
```bash
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-report fm_batch_001_validation.json \
    --skip-s0
```

### Step 4: 修复和重新生成

如果验证失败，检查报告中的issues：

```bash
cat fm_batch_001_validation.json | jq '.results[] | select(.passed == false)'
```

**处理方式**:
- **S0检查失败**: LLM生成的公式有错误，需要重新生成该任务
- **元数据不完整**: 检查生成prompt，调整LLM输出格式
- **指令质量差**: 调整generation prompt，增加instruction质量要求

重新生成失败的任务：
```bash
python scripts/regenerate_single_task.py \
    --task-id fm_001_dcf_valuation \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/fm_batch_001 \
    --strict-mode
```

### Step 5: 打包提交

验证通过后，打包任务：

```bash
python scripts/package_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-dir packaged_batches \
    --batch-id fm_batch_001 \
    --validation-report fm_batch_001_validation.json
```

这将：
1. 只打包通过验证的任务
2. 标准化文件名
3. 生成批次索引（batch_index.json）
4. 生成打包报告（packaging_report.json）

输出结构：
```
packaged_batches/
└── fm_batch_001/
    ├── batch_index.json          # 批次索引
    ├── packaging_report.json     # 打包报告
    ├── fm_001_dcf_valuation/
    │   ├── task.json
    │   ├── fm_001_dcf_valuation_input.xlsx
    │   └── fm_001_dcf_valuation_golden.xlsx
    └── fm_002_revenue_forecast/
        ├── task.json
        ├── fm_002_revenue_forecast_input.xlsx
        └── fm_002_revenue_forecast_golden.xlsx
```

### Step 6: 人工抽检

随机抽取20%任务进行人工审核：

```bash
# 随机抽取样本
python scripts/sample_for_review.py \
    --batch-dir packaged_batches/fm_batch_001 \
    --sample-rate 0.2 \
    --output review_sample_001.json

# 审核员审核样本，标注审核结果
# 根据审核结果决定是否批准整个批次
```

### Step 7: 提交集成

将打包的批次提交给审核员：

1. **上传到共享存储**:
```bash
# 示例：上传到项目共享目录
rsync -av packaged_batches/fm_batch_001/ \
    /shared/route_a_submissions/fm_batch_001/
```

2. **通知审核员**:
   - 发送邮件或消息
   - 附上batch_index.json和packaging_report.json摘要
   - 说明批次规模、任务类型分布、抽检结果

3. **等待审核批准**:
   - 审核员验证抽检样本质量
   - 批准后进入主pipeline集成

## 审核标准

### 任务质量标准

**必须满足**:
- ✓ 通过所有自动化验证
- ✓ 指令清晰无歧义
- ✓ Input信息充分，可完成任务
- ✓ Golden正确，代表唯一合理解
- ✓ Criteria可验证，覆盖关键点

**建议达到**:
- ✓ 场景真实，符合业务需求
- ✓ 难度适当，与标注一致
- ✓ 格式专业，符合行业规范
- ✓ 无明显快捷方式或泄漏

### 批次质量标准

**FM批次**:
- 至少15个任务
- 难度分布：L3≥40%, L4≥40%
- 领域多样：至少3个不同domain
- 概念覆盖：至少10个不同concepts

**Visualization批次**:
- 至少8个任务
- 难度分布：L2≥30%, L3≥50%
- 图表类型多样：至少5种不同类型
- Tier1 criteria覆盖≥70%

## 批次跟踪

### 批次状态

1. **生成中（Generating）**: LLM生成任务中
2. **待验证（Pending Validation）**: 等待自动验证
3. **验证失败（Validation Failed）**: 需要重新生成或修复
4. **待抽检（Ready for Review）**: 验证通过，等待人工抽检
5. **抽检中（Under Review）**: 人工审核样本中
6. **需重新生成（Regeneration Requested）**: 抽检发现质量问题
7. **已批准（Approved）**: 抽检通过
8. **已集成（Integrated）**: 集成到主pipeline

### 批次元数据

每个批次维护一个状态文件（batch_status.json）：

```json
{
  "batch_id": "fm_batch_001",
  "status": "Approved",
  "created_date": "2026-08-17",
  "validated_date": "2026-08-17",
  "approved_date": "2026-08-20",
  "task_count": 18,
  "task_types": {
    "FM": 12,
    "Visualization": 6
  },
  "generation_model": "claude-3-5-sonnet-20241022",
  "reviewer": "reviewer_002",
  "notes": "High quality LLM-generated FM tasks, good domain coverage"
}
```

## 常见问题

### Q1: S0门槛检查失败怎么办？

**A**: LLM生成的任务如果S0失败，通常需要重新生成：

1. **公式错误**: LLM生成的公式逻辑有问题
2. **循环引用**: LLM生成了无意的循环依赖
3. **外部链接**: 检查工作簿不依赖外部数据源
4. **LibreOffice兼容性**: 某些Excel高级功能可能不兼容

解决方法：
- 检查生成日志了解LLM的生成过程
- 调整生成prompt增加公式正确性约束
- 使用--strict-mode重新生成该任务
- 如果多次失败，使用不同的seed重新生成

### Q2: 如何确保LLM生成的任务有唯一解？

**A**: LLM生成器会自动处理唯一解问题：

对于FM任务：
- ✓ LLM生成明确方法的指令，golden是唯一实现
- ✓ 对于多种合理方法，LLM自动生成criteria覆盖等价条件
- ✓ LLM避免生成模糊指令

如果抽检发现唯一解问题：
- 调整generation prompt增加指令明确性要求
- 增加criteria完整性检查
- 重新生成该任务

### Q3: LLM如何生成Visualization criteria？

**A**: LLM自动生成两级criteria：

**Tier 1 (自动验证, ≥70%)**:
- 图表存在性
- 图表类型
- 数据源范围
- 标题文本
- 轴标签文本

**Tier 2 (人工/VLM验证, ~15%抽检)**:
- 颜色选择合理性
- 格式美观性
- 洞察传达清晰度

LLM生成示例：
```json
{
  "criterion": "Revenue trend line chart exists on Dashboard sheet",
  "chart_type": "Line",
  "data_range": "Data!B2:F2",
  "tier": 1
}
```

如果criteria质量不足：
- 调整generation prompt增加criteria详细程度
- 增加Tier 1/Tier 2比例要求
- 重新生成该任务

### Q4: 批次大小建议？

**A**: 
- **FM批次**: 15-25个任务（LLM生成时间~1-2小时）
- **Visualization批次**: 8-15个任务（LLM生成时间~30-60分钟）
- **混合批次**: 可以，但建议保持类型平衡

小批次优势：
- 更快反馈周期
- 更容易调整生成参数
- 降低LLM API成本风险

### Q5: 如何提高LLM生成质量？

**A**: 

1. **提高seed质量**:
   - 使用质量评分≥70的seed
   - 确保seed通过S0门槛
   - 选择领域相关的seed

2. **调整生成参数**:
   - 使用--strict-mode增加质量约束
   - 调整--difficulty-mix控制难度分布
   - 使用--domains限制领域范围

3. **优化generation prompt**:
   - 增加公式正确性要求
   - 增加指令清晰度要求
   - 增加criteria完整性要求

4. **迭代改进**:
   - 从小批次开始（5-10个任务试水）
   - 检查生成质量（前几个任务人工审核）
   - 根据问题调整prompt和参数
   - 逐步扩大批次规模

## 联系方式

- **技术支持**: pipeline-team@project.com
- **审核协调**: review-coord@project.com

---

**版本**: v2.0 (LLM生成版本)  
**最后更新**: 2026-08-17
