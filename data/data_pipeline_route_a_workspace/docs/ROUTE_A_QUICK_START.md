# 路线A快速开始指南

本指南帮助开发者快速上手路线A的LLM任务生成流程。

## 前置准备

### 1. 环境检查

```bash
# 确认Python环境
python --version  # 需要Python 3.8+

# 确认LibreOffice安装（用于S0检查）
soffice --version

# 确认依赖安装
cd /mnt/hhq/data/data_pipeline
pip install -r requirements.txt

# 设置LLM API密钥
export ANTHROPIC_API_KEY="your-api-key"
# 或在.env文件中配置
```

### 2. 理解任务类型

**FM（财务建模）任务**:
- 三表模型构建
- DCF估值计算
- 敏感性分析
- 情景建模
- 难度：主要L3-L4

**Visualization（可视化）任务**:
- 图表创建（折线图、柱状图、饼图等）
- 仪表板构建
- 数据可视化格式化
- 难度：主要L2-L3

## 快速流程（3步）

### Step 1: 准备Seed工作簿库

```bash
# 扫描候选seed工作簿并评分
python scripts/collect_seed_workbooks.py scan /path/to/candidates

# 导入高质量seed（质量评分≥70）
python scripts/collect_seed_workbooks.py import seed_library/ --min-score 70

# 查看seed库统计
python scripts/collect_seed_workbooks.py stats seed_library/
```

**质量要求**:
- 通过S0门槛（重算一致性）
- 公式密度10-100（不能太少或太多）
- 结构清晰（2-10个sheets）
- 领域相关（财务建模或数据分析）

### Step 2: 生成任务批次

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

**生成过程**:
1. LLM分析seed工作簿结构和特征
2. 生成真实的业务场景
3. 构造golden工作簿（完整答案）
4. 构造input工作簿（移除答案）
5. 生成自然语言指令
6. 自动填写task.json元数据

### Step 3: 验证和打包

```bash
# 自动验证生成的任务
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-report fm_batch_001_validation.json

# 查看验证结果
cat fm_batch_001_validation.json | jq '{total: .total_tasks, success: .success_count, fail: .fail_count, rate: .success_rate}'

# 打包通过验证的任务
python scripts/package_route_a_batch.py \
    --task-dir generated_tasks/fm_batch_001 \
    --output-dir packaged_batches \
    --batch-id fm_batch_001 \
    --validation-report fm_batch_001_validation.json
```

## LLM生成器工作原理

### 核心流程

```
Seed工作簿
    ↓
[LLM Analyzer] 分析结构、领域、复杂度
    ↓
[LLM Scenario Designer] 设计业务场景
    ↓
[LLM Golden Constructor] 构造完整模型
    ↓
[LLM Input Constructor] 反推起点状态
    ↓
[LLM Instruction Writer] 生成清晰指令
    ↓
[LLM Metadata Filler] 填写task.json
    ↓
完整任务三元组 (input.xlsx, golden.xlsx, task.json)
```

### 生成策略

**FM任务生成**:
- 识别seed中的财务结构（三表、估值模型等）
- 生成符合行业标准的业务场景
- 确保公式逻辑正确、数据一致
- 自动评估难度（概念数量、公式复杂度）

**Visualization任务生成**:
- 识别seed中的数据表结构
- 生成合理的可视化需求
- 构造专业的图表和仪表板
- 自动生成Tier 1/2验证标准

## 验证和质量控制

### 自动验证

```bash
# 完整验证（包含S0检查）
# 注意: S0检查使用LibreOffice重算，每个工作簿约5秒
# 预计时间: ~7-10秒/任务（含input和golden）
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/batch_001 \
    --output-report batch_001_validation.json

# 快速验证（跳过S0检查，开发时使用）
python scripts/validate_route_a_batch.py \
    --task-dir generated_tasks/batch_001 \
    --output-report batch_001_validation.json \
    --skip-s0
```

### 人工抽检

```bash
# 随机抽取20%任务进行人工审核
python scripts/sample_for_review.py \
    --batch-dir packaged_batches/fm_batch_001 \
    --sample-rate 0.2 \
    --output review_sample_001.json

# 审核员标注审核结果
# （使用审核界面或手动编辑review_sample_001.json）

# 根据审核结果决定是否批准整个批次
```

## 质量检查清单

### 完整性检查 ✓
- [ ] task.json存在且格式正确
- [ ] input.xlsx存在且可打开
- [ ] golden.xlsx存在且可打开
- [ ] 所有必填字段已填写
- [ ] 文件名与task.json一致

### 可解性检查 ✓
- [ ] Input包含完成任务所需的所有信息
- [ ] Instruction清晰无歧义
- [ ] Criteria可验证
- [ ] Golden代表唯一合理解
- [ ] 任务可在estimated_time内完成

### 质量标准 ✓
- [ ] 业务场景真实合理
- [ ] 公式逻辑正确
- [ ] 格式专业整洁
- [ ] 无明显答案泄漏
- [ ] 难度标注准确

## 常见问题处理

### 问题1: 生成的任务S0检查失败
**原因**: LLM生成的公式有错误或循环引用  
**解决**: 
```bash
# 重新生成该任务，使用更严格的prompt
python scripts/regenerate_single_task.py \
    --task-id fm_001_dcf_valuation \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/fm_batch_001 \
    --strict-mode
```

### 问题2: 生成的instruction不够清晰
**原因**: LLM生成的指令过于模糊  
**解决**: 调整generation prompt，增加instruction质量要求

### 问题3: 难度分布不符合预期
**原因**: LLM难度评估不准确  
**解决**: 
```bash
# 手动调整难度标注
python scripts/adjust_difficulty.py \
    --batch-dir generated_tasks/fm_batch_001 \
    --target-mix "L3:0.4,L4:0.6"
```

### 问题4: 领域覆盖不足
**原因**: Seed库领域单一  
**解决**: 扩充seed库，确保包含多个领域的工作簿

## 批次规模建议

### FM批次
- **推荐规模**: 15-25个任务
- **生成时间**: 1-2小时（取决于LLM速度）
- **验证时间**: 5-10分钟
- **难度分布**: L3≥40%, L4≥40%
- **领域多样**: ≥3个不同domain

### Visualization批次
- **推荐规模**: 8-15个任务
- **生成时间**: 30-60分钟
- **验证时间**: 3-5分钟
- **难度分布**: L2≥30%, L3≥50%
- **图表多样**: ≥5种不同类型

## 性能优化

### 并行生成

```bash
# 使用多进程并行生成
python scripts/generate_route_a_tasks.py \
    --task-type fm \
    --seed-dir seed_library/ \
    --output-dir generated_tasks/fm_batch_001 \
    --count 20 \
    --parallel 4  # 使用4个并行进程
```

### 批量验证

```bash
# 批量验证多个批次
python scripts/batch_validate_multiple.py \
    --batch-dirs generated_tasks/fm_batch_* \
    --output-dir validation_reports/
```

## 获取帮助

### 详细文档
- LLM生成详细指南: `docs/ROUTE_A_LLM_GENERATION_GUIDE.md`
- 提交流程: `docs/ROUTE_A_SUBMISSION_WORKFLOW.md`
- 基础设施总结: `docs/ROUTE_A_INFRASTRUCTURE_SUMMARY.md`

### 技术支持
- 工具问题: pipeline-team@project.com
- 审核问题: review-coord@project.com

### 最佳实践
1. 从小批次开始（5-10个任务试水）
2. 检查生成质量（前几个任务人工审核）
3. 调整prompt参数（根据质量问题优化）
4. 建立seed库（持续收集高质量seed）

---

**版本**: v2.0 (LLM生成版本)  
**最后更新**: 2026-08-17  
**适用对象**: Pipeline开发者和运维人员
