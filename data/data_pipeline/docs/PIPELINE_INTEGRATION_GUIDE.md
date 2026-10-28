# Route B 数据管线集成指南

本文档说明S0→S6各阶段的输入输出、脚本入口和相互衔接关系。

## 管线架构图

```
源Excel文件
    ↓
┌─────────────────────────────────────────┐
│ S0: 语料入库                              │
│ 脚本: run_s0_s2_s3_pipeline.py          │
│ 输出: corpus/{batch_name}/*.xlsx        │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ S2: 任务生成                              │
│ 生成器: DebuggingGenerator + TemplateGenerator │
│ 输出: generated_tasks/route_b_{batch_name}/{debugging,template}/ │
│       - {task_id}.json                  │
│       - {task_id}_input.xlsx            │
│       - {task_id}_golden.xlsx           │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ S3: 筛选验证                              │
│ 筛选器: TaskScreener (唯一解+污染+难度)  │
│ 输出: screening_report.json             │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ S3+: 物理分类                             │
│ 脚本: sort_screened_tasks.py            │
│ 输出: passed/{debugging,template}/      │
│       rejected/{debugging,template}/    │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ S4: 轨迹生成                              │
│ LLM Rollout模式: llm_rollout_generator.py │
│ 输出: trajectories/{run_dir}/{sample_id}.json │
│       + {sample_id}__verify_bundle/     │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ S5: 轨迹验证                              │
│ 验证器: TrajectoryVerifier              │
│ 输出: verification_report.json          │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ S5+: 物理分类                             │
│ 脚本: sort_verified_trajectories.py     │
│ 输出: approved/{sample_id}__verify_bundle/ │
│       rejected/{sample_id}__verify_bundle/ │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ S6: 数据装配（待实现）                     │
│ 输出: HuggingFace格式数据集              │
│       train/test split                  │
└─────────────────────────────────────────┘
```

## 各阶段详细说明

### S0: 语料入库

**输入**: 原始Excel文件目录或单个文件

**脚本**: 
```bash
python3 scripts/run_s0_s2_s3_pipeline.py <source_path> <batch_name>
```

**输出**:
- `corpus/{batch_name}/*.xlsx` - 入库的源文件
- 去重自动跳过已存在文件

**质量要求**: 无特殊要求，S2阶段会自动跳过无法处理的文件

---

### S2: 任务生成

**输入**: `corpus/{batch_name}/*.xlsx`

**核心逻辑**: 
- `generate/transform/debugging_generator.py` - 10类错误注入
- `generate/transform/template_generator.py` - 公式保留+数据清空

**输出**:
```
generated_tasks/route_b_{batch_name}/
├── debugging/
│   ├── {task_id}.json
│   ├── {task_id}_input.xlsx
│   └── {task_id}_golden.xlsx
├── template/
│   └── (同上)
└── generation_summary.json
```

**关键字段** (task.json):
- `task_id`, `task_type` (Debugging/Template)
- `instruction`, `criteria`
- `input_path`, `golden_path`
- `answer_position` (修改位置列表)
- `metadata.injected_errors` (Debugging专用)

---

### S3: 筛选验证

**输入**: `generated_tasks/route_b_{batch_name}/{debugging,template}/*.json`

**核心逻辑**: `screen/task_screener.py`
1. 唯一解验证 (`screen/unique_solution_validator.py`)
2. 污染扫描 (`screen/contamination_scanner.py`) - 6种方法检测
3. 难度校验 - 4因素加权评分

**输出**: `screening_report.json`
```json
{
  "total": 104,
  "passed": 71,
  "pass_rate": 0.683,
  "contamination_checked": true,
  "results": [
    {"task_id": "...", "passed": true, "issues": []},
    ...
  ]
}
```

---

### S3+: 物理分类

**输入**: `screening_report.json` + 原始任务三件套

**脚本**:
```bash
python3 scripts/sort_screened_tasks.py generated_tasks/route_b_{batch_name}
```

**输出**:
```
generated_tasks/route_b_{batch_name}/
├── passed/
│   ├── debugging/  (三件套)
│   └── template/   (三件套)
├── rejected/
│   ├── debugging/
│   └── template/
└── sort_screened_report.json
```

**重要**: S4只从`passed/`目录读取任务，`rejected/`仅用于分析和调试。

---

### S4: 轨迹生成（LLM Rollout，真实推理）

**输入**: `passed/{debugging,template}/*.json`

**脚本**:
```bash
export ROLLOUT_LLM_API_KEY="sk-..."
python3 scripts/run_llm_rollout_batch_test.py --count 15 --seed 42 --concurrency 4
```

**核心逻辑**: `rollout/llm_rollout_generator.py`
- 真实多轮LLM API调用
- 自主决策工具调用序列
- 最多100轮，超时或submit结束

**输出**:
```
trajectories/llm_rollout_runs/{timestamp}_{model}_seed{N}_n{count}/
├── {sample_id}__rollout_v1.json  (轨迹JSON)
├── {sample_id}__verify_bundle/   (rollout_success=True才有)
│   ├── task.json
│   ├── input.xlsx
│   ├── golden.xlsx
│   └── output.xlsx
├── batch_test_summary.json
└── (其他rollout_success=False的轨迹json)
```

**关键指标**:
- `rollout_success`: LLM是否调用了submit
- 只有`rollout_success=True`的任务才有verify_bundle

---

### S5: 轨迹验证

**输入**: `{sample_id}__verify_bundle/`目录（包含task.json + 三个xlsx）

**核心逻辑**: `verify/trajectory_verifier.py`
1. LibreOffice重算检查 (`ingest/validators.py`)
2. 官方评分 (`verify/scorer.py`) - accuracy计算
3. Strict验证:
   - Protected cells: 检测answer_position外的修改
   - Formula family: 公式模式一致性
   - Invariants: 财务约束（资产负债平衡等）
   - Excel errors: #REF!, #VALUE!统计
   - Style preservation: 合并单元格、命名区域

**批准标准** (全部满足才approved):
- `recalculated = True`
- `accuracy = 1.0`
- `protected_violation = 0`
- `formula_family_consistent = True`
- `invariants_failed = []`
- `excel_errors = 0`
- `style_preserved = True`

**输出**: `VerificationResult`对象 + `verification_report.json`

---

### S5+: 物理分类

**输入**: `{run_dir}/*__verify_bundle/`

**脚本**:
```bash
python3 scripts/sort_verified_trajectories.py trajectories/llm_rollout_runs/<run_dir>
```

**输出**:
```
trajectories/llm_rollout_runs/<run_dir>/
├── approved/
│   ├── {sample_id}__verify_bundle/
│   └── {sample_id}__rollout_v1.json
├── rejected/
│   └── (同上)
└── verification_report.json
```

**重要**: S6只从`approved/`目录读取正样本。

---

### S6: 数据装配（待实现）

**输入**: `approved/*__verify_bundle/`

**目标输出**:
- HuggingFace格式数据集
- Train/test split（按lineage_family切分，防止泄漏）
- 负样本池管理（为DPO/PRM准备）

**待实现脚本**:
- `scripts/assemble_dataset.py`
- `scripts/split_train_test.py`

---

## 快速上手示例

### 示例1: 小批量测试（10个Excel → S5）

```bash
# S0-S2-S3: 入库+生成+筛选（约2分钟）
python3 scripts/run_s0_s2_s3_pipeline.py /data/test_excel/ test_batch1 --seed 42

# 查看S3结果
cat generated_tasks/route_b_test_batch1/screening_report.json | jq '.passed, .total'

# S4: LLM Rollout轨迹生成（真实API调用，耗时视任务数和模型而定）
export ROLLOUT_LLM_API_KEY="sk-..."
python3 scripts/batch_generate_trajectories.py \
    generated_tasks/route_b_test_batch1/passed/debugging/ \
    trajectories/test_batch1_rollout

# 查看最终结果（golden泄漏检测+scaffold对齐检查已自动执行）
cat trajectories/test_batch1_rollout/generation_report.json | jq '.success_count, .fail_count'
```

### 示例2: 大批量生产（200个Excel → S5 LLM Rollout）

```bash
# S0-S2-S3（约10分钟）
python3 scripts/run_s0_s2_s3_pipeline.py /data/corpus_batch5/ batch5 --seed 100

# 查看通过S3的任务数
ls -1 generated_tasks/route_b_batch5/passed/debugging/*.json | wc -l

# S4: LLM Rollout（每15个任务约1-1.5小时，成本约$0.18/任务）
export ROLLOUT_LLM_API_KEY="sk-..."
nohup python3 scripts/run_llm_rollout_batch_test.py --count 50 --seed 100 --concurrency 4 \
    > /tmp/rollout_batch5.log 2>&1 & disown

# 监控进度
watch -n 60 'grep -c "\[OK\]\|\[FAIL\]" /tmp/rollout_batch5.log'

# S5: 验证+分类（约5分钟）
python3 scripts/sort_verified_trajectories.py \
    trajectories/llm_rollout_runs/20260903_*_seed100_n50

# 查看最终通过率
cat trajectories/llm_rollout_runs/20260903_*_seed100_n50/verification_report.json | \
    jq '.approved, .total, .approval_rate'
```

---

## 关键文件索引

| 阶段 | 核心脚本 | 核心模块 | 输出格式 |
|------|---------|---------|---------|
| S0 | `run_s0_s2_s3_pipeline.py` | - | `corpus/{batch}/*.xlsx` |
| S2 | `run_s0_s2_s3_pipeline.py` | `debugging_generator.py`, `template_generator.py` | `generated_tasks/route_b_{batch}/{debugging,template}/` |
| S3 | `run_s0_s2_s3_pipeline.py` | `task_screener.py` | `screening_report.json` |
| S3+ | `sort_screened_tasks.py` | - | `passed/`, `rejected/` |
| S4 | `batch_generate_trajectories.py` / `run_llm_rollout_batch_test.py` | `llm_rollout_generator.py` | `{sample_id}__rollout_v1.json`, `verify_bundle/` |
| S5 | `sort_verified_trajectories.py` | `trajectory_verifier.py` | `verification_report.json` |
| S5+ | `sort_verified_trajectories.py` | - | `approved/`, `rejected/` |
| S6 | (待实现) | (待实现) | HuggingFace dataset |

---

## 相关文档

- **快速开始**: `docs/README_S0_S2_S3.md`
- **详细使用**: `docs/S0_S2_S3_PIPELINE_USAGE.md`
- **Route B概览**: `docs/ROUTE_B_LLM_ROLLOUT_GUIDE.md`
- **LLM Rollout工作流**: `docs/LLM_ROLLOUT_BATCH_WORKFLOW.md`
- **S3筛选报告**: `docs/S3_SCREENING_REPORT.md`
- **S5验证指南**: `docs/S5_TRAJECTORY_VERIFICATION.md`
- **项目状态**: `docs/PROJECT_STATUS.md`

---

**最后更新**: 2026-09-03  
**文档版本**: 1.0
