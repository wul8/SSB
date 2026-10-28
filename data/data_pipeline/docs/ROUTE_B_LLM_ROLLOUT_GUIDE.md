# 语料就位后：Route B生成任务 + LLM跑轨迹 操作指南

本指南写给"已经拿到足够真实语料（Sheetpedia/MiMoTable/T2R-Bench等）之后"的你，串起从原始工作簿到LLM rollout轨迹的完整操作步骤。目前`corpus/seed_workbooks`里只有103个通过S0门槛的样本+`files_demo`15个，语料规模不够支撑量产；下面的步骤在新语料到位后原样适用，只是把输入目录换成真实语料。

---

## 0. 前置：语料入库（S0）

新语料不能直接喂给S2生成器，必须先过资产入库门槛。

```bash
cd /mnt/hhq/data/data_pipeline

# 1) 索引新语料目录
python3 scripts/prepare_corpus.py index /path/to/new_corpus --output corpus_index.json

# 2) 抽样验证可读性/重算一致性(先小规模抽查，别一上来验证全量)
python3 scripts/prepare_corpus.py validate corpus_index.json --sample-size 100

# 3) 用collect_seed_workbooks.py正式扫描+导入通过S0门槛的文件
#    (WorkbookValidator检查: openpyxl可读、LibreOffice可打开、两次重算一致、
#     无外部链接、无易变函数NOW/TODAY/RAND等、无PII、无宏、golden无未解释错误值)
python3 scripts/collect_seed_workbooks.py scan /path/to/new_corpus --output seed_scan_report.json
python3 scripts/collect_seed_workbooks.py import seed_scan_report.json --target-count 500
python3 scripts/collect_seed_workbooks.py stats
```

导入后的文件会落到`corpus/seed_workbooks/`，并登记进`ingest/lineage_registry.json`（`quality_score`、来源、hash等），后续S2/S3都从这里取数据源，不直接用原始语料目录。

**校验点**：`collect_seed_workbooks.py stats`里看到的样本数应该显著增长（不再是103个）；`corpus/seed_workbooks/*.xlsx`数量应与之匹配。

---

## 1. S2+S3+S4(LLM rollout)+S5：跑端到端编排脚本

语料量大之后，不要再用一次性小脚本，直接跑已经产品化的编排脚本`scripts/run_route_b_e2e.py`——它是本项目"Route B端到端跑通"任务里做好的项目级脚本，串起S2生成→S3筛选(含真实污染扫描)→S4 LLM rollout+真实执行→S5验证，产出`generated_tasks/route_b_e2e/`和`trajectories/route_b_e2e/`两组持久化产物。

```bash
# --seed-sample-count 控制从seed_workbooks里抽样多少个(默认15，语料多了应该调大)
python3 scripts/run_route_b_e2e.py --seed-sample-count 200 --seed 42
```

会依次做：
1. 收集源工作簿：`files_demo`全量 + `seed_workbooks`抽样
2. 用`DebuggingGenerator`/`TemplateGenerator`(`generate/transform/`)对每个源工作簿生成任务JSON
3. 用`TaskScreener`(`screen/task_screener.py`，含`UniqueSolutionValidator`唯一解校验 + `ContaminationScanner`真实污染扫描,读取`/mnt/hhq/Benchmark/SpreadsheetBench-2-505b/data/spreadsheetbench-v2`)筛掉不合格任务
4. 对筛选通过的任务，用`LLMRolloutGenerator`(`rollout/llm_rollout_generator.py`)让LLM真实多轮尝试解题生成轨迹JSON + 用`TrajectoryExecutor`(`rollout/trajectory_executor.py`)重放轨迹里的bash步骤产出`output.xlsx`
5. 用`TrajectoryVerifier`(`verify/trajectory_verifier.py`)做S5验证，汇总`trajectories/route_b_e2e/verification_report.json`（含`approval_rate`、`rejection_breakdown`）

跑完看：
```bash
cat trajectories/route_b_e2e/e2e_summary.json
```
关注`s5_approval_rate`和`rejection_breakdown`——approval_rate明显偏低时先查`rejection_breakdown`里占比最大的拒绝原因，而不是急着扩大样本量。

这一步产出的都是**LLM真实推理**的rollout轨迹（`provenance.generator == "rollout"`），thought是LLM自己多轮尝试的真实推理过程，不是照着golden倒推的解说词。跑之前必须先完成下面第2节的模型/API Key配置。

---

## 2. 配置与验证LLM Rollout生成器

`rollout/llm_rollout_generator.py`让LLM真正多轮尝试解题（自己看文件、自己下bash命令、自己判断何时submit），产出真实的`thought`和`tool_calls`，而不是照着golden倒推的解说词。

### 2.1 配置模型和API Key

`config.py`里的`LLM_ROLLOUT_CONFIG`已配置为走自建中转endpoint（Anthropic Messages API兼容）：

```python
LLM_ROLLOUT_CONFIG = {
    "model": "deepseek-v4-pro",
    "api_key_env_var": "ROLLOUT_LLM_API_KEY",
    "base_url": "http://115.120.120.64:8082",
    ...
    "temperature": 1,
    "reasoning_effort": "max", # 通过extra_body传给中转
}
```

对应设置环境变量（不要把key写进config.py或提交进版本控制）：
```bash
export ROLLOUT_LLM_API_KEY="sk-..."
```

### 2.2 跑单个任务，先验证框架真的能work

```bash
python3 rollout/llm_rollout_generator.py \
    generated_tasks/route_b_e2e/debugging/<某个task_id>.json \
    /tmp/llm_rollout_smoke_test
```

会调用真实API跑一整个多轮tool-use循环，产出`{sample_id}.json`轨迹文件。先跑1-2个确认：
- LLM能不能在`max_turns`(默认100)内完成任务并调用`submit`
- 产出的轨迹JSON里`messages`序列格式是否正常（assistant的thought是不是真实文本，不是空字符串）
- `provenance.generator == "rollout"`，`provenance.model`是你配置的真实model名
- user message里展示的output路径是独立输出目录格式(`/mnt/spreadsheet_output/{task_id}_output.xlsx`)，不是与输入同目录

### 2.3 用现有检查器验证rollout轨迹的合规性

```python
from pathlib import Path
from rollout.golden_leak_detector import GoldenLeakDetector
from rollout.scaffold_aligner import ScaffoldAligner

trajectory_path = Path("/tmp/llm_rollout_smoke_test/xxx__rollout_v1.json")

# 检查LLM有没有在thought/content里意外提到golden/answer相关字样
leak_report = GoldenLeakDetector().generate_report(GoldenLeakDetector().detect(trajectory_path))
print("golden泄漏检查:", "PASS" if leak_report["passed"] else "FAIL", leak_report["by_severity"])

# 检查system prompt/工具/角色序列/turn数/observation长度是否符合scaffold规范
align_report = ScaffoldAligner().generate_report(ScaffoldAligner().check(trajectory_path))
print("scaffold对齐检查:", "PASS" if align_report["passed"] else "FAIL", align_report["by_severity"])
```

**重点关注`golden_leak_detector`的结果**——LLM是自主决策的，理论上不该看到golden信息（`llm_rollout_generator.py`的user消息只包含`instruction`+`criteria`，不含`golden_path`/`answer_position`），但如果LLM在bash命令里意外读取/打印了golden文件路径变量名之类的内容，这里会报出来，需要人工review。

### 2.4 真正执行轨迹产出output.xlsx，再跑S5验证

```python
from pathlib import Path
from rollout.trajectory_executor import TrajectoryExecutor
from verify.trajectory_verifier import TrajectoryVerifier
import json, shutil

task_json_path = Path("generated_tasks/route_b_e2e/debugging/<task_id>.json")
trajectory_path = Path("/tmp/llm_rollout_smoke_test/<task_id>__rollout_v1.json")
task_dir = Path("trajectories/llm_rollout_test/<task_id>")
task_dir.mkdir(parents=True, exist_ok=True)

task = json.load(open(task_json_path))

executor = TrajectoryExecutor()
result = executor.execute(
    trajectory_path=trajectory_path,
    input_path=Path(task["input_path"]),
    output_path=task_dir / "output.xlsx",
)
print("执行结果:", result.success, f"{result.steps_executed}/{result.steps_total}")

if result.success:
    shutil.copy2(task_json_path, task_dir / "task.json")
    shutil.copy2(task["input_path"], task_dir / "input.xlsx")
    shutil.copy2(task["golden_path"], task_dir / "golden.xlsx")

    verification = TrajectoryVerifier().verify(str(task_dir))
    print("S5验证:", verification.approved, verification.accuracy, verification.rejection_reasons)
```

### 2.5 批量跑（语料量大之后）

`scripts/batch_generate_trajectories.py`已经改造为驱动`LLMRolloutGenerator`，可以直接批量跑：

```bash
python3 scripts/batch_generate_trajectories.py <task_dir> --output <output_dir> --max-tasks 20
```

或者直接用`scripts/run_route_b_e2e.py`跑全流程(见第1节)，两者内部都走同一个`LLMRolloutGenerator`。

**批量跑前务必注意成本和时延**：每个任务是一次真实的多轮LLM API调用（可能几轮到几十轮，每轮几千token），跑几百个任务会产生实际的API费用和明显更长的运行时间。建议先用10-20个任务小批量跑一遍，统计平均turn数、平均耗时、平均accuracy，再决定要不要扩大批量规模。

---

## 小结

轨迹生成只有一条路径：`rollout/llm_rollout_generator.py`的`LLMRolloutGenerator`。

| | LLM rollout |
|---|---|
| 入口 | `rollout/llm_rollout_generator.py` `LLMRolloutGenerator` |
| 已接入`run_route_b_e2e.py`/`batch_generate_trajectories.py` | 是 |
| thought来源 | LLM真实推理输出 |
| 成本 | 真实API调用，按token计费 |
| 需要配置 | `config.py`的`LLM_ROLLOUT_CONFIG.model` + `ROLLOUT_LLM_API_KEY`环境变量 |
| 产出格式 | `trajectory.schema.json`，`provenance.generator="rollout"` |
| 下游消费 | `TrajectoryExecutor`/`ScaffoldAligner`/`GoldenLeakDetector`/`TrajectoryVerifier` |

对应`config.py`里`TRAJECTORY_GENERATION["sources"]`的配比：`rollout: 0.90 / recovery_inject: 0.10`（`recovery_inject`尚未实现）。
