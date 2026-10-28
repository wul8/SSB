# S0-S2-S3 Pipeline Agent 使用文档

## 概述

S0-S2-S3 Pipeline Agent是Route B数据管线前三阶段的自动化工具，将语料入库、任务生成和筛选验证整合为一键执行流程。

## 功能

### 自动化流程

1. **S0 语料入库**
   - 从指定路径复制Excel文件到`corpus/{batch_name}/`
   - 自动去重，跳过已存在文件
   - 支持单文件或整目录处理

2. **S2 任务生成**
   - Debugging任务：注入8种错误类型（公式错误、颜色不一致、单位错误等）
   - Template任务：移除公式，保留数据结构
   - 输出三件套：`{task_id}.json` + `{task_id}_input.xlsx` + `{task_id}_golden.xlsx`
   - 生成`generation_summary.json`统计报告

3. **S3 筛选验证**
   - 唯一解验证：确保任务有确定答案
   - 污染扫描：检测与官方321题重叠（可选跳过）
   - 难度校验：L1-L4标注与实际复杂度一致性
   - 生成`screening_report.json`

4. **S3+ 物理分类**
   - 根据筛选结果物理移动文件到passed/rejected/
   - 保持debugging/template分类结构
   - 生成`sort_screened_report.json`

## 使用方法

### 方式1：直接运行脚本

```bash
cd /mnt/hhq/data/data_pipeline

# 基础用法
python3 scripts/run_s0_s2_s3_pipeline.py /path/to/excel_files batch_name

# 指定随机种子
python3 scripts/run_s0_s2_s3_pipeline.py /data/new_sheets/ sheetpedia_batch2 --seed 42

# 跳过污染检测（当官方数据集路径不可用时）
python3 scripts/run_s0_s2_s3_pipeline.py corpus/test/ test_batch1 --skip-contamination
```

### 方式2：调用Agent

在Claude Code中：

```
使用s0-s2-s3-pipeline处理/data/new_excel/目录，批次名为sheetpedia_batch3
```

或直接说：

```
把/data/new_excel/里的Excel跑一遍S0到S3，批次名sheetpedia_batch3
```

## 参数说明

| 参数 | 必需 | 说明 | 示例 |
|-----|------|------|------|
| source_path | ✓ | 源Excel路径（目录或单文件） | `/data/excel/` 或 `/data/file.xlsx` |
| batch_name | ✓ | 批次名称 | `sheetpedia_batch2` |
| --seed | ✗ | 随机种子（默认42） | `--seed 100` |
| --skip-contamination | ✗ | 跳过污染检测 | `--skip-contamination` |

## 输出结构

```
corpus/{batch_name}/
  ├── source1.xlsx
  ├── source2.xlsx
  └── ...

generated_tasks/route_b_{batch_name}/
  ├── passed/
  │   ├── debugging/
  │   │   ├── {task_id}.json
  │   │   ├── {task_id}_input.xlsx
  │   │   └── {task_id}_golden.xlsx
  │   └── template/
  │       └── ...
  ├── rejected/
  │   ├── debugging/
  │   └── template/
  ├── generation_summary.json      # S2生成统计
  ├── screening_report.json        # S3筛选详情
  └── sort_screened_report.json    # 物理分类统计
```

## 输出报告

### 终端输出示例

```
================================================================================
Route B S0→S2→S3 Pipeline: sheetpedia_batch2
================================================================================
S0完成: 57个新文件 → corpus/sheetpedia_batch2/ (总计57个)
S2完成: Debugging=47, Template=57, 失败=10
S3筛选: 71/104 通过 (68.3%)
S3+完成: passed=71, rejected=33, missing=0
================================================================================
Pipeline完成
================================================================================
S0语料入库: 57个Excel → corpus/sheetpedia_batch2/
S2任务生成: 47个Debugging + 57个Template
S3筛选验证: 71个通过 (68.3%) / 33个拒绝
物理分类完成:
  - passed/{debugging,template}/  : 71个
  - rejected/{debugging,template}/: 33个

输出目录: generated_tasks/route_b_sheetpedia_batch2/
  - passed/     : S4轨迹展开输入
  - rejected/   : 筛选未通过任务
  - screening_report.json : S3筛选详情
  - sort_screened_report.json : 物理分类统计
================================================================================
```

### generation_summary.json

```json
{
  "sources_total": 57,
  "debugging_generated": 47,
  "template_generated": 57,
  "generation_errors": 10,
  "errors": [
    {"source": "file1.xlsx", "error": "注入器找不到目标模式: INDEX-MATCH"},
    ...
  ]
}
```

### screening_report.json

```json
{
  "total": 104,
  "passed": 71,
  "failed": 33,
  "pass_rate": 0.683,
  "contamination_checked": true,
  "results": [
    {
      "task_id": "task_001",
      "passed": true,
      "unique_solution": true,
      "contaminated": false,
      "difficulty_valid": true,
      "issues": []
    },
    ...
  ]
}
```

### sort_screened_report.json

```json
{
  "total": 104,
  "passed": 71,
  "rejected": 33,
  "missing": []
}
```

## 常见问题

### Q: 为什么有些任务生成失败？

A: 正常现象。Debugging任务需要特定公式模式（如SUM、INDEX-MATCH）才能注入错误，源Excel没有这些模式时会失败。这不影响成功生成的任务质量。

**已知模式**：
- mimotable_batch1: 436个源文件中323个是formula_count=0的纯数据表，Debugging生成器大量失败是预期行为
- sheetpedia_batch1: 57个源文件中约10个缺少特定公式模式

### Q: 为什么S3通过率较低？

A: S3会严格筛选，不同批次通过率差异很大：
- **sheetpedia_batch1**: 68.3%通过率（71/104）
- **mimotable_batch1**: 24.4%通过率（130/533）

**mimotable_batch1通过率低的根本原因**：
- **无唯一解占主导**（75.2%的拒绝原因）: 303个任务因formula_count=0被拒
- **语料特点不匹配**: Mimotable大量纯数据表（无公式或公式极少），Template生成器移除公式后没有约束条件
- **Template任务通过率极低**: 23.2%（101/435），拖累整体通过率
- **Debugging任务通过率也不高**: 29.6%（29/98），主要因难度偏差（小型简单表格被评为L1但标注为L2）

**对比sheetpedia_batch1（68.3%通过率）**：
- Sheetpedia是真实财务建模工作簿，公式密集
- Template任务移除公式后仍有大量公式约束，能通过唯一解验证

**结论**：
- ✓ S3筛选机制工作正常，正确识别出无约束任务
- ✗ Mimotable语料不适合当前Route B工作流（纯数据表占比>60%）
- 建议：
  1. 只对Mimotable生成Debugging任务（跳过Template）
  2. 或预筛选：只对formula_count>5的源文件生成Template任务
  3. 或开发新的Template生成策略（基于数据模式而非公式约束）

这是质量保证机制，确保进入S4的任务都符合标准。130个通过的任务仍然是有效的高质量数据。

### Q: 如何只重新跑S3而不重新生成S2？

A: 使用独立的筛选脚本：

```bash
# 只做S3筛选（针对特定批次）
python3 scripts/screen_route_b_mimotable_batch1_tasks.py

# 只做物理分类
python3 scripts/sort_screened_tasks.py generated_tasks/route_b_{batch_name}
```

### Q: 原debugging/template目录还有文件怎么办？

A: 那些是生成失败的残留文件（没进screening_report.json），保留它们用于调试，不影响后续流程。S4只从`passed/`目录读取。

### Q: 污染检测报错怎么办？

A: 污染检测需要官方数据集路径`/mnt/hhq/Benchmark/SpreadsheetBench-2-505b/data/spreadsheetbench-v2`。如果路径不存在或不需要检测，使用`--skip-contamination`跳过：

```bash
python3 scripts/run_s0_s2_s3_pipeline.py /path/to/excel/ batch_name --skip-contamination
```

### Q: 如何调整难度分布？

A: S3难度评分基于4个因素的加权：
- 数据单元格（30%权重）
- 公式单元格（30%权重）
- Sheet数量（20%权重）
- 不变量约束（20%权重）

评分规则在`screen/task_screener.py`中定义，可根据需要调整阈值和权重。

## 下一步

完成S0-S2-S3后，可以继续：

### S4: 轨迹生成

**LLM Rollout模式**（真实推理轨迹，需API调用）：
```bash
# 配置API key
export ROLLOUT_LLM_API_KEY="sk-..."

# 批量生成（需要LLM API，有成本）
python3 scripts/run_llm_rollout_batch_test.py --count 15 --seed 42 --concurrency 4

# 特点：真实thought和tool_calls，多轮API调用
# 参考：docs/ROUTE_B_LLM_ROLLOUT_GUIDE.md
# 参考：docs/LLM_ROLLOUT_BATCH_WORKFLOW.md
```

### S5: 轨迹验证

```bash
# 验证单个verify_bundle
python3 scripts/test_trajectory_verifier.py <path_to_verify_bundle>

# 批量验证并自动分类打包
python3 scripts/sort_verified_trajectories.py trajectories/llm_rollout_runs/<run_dir>

# 输出：approved/和rejected/子目录，verification_report.json
# 参考：docs/S5_TRAJECTORY_VERIFICATION.md
# 参考：docs/S5_VERIFIER_USAGE.md
```

### S6: 数据装配

```bash
# 将approved轨迹转换为HuggingFace格式
# TODO: 实现assemble脚本

# Train/test split（按lineage_family切分，防止泄漏）
# TODO: 实现split脚本

# 参考：docs/PROJECT_STATUS.md（W6任务章节）
```

## 批次管理最佳实践

### 命名规范
- **Route B批次**: `route_b_{source}_{batch_number}`
  - 例如: `route_b_sheetpedia_batch1`, `route_b_mimotable_batch2`
- **LLM Rollout批次**: `{timestamp}_{model}_seed{N}_n{count}`
  - 例如: `20260818_143022_kimi-k3_seed42_n15`

### 批次跟踪
建议在项目根目录维护`batch_tracking.json`记录所有批次状态：
```json
{
  "route_b_sheetpedia_batch1": {
    "status": "s5_verified",
    "created": "2026-08-15",
    "sources": 57,
    "tasks_generated": 104,
    "tasks_passed_s3": 71,
    "tasks_approved_s5": 0
  }
}
```

### 质量审核检查清单
- [ ] S2生成率 ≥ 80%（源文件数 vs 成功生成数）
- [ ] S3通过率 ≥ 60%（总任务数 vs passed数）
- [ ] 污染检测无高危命中（<1%重叠）
- [ ] 难度分布合理（L2~L4覆盖，不过度集中）
- [ ] S5 approval率 ≥ 40%（rollout提交数 vs approved数）

## 相关文档

- `docs/PIPELINE_INTEGRATION_GUIDE.md` - **S0→S6全流程架构图与衔接说明**
- `docs/ROUTE_B_LLM_ROLLOUT_GUIDE.md` - Route B完整管线说明
- `docs/S3_SCREENING_REPORT.md` - S3筛选器验证报告
- `scripts/sort_screened_tasks.py` - 物理分类脚本源码
- `.claude/agents/s0-s2-s3-pipeline.md` - Agent定义文件
