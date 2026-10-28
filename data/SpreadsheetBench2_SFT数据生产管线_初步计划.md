# SpreadsheetBench 2 SFT 数据生产管线：初步计划

> 撰写日期：2026-08-13
> 范围：只讨论 **SFT 阶段**的数据生产（任务资产 → 轨迹 → 训练样本），偏好数据与 RL 只标出接口，不展开。
> 上游文档：`SpreadsheetBench2_模型能力提升数据构造方案.md`（数据战略、三层体系、配比）、`SpreadsheetBench2_行业办公Agent评测深度解读.md`（benchmark 解读）。本文不重复战略论证，只落地"怎么造、造成什么样、怎么验"。

---

## 0. 结论先行

三条决定管线形态的判断：

1. **SFT 的训练单位必须是 scaffold 对齐的多轮工具调用轨迹，不是 (指令, 公式) 对，也不是 (指令, 最终脚本) 对。** benchmark 的输入分布是 `view_xlsx` 的固定文本格式 + 10k 截断的 observation + 一次一个工具调用的 REPL 约束。任何不带这层壳的数据，推理时都要靠模型自己迁移。
2. **主要收益来自"目标覆盖率"而不是"公式知识"。** 官方评分里 modification 分子分母必须完全相等才计 1 分（regression 有 0.2% 松弛，modification 零松弛）。漏一个单元格 = 该题 0 分。这把训练目标从"会算"改成"数得全"。
3. **金标准工作簿是瓶颈，但只对 Financial Model 是硬瓶颈。** 有了 `golden.xlsx` + `answer_position`，正确轨迹可以用程序化 oracle 展开 + 强模型改写思考过程；没有 golden 就什么都验不了。但 golden 有两种来源：FM 需要内部一致的完整模型，只能靠专家构造；Debugging 和 Template 的 golden 可以直接取自真实工作簿语料再程序化退化，单位成本差两个量级。管线因此分两条构造路线并行，见 §9。

MVP 目标：**1,200 个可验证任务 → 约 4,000 条通过 verifier 的轨迹（正样本池）→ 装配后约 2,000–2,400 条 SFT 样本**，四类齐全，每条都能在本地重跑官方重算 + 评分脚本得 1.0。

池子比装配后的量大，是因为 §S6 有"每题最多保留 2 条正样本"的上限（最短的 + 一条含恢复片段的），多出来的同题轨迹不入训练集，留作偏好数据的候选。报数时区分这两个数字，不要混用。

---

## 1. 从官方评分脚本反推的硬约束

以下全部读自本地 `visualization_scoring_package 92_b/evaluation/evaluation.py`（文件头注明 DO NOT EDIT，是评测用脚本），不是论文描述，造数据时按这个口径对齐。

### 1.1 判分逻辑

- 只在 `answer_position` 指定的 `sheet!range` 列表内取单元格，**范围外一律不检查**。
- 每个单元格先做输入 vs golden 的对比分类：不同 → `modification`，相同 → `regression`。
- `accuracy = 1.0` 当且仅当 `modification_accuracy == 1.0` 且 `regression_accuracy == 1.0`，其中 `regression_accuracy >= 0.998` 会被归一为 1.0。
- 数值比较：完全相等，或 `|a-b|/max(|a|,|b|) <= 0.01`，一端为 0 时用 `|a-b| <= 0.01` 绝对误差。
- 公式比较：去掉 `$`、转大写、`=+` 归一为 `=` 后做字符串相等。
- `#DIV/0!`、`#N/A` 与 `N/A / NA / N.M. / — / -` 等一组 finance placeholder 互相等价；`None` 与 `""` 等价；`None` 与数值 `0` 等价。
- Debugging 分支按**文件路径**切换比较模式：路径含 `Color` → 比字体颜色（值 + `font.color`），路径含 `Embedded` → 比公式文本。其余比计算值。
- 值模式下若某格是 Excel 错误串，会 fallback 到公式比较。
- sheet 名匹配是 strip + 小写容错（官方数据里真实存在 `'Ratio_Analysis '` 这种带尾空格的表名）。

### 1.2 对造数据的直接推论

| 评分事实 | 造数据要求 |
|---|---|
| modification 零松弛 | 每题必须有机器生成的、完备的 `target_cells` 清单；轨迹里要有"逐区域点数核对"的动作 |
| 范围外不检查 | 内部 verifier 要**比官方更严**，额外定义 `protected_cells`，否则会训练出"范围外随便改"的习惯 |
| 1% 容差 + placeholder 等价 | 不要造依赖容差才能过的样本；不要教模型用 `IFERROR` 套 `"N/A"` 骗分 |
| 公式比较忽略 `$` 和大小写 | 相对/绝对引用错误在**值模式**下才暴露（复制传播后值错），在公式模式下 `$` 被忽略 —— Debugging 的 Relative/Absolute 配方必须让错误体现在值上 |
| 值模式依赖缓存 | 每条轨迹的产出文件必须经 LibreOffice 重算后再判分，管线里重算是强制步骤，不是可选 |
| 颜色/公式模式由路径决定 | 内部数据要显式带 `compare_mode` 字段，不要靠目录名隐式传递 |

### 1.3 Visualization 是另一套口径

读自 `visualization_eval_505b_package/`：

- `dataset.json` 24 题，字段 `id / task_id / instruction / spreadsheet_path / golden_response_path / category / criteria`，**没有 `answer_position`**。
- `criteria` 每题 9–91 条，均值 33.9。全量 813 条的 `rubric_category` 分布：Data Correctness 528、Spec Compliance 278、Preservation 6。
- 打分链路：Windows COM 打开 xlsx → `Chart.Export` 导出 PNG → 多图拼接 → VLM 逐条判 PASS/FAIL（FAIL 理由要求 ≤8 词）→ `score = 通过数/总数`，`score > 0.7` 记 acc=1。
- 结论：Visualization 的 SFT 目标是**先把数据映射做对**（占 65% 的 rubric 权重），再谈格式。论文里所有模型的 Data Correctness 都低于 Format Compliance（Opus 4.6：72.7 vs 82.0），这是最大的空档。

---

## 2. 训练样本的目标形态

### 2.1 必须复刻的 scaffold 细节

读自 `trajectory_example/*/claude opus 4.6/*/config.yaml`：

- system prompt：`You are a helpful Spreadsheet Automation Engineer...` + REPL、**一次只发一个命令**。
- 三个工具：`bash` / `view_xlsx <file> [list|content] [sheet] [start_row] [end_row]` / `submit`。
- instance 模板内含固定的 6 步推荐流程（Inspect / Plan / Implement / Execute / Verify / Submit），并显式禁止 `python3 script.py && submit` 这类合并动作。
- `per_instance_call_limit: 50`、`temperature: 0.0`、reasoning effort high。
- `max_observation_length: 10000`，超长按头尾各半截断并插入 `<elided_chars>`。
- `execution_timeout: 60`、`total_execution_timeout: 1800`。
- blocklist：`vim/vi/nano/less/tail -f/make` 等；`python`/`python3`/`bash` 作为**独立命令**被拦。观测到的可行写法是 heredoc 写脚本到 `/tmp` 再执行，或 `python3 << 'EOF'`。
- 路径约定：输入 `/mnt/spreadsheet_data/spreadsheet/<家族>/<id>_input.xlsx`（只读挂载），输出 `/mnt/spreadsheet_output/<id>_output.xlsx`。

`view_xlsx content` 的 observation 格式必须逐字复刻：

```text
Loading workbook: <path>

Sheet: Financials
Data range: 'Financials'!B17:AH30
Rows: 17 to 30 (total: 14)
Columns: B to AH

Row 17: ['EBITDA', None, '=+$D$3', '=E25-E21', ...]
```

即：**公式以原文字符串出现，空格以 `None` 出现，整行一个 Python list**。模型是在这种表征上做定位的，训练数据换成 markdown 表格或 CSV 会直接改变输入分布。

### 2.2 样本 schema

一条 SFT 样本 = 一条完整轨迹展开成 messages，`loss_mask` 只覆盖 assistant 段。

```json
{
  "sample_id": "fm_000123__oracle_v1",
  "task_id": "fm_000123",
  "category": "Financial_Model",
  "difficulty": "L3",
  "source_lineage_id": "family_042",
  "scaffold": "swe-agent/spreadsheet.yaml@<commit>",
  "messages": [
    {"role": "system", "content": "You are a helpful Spreadsheet Automation Engineer..."},
    {"role": "user", "content": "<task_context>...</task_context>\n\n<instructions>...</instructions>"},
    {"role": "assistant", "thought": "...", "tool_calls": [{"name": "view_xlsx", "arguments": {"file_path": "...", "mode": "list"}}]},
    {"role": "tool", "content": "<observation>\nLoading workbook: ...\n</observation>"}
  ],
  "step_meta": [
    {"i": 0, "phase": "inspect", "effective": true, "cells_written": 0, "touched_protected": false}
  ],
  "verifier": {
    "recalculated": true,
    "modification_accuracy": 1.0,
    "regression_accuracy": 1.0,
    "accuracy": 1.0,
    "protected_violation": 0,
    "invariants_passed": ["balance_sheet_check", "cfs_tie"],
    "excel_errors_in_output": 0
  },
  "provenance": {"generator": "oracle_expand+llm_rewrite", "reviewed_by": "expert_b", "golden_leak_check": "pass"}
}
```

两个字段是这套管线的核心，别省：

- `step_meta[].effective`：论文用 effective step ratio 解释了 Opus 与 MiniMax 的差距。我们不训练"多检查"，训练"少犯错地检查"，所以每步是否有效必须在数据里可见，用于过滤和后续 PRM。
- `verifier`：**只有 accuracy == 1.0 的轨迹进 SFT 正样本池**，其余进 hard negative 池给偏好阶段用。

### 2.3 上下文预算

我对本地 160 条轨迹算了最后一次调用时的完整 context（字符数，按 3.2 字符/token 粗估）：

| 类别 | 平均步数 | view_xlsx 占比 | bash 占比 | 带执行错误的步骤占比 | 末轮 context 均值 |
|---|---:|---:|---:|---:|---:|
| Financial Model | 31.8 | 42.9% | 54.2% | 4.2% | ~85k 字符（≈26k tok） |
| Debugging | 29.9 | 45.6% | 51.4% | 3.2% | ~68k 字符（≈21k tok） |
| Visualization | 27.2 | 16.9% | 79.9% | 14.4% | ~26k 字符（≈8k tok） |
| Template | 17.3 | 28.7% | 65.8% | 5.9% | ~21k 字符（≈6k tok） |

三个可用信号：

- 训练序列长度按 **32k 起、48k 上限** 设计足够覆盖 FM/Debugging，不用一上来堆 128k。
- Visualization 的执行错误率 14.4%，是其他类别的 3–4 倍，且 `view_xlsx` 占比只有 16.9%（几乎不检查数据就开始画图）。这与 rubric 里 Data Correctness 偏低完全对应 → Visualization 的 SFT 要**强制插入"先落地 chart data table 并核对数值"这一步**。
- Template 步数最短但错误率不低，适合作为课程学习第一阶段。

---

## 3. 管线总览

```text
S0 资产入库        原始工作簿 → 许可/PII/可重算过滤 → seed 库
      ↓
S1 结构解析        workbook_map / formula_graph / style_map / invariants
      ↓
S2 任务生成        FM 语义挖空 · Template 族补全 · Debugging 错误注入 · Vis 图表规格
      ↓
S3 任务体检        重算 · 唯一解 · 可解性 · 难度 · 去重 · 污染扫描        ← 淘汰率预期 40–60%
      ↓
S4 轨迹生成        oracle 展开 + 多模型 rollout + 恢复片段注入
      ↓
S5 轨迹判决        LibreOffice 重算 → 官方口径评分 + 内部严格 verifier
      ↓
S6 样本装配        scaffold 化 messages · 有效步裁剪 · 配比抽样 · 分片落盘
```

S3 和 S5 是两道硬闸门，不允许绕过。任何"人工看着还行就先入库"的样本，最终都会以"模型学会了改坏范围外单元格"的形式回来。

S2 有两条并行路线（A 专家构造 / B 真实语料 + 程序化变换），产物 schema 一致，S3 之后不区分来源。路线 B 详见 §9。

---

## 4. 各阶段细节

### S0 资产入库

- 来源优先级：公开财报/交易所披露 → 政府与国际组织开放数据 → 允许再利用的建模教学模板 → 已授权脱敏的内部历史模型 → 专家基于公开数字重建的原创工作簿。
- 每个文件登记 `lineage.json`：来源 URL、公司、期间、模板作者、许可、行业、构建者。**没有 lineage 的文件不入库**，否则后面无法按家族切分 split。
- 入库门槛（全部通过才留）：openpyxl 可读；LibreOffice headless 可打开 + 重算 + 另存；连续两次重算结果一致；无外部链接；无 volatile 函数（`NOW/TODAY/RAND/RANDBETWEEN/INDIRECT` 未冻结的一律拒收）；golden 内无未解释的 `#REF!/#VALUE!/#NUM!`；无 PII / 凭证 / 宏。
- 刻意保留真实工作簿的"脏"特征：尾空格表名、隐藏 sheet、合并单元格、命名区域、spacer 空行、subtotal 与 check row。这些是 benchmark 里真实存在的定位难点，清洗掉等于把题变简单。

### S1 结构解析

每个 seed 产出四份可复用元数据（后续所有任务类型共用）：

- `workbook_map.json`：sheet 角色、used range、表头行列、时间轴（含历史/预测分界列）、单位、输入区/公式区/输出区。
- `formula_graph.json`：单元格级依赖边、跨 sheet 边、公式族（R1C1 归一化后聚类）、上下游影响集、硬编码常量清单、断裂引用清单。
- `style_map.json`：数字格式、字体颜色、填充、边框、合并区域 —— Debugging 的 Color 配方和 Template 的格式保持都从这里取真值。
- `invariants.json`：资产负债平衡、三表勾稽、合计=明细之和、比率口径一致性、单位量级关系。每条带 `cell / expected / tolerance`。

解析器要抽样人工校验，尤其是"历史/预测分界"和"公式族边界"两项 —— 这两项错了，下游所有 `target_cells` 都是错的。

### S2 任务生成

两条构造路线并行，共用同一条骨架：**`golden.xlsx` 先在手，再退化成 `input.xlsx`，`answer_position` 与 `target_cells` 由 diff 机器算出，不手写。** 区别只在 golden 从哪来 —— 路线 A（专家构造）见下文四类细则，路线 B（真实语料 + 程序化变换）见 §9。两条路线的产物 schema 完全一致，S3 之后的管线不区分来源，只在 `provenance.route` 里记 A/B。

- **Financial Model**：在 `formula_graph` 上选**语义完整的子图**挖空（收入→毛利→EBITDA 一条链、营运资本一组假设、债务 schedule、DCF 的 UFCF→TV→EV-to-equity bridge），不做随机 mask。保留格式、表头和推导所需的假设行。每题额外产出一组"同一财务概念的本地实现差异"变体（如 Debt/Equity 用总债务 vs 净债务 vs 平均权益），指令措辞接近但正确答案只能由工作簿上下文决定 —— 这是压制教科书套用的关键。
- **Template**：目标是公式族、传播方向、绝对/相对引用、格式保持。刻意造 hard negative：相邻行标签相似、同名指标出现在多个 sheet、历史期是硬编码而预测期该用公式、季度列与年度列并存、左侧公式可复制但其中一个引用必须保持绝对。
- **Debugging**：按官方十类错误各写一个 mutation operator（Double Counting / Embedded Hardcodes / Errors / Inconsistent Color / Incorrect Average / Cross-Sheet References / Incorrect index-match / Incorrect Sign / Relative vs Absolute / Unit Mismatch）。每个注入点记录：错误类型、根因单元格、注入前后的公式/值/格式、直接与间接影响集、可暴露问题的证据、正确修复、不该动的近邻、修复后应恢复的 invariant。错误数分布 20% 单根因 / 50% 2–3 个 / 30% 4–8 个（含无关噪声）。指令沿用官方的**不告知位置和类型**的通用措辞。
- **Visualization**：`golden` 里已有图表 → 抽取 chart XML 得到系列、范围、轴、标题、颜色、标签，反向生成自然语言指令 + `criteria` 清单，rubric_category 按 Data Correctness / Spec Compliance 标注，比例对齐官方的约 65/35。同时记录该图表类型在 openpyxl / xlsxwriter 下**是否有原生原语**、可用的 OOXML 模板、以及不支持时的降级路径。sunburst、clustered-stacked 这类没有原语的，数据只能教"怎么用 helper"，教不出无中生有。

### S3 任务体检

路线 A（专家构造，单位成本高）淘汰优于修补：过不了就丢，别改指令去迁就一道题。路线 B（机器批量生成，单位成本近零）反过来 —— **欠定的指令自动修补后重试，只有修补两轮仍不收敛才丢**，见 §9.3。

1. `input.xlsx` 与 `golden.xlsx` 都能重算、两次结果一致。
2. `input → golden` 的 diff 与指令描述的范围一致，无遗漏无超出。
3. `answer_position` 覆盖全部 modification cells，且不包含"靠 golden 泄漏才能知道要改"的区域。
4. 唯一解：不联网、不依赖工作簿外知识可判定；无多个同样合理的不同答案。**这是路线 B 的主要淘汰原因，不是次要检查项** —— 自由措辞的指令天生多解。
5. 可解性：生成 input 时没有把推导必需的上下文一起删掉。
6. 难度打标 L1–L4（按 sheet 数、目标单元格数、依赖链长度、错误数）。
7. 去重：按 lineage + sheet 名序列 + 公式 AST 指纹 + 依赖图指纹 + 行标签 MinHash + 指令 embedding 六路联合，命中则**整个 `source_lineage_id` 移除**。
8. 污染扫描：与官方 321 题做同样六路比对，任何高相似度整族剔除。官方数据只用于评测，`input/golden/答案范围/公开轨迹里的修复脚本` 一律不进训练集。
9. 强模型试解：全对的（过易）和全错的（可能有歧义或不可解）都送人工复核，不直接入库。

高价值样本（L3/L4、以及所有 Debugging）走**双专家盲解**：两名未参与构造的专家只看 input + instruction 独立作答，与 golden 和 invariant 三方比对，有分歧就回改指令或 input，直到唯一。官方 321 题花了 1,500+ 小时（约 4.7 小时/题），我们靠自动化把这个成本压到高价值样本上，不要幻想零成本。

### S4 轨迹生成

三条来源混合，全部落成同一 schema：

1. **Oracle 展开（主力，约 60%）**。已知 golden 和 target，用程序确定性生成动作序列：按依赖顺序 inspect 必要 sheet/行段 → 输出变更计划 → 写一个 openpyxl 脚本 → 重算 → 逐区域核对 → submit。动作和 observation 都是真环境执行的真结果，只有 `thought` 由强模型基于"已知答案但要装作在推理"的提示重写。**注意**：重写 thought 时必须屏蔽 golden，否则会产生"凭空知道答案"的思考文本，训出来的模型学到的是自信而不是推理。做法是先让模型在只看 observation 的条件下解释这一步为何合理，再与 oracle 动作做一致性校验，不一致就丢弃该步重生成。
2. **多模型 rollout（约 30%）**。用若干强模型在真 scaffold 里跑，S5 判 1.0 的留作正样本，其余按失败主因入 negative 池。
3. **恢复片段注入（约 10%）**。在正确轨迹中人为插入一次真实失败（sheet 名尾空格导致 KeyError、输出路径写错、LibreOffice 重算超时、写入后未保存、图表对象导不出、XML 改完 Excel 不识别、写入范围越界），后续动作展示：读错误证据 → 缩小原因 → 修复或回滚 → 重新验证。**同一失败动作重复执行的轨迹一律不要**，那是在教退化行为。

两条硬规则：

- **禁止 golden 泄漏**。我在本地 160 条轨迹里发现 **5 条**（Debugging 1 条、Template 4 条）在 input 同目录下直接 `view_xlsx ... golden.xlsx` 偷看答案 —— 因为评测挂载把 golden 放进了只读数据目录。这类轨迹结果分再高也必须剔除，否则模型学到的是"先找 golden"。管线里加一条静态检查：动作文本命中 `golden|answer|target\.xlsx` 即拒。
- **不训练无目的浏览**。裁掉未被后续动作引用的 inspect 步骤，也裁掉产出为空的重复命令。目标是让 SFT 分布的 effective step ratio 显著高于 rollout 原始分布。

### S5 轨迹判决

固定顺序，缺一步该轨迹判废：

1. 产出文件存在、openpyxl 可读、LibreOffice 可打开。
2. `evaluation/open_spreadsheet.py` 等价的重算流程刷新缓存值。
3. 官方口径评分（复用 `evaluation.py` 的比较函数，含 Debugging 的 Color/Embedded 分支）。
4. 内部严格 verifier，比官方多查：`protected_cells`（含 answer_position 之外的区域）是否被动；公式族是否一致（不能一半公式一半硬编码）；输出中 Excel 错误值计数；invariants 是否全过；样式/合并/命名区域是否被破坏；Visualization 还要查 chart object 数量与能否导出。
5. Visualization 额外跑一遍 rubric，记录连续分数而不是 0/1 —— 阈值 0.7 是评测口径，训练时丢掉连续分等于扔掉大部分学习信号。**分两级执行**，不要每条样本都上 Windows：

   **一级（Linux，openpyxl 读 chart XML）。** 本地实测：`load_workbook` 能直接读出图表类型、系列数、`val` / `cat` / `tx` 的引用范围（形如 `'Surprise'!$U$51:$U$71`）和标题对象。对 813 条 criteria 做关键词分类，55% 涉及系列/范围/数值/单元格、20% 涉及坐标轴（含主次轴）、5% 图表类型、4% 标题 —— 合计约 70% 可在 Linux 侧判定，秒级且可并行。这一级同时充当"文件是否结构完好"的闸门。

   **二级（Windows + Excel COM + VLM）。** 只处理通过一级的文件，外加固定比例抽检用于校准。颜色、图例位置、网格线、数据标签这类纯视觉项（约 15%）只能在这一级判。

   两条硬要求：

   - **必须量一级与二级的 task 级 pass/fail 一致率。** 一级是代理，官方分数由 VLM 看像素给出。对着代理优化而代理与真实评分器不一致，等于优化错了目标。一致率不达标（建议门槛 90%）就不允许用一级做批量过滤。
   - **一级通过不等于可交付。** 本地 22 个历史 output 文件里，1 个 openpyxl 读取失败、2 个读不到 chart —— 正是 §S4 恢复片段清单里"XML 改完 Excel 不识别"那类。官方判分用 Excel COM 打开文件，打不开直接 0 分。所以每批样本都要有一定比例过二级，确认 Excel 能真的打开。

   结论：Windows + Excel 是**校准与抽检**设备，不是每条样本的依赖。这把它从"常驻专用节点"降级为"阶段性占用"，§8 第 2 问的成本估算按这个口径重算。

只有官方 accuracy == 1.0 **且**内部 verifier 全绿的轨迹进正样本池。

### S6 样本装配

- 按 §2.1 逐字复刻 system/instance 模板、observation 格式和 10k 截断规则；`scaffold` 字段记住对应 commit，scaffold 一改就要重新装配。
- 每题最多保留 2 条正样本（最短的 + 一条含恢复片段的），避免同题重复主导 loss。
- MVP 配比（1,200 题 → 约 4,000 条轨迹）：

| 类别 | 题数 | 占比 | 侧重 |
|---|---:|---:|---|
| Debugging | 460 | 38% | 十类错误、根因链、完整修复、最小变更 |
| Financial Model | 385 | 32% | 本地公式 grounding、跨表、历史/预测边界 |
| Template | 215 | 18% | 公式族、绝对/相对引用、格式保持 |
| Visualization | 140 | 12% | 数据映射优先、组合图、渲染验证 |

难度：L1 20% / L2 30% / L3 35% / L4 15%。课程学习先 L1+L2 打稳流程，再提 L3/L4；最终混合里必须保留 L1/L2，否则工具成功率会掉。

- split 按 `source_lineage_id` + 模板家族 + 公司 + 错误配方组合切分，同一工作簿换数字不得跨 split。
- 另建 300–500 题内部 shadow 评测集（未见公司/模板/行业/错误配方组合），与官方 benchmark 同时报告。只有两边同时涨，才算能力提升而不是过拟合。

---

## 5. 工程交付物

| 组件 | 说明 |
|---|---|
| `schemas/` | task / trajectory / workbook_map / formula_graph / invariants / rubric 的 JSON Schema |
| `ingest/` | 来源抓取、许可与 PII 登记、可重算门槛 |
| `parse/` | 结构解析器（map、graph、style、invariant 推断） |
| `generate/` | 四类任务生成器 + 十个 Debugging mutation operator |
| `screen/` | 唯一解/可解性/难度/去重/污染扫描 |
| `rollout/` | 真 scaffold 容器、oracle 展开器、恢复片段注入器 |
| `verify/` | 重算服务 + 官方口径评分 + 内部严格 verifier + Vis rubric runner |
| `assemble/` | messages 装配、有效步裁剪、配比抽样、分片 |
| `audit/` | 抽样人工审核界面（看 input/golden/diff/轨迹/判分四联屏） |

依赖：Linux + Docker（官方 `spreadsheet.Dockerfile` 同构，Python 3.11 + openpyxl + LibreOffice UNO）用于生成与判分；一台 Windows + Excel 节点用于 Visualization 导图与 rubric。部署细节沿用 `SpreadsheetBench2_deploy/SpreadsheetBench2_服务器部署说明.md`。

---

## 6. 排期（6 周到 MVP）

| 周 | 交付 |
|---|---|
| W1 | schema 定稿；重算服务 + 官方口径评分复现（用本地 92b/505b 包对齐一次已知结果）；污染扫描；200 个 seed 入库；**语料抽样 2,000 份实测三道损耗通过率，据此定路线 B 题数** |
| W2 | S1 解析器 + invariant 库；解析准确率抽检报告；**路线 A 的 FM 专家产能启动（不等 W4）** |
| W3 | **路线 B 的 Template + Debugging 生成器**（变换器 + 指令反向生成 + 唯一解修补循环）；S3 体检闸门跑通 |
| W4 | Financial Model 语义挖空（路线 A）+ Visualization 规格抽取；双专家盲解流程上线 |
| W5 | S4/S5 打通：oracle 展开 + 多模型 rollout + 判决，产出首批 1,000 条轨迹 |
| W6 | S6 装配、配比抽样、shadow 集切分；交付 MVP 数据包 + 数据卡 |

W1 的对齐动作要认真做：拿本地 `visualization_scoring_package 92_b/results/` 里已有的评分结果反跑一遍我们自己的 verifier，两边数字对不上就说明比较口径抄错了，这个错误越晚发现越贵。

---

## 7. 验收指标

数据侧（管线自身健康度）：

- 任务体检通过率、双专家盲解一致率、去重后独立 lineage 数。
- 路线 B 专属：S0 三道损耗的实际通过率；唯一解循环的一轮收敛率、修补后收敛率、终弃率；"三模型一致但都不等于 golden"的命中率（该指标高说明指令生成 prompt 有系统性偏差，要改 prompt 不是逐题修补）。
- 正样本池的 effective step ratio 中位数（要显著高于 rollout 原始分布）。
- golden 泄漏检出数 = 0；污染扫描命中数 = 0。

模型侧（SFT 后应该动的指标，按重要性排序）：

1. target recall / precision（漏改与误改，先看这个）
2. protected-cell violation rate
3. complete repair rate（Debugging：诊断出的错是否全修）
4. submit-before-verify rate（提交前是否真跑过验证）
5. **Accuracy 与 Modification 的差距是否缩小** —— 这是北极星。Modification 单独涨说明只是更会改局部，差距不缩小就等于没解决问题。
6. Visualization 的 Data Correctness（不看 Overall，Format Compliance 本来就高）

Ablation 至少做：只有公式 SFT → +workbook map → +target selection → +verify/recovery。预期后两项对 task Accuracy 的增益明显大于对 Modification 的增益；如果不是这个形状，说明数据设计没打在失败主因上（论文归因：Insufficient Inspection 42.3% + Wrong Target Selection 32.9% = 75.2%）。

---

## 8. 风险与待定

| 风险 | 应对 |
|---|---|
| FM 的金标准工作簿产能不足（唯一硬瓶颈） | W2 就并行启动来源采集与专家招募；宁可减题数不减 golden 质量；其余三类靠路线 B 摆脱这个瓶颈 |
| oracle 展开的 thought 与动作脱节，训出"假推理" | 强制一致性校验（只看 observation 能否解释该动作），不通过即丢步重生成 |
| scaffold 版本漂移导致数据失效 | 样本带 `scaffold@commit`；scaffold 变更走重装配流程 |
| Visualization 依赖 Windows/Excel，产能与稳定性都差 | 固定 Windows/Excel/VLM 版本与截图分辨率；同一输出多次评测记方差；先保 Data Correctness 类样本 |
| 学到评分器容差（用 IFERROR 套 N/A、靠 1% 容差过关） | 内部 verifier 严于官方；此类样本在 S5 直接判废 |
| 数据泄漏（官方 321 题及其变体） | 六路污染扫描 + 按 lineage 整族剔除 + shadow 集交叉验证 |
| 路线 B 的指令欠定，训出"猜口径"的模型 | 唯一解自动修补循环（§9.3）；不收敛即丢；指令必须钉死每个影响目标值的自由度 |
| 真实语料可重算率远低于预期，路线 B 产能不及测算 | W1 先在 2,000 份抽样上实测 S0 通过率，再定路线 B 的题数承诺，不要按语料总量线性外推 |

四个需要拍板的问题：

1. **专家预算**。双专家盲解是官方数据质量的来源，也是最贵的一环。MVP 里给多少题走盲解（建议：全部路线 A 的 Debugging + 全部 L3/L4，约 400 题；路线 B 只抽检 5%）？
2. **Visualization 是否进 MVP**。它占 benchmark 只有 24 题。原先的理由是"需要一整条常驻 Windows + VLM 链路"，实测后这个理由弱了 —— 约 70% 的 criteria 可在 Linux 侧用 openpyxl 判定（§S5 第 5 步），Windows 降级为校准与抽检设备。现在的决策点变成：**能否借到一台 Windows + Excel 机器做几天校准**，而不是要不要长期占一台。如果能，建议 Visualization 留在 MVP。
3. **是否同期产偏好数据**。S4/S5 天然会积累大量 hard negative（高 Modification、零 Accuracy 的轨迹），丢掉浪费。建议 MVP 阶段只**留存不使用**，schema 预留位置，DPO 放第二版。
4. **路线 B 的配额**。建议 MVP 的 1,200 题里给路线 B 600–700 题（全部承担 Template + 大部分 Debugging），路线 A 专注 FM 与 Visualization。这个比例取决于 W1 抽样测出的可重算率。

---

## 9. 路线 B：真实语料 + 程序化变换（正向构造）

§4 的 S2 描述的是路线 A：专家先造内部一致的 golden，再退化成 input。它的质量上限最高，但单位成本以小时计。路线 B 换一个方向：**把现成的真实工作簿直接当 golden，用参数化程序变换生成 input，指令事后由程序做了什么反向描述。** 两条路线共用 S0/S1/S3/S4/S5/S6，只有 S2 不同。

### 9.1 核心是执行顺序，不是组件

一个自然的写法是"LLM 读工作簿 → 生成 Query → 确定性引擎执行 → 得到 golden"。这个顺序有问题：引擎必须先*理解*那句自然语言才能算出 golden，LLM 与代码之间的语义 gap 没有消除，只是从"LLM 写公式"挪到了"引擎解析意图"。指令里"预测营收以每年 5% 增长"落在哪张表、基期取哪一列、复利还是单利、保留几位小数，每一处都会改变目标单元格的值，而引擎无从判断哪个是对的。

正确顺序是**程序优先**：

```text
真实工作簿（通过 S0 重算门槛）
    → 作为 golden 直接冻结
    → 参数化变换器（挖空 / 注入错误 / 拆解公式族）产出 input
    → answer_position + target_cells 由 golden-input diff 机器算出
    → LLM 读 (golden, input, diff, change_plan) 反向写指令
    → 唯一解校验（§9.3）
```

这样 golden 的正确性是**程序的性质**（它本来就是一份真实、能重算、内部一致的工作簿），不是"LLM 与引擎是否达成一致"的性质。变换器只做删除、替换、注入这类不需要理解语义的操作，天然不会引入错误。

指令生成这一步 LLM 是必要的且不可替代 —— diff 是机器语言（"Financials!H12:L45 被清空"），benchmark 的输入是 429 词的业务描述。但 LLM 在这里只承担**措辞**，不承担正确性：写错了指令，S3 会以"指令与 diff 范围不一致"或"多解"打回，不会污染 golden。

### 9.2 画像层的作用变了

人物画像（投行分析师 / 财务总监 / 审计师，叠加初级/中级/高级工具熟练度）在程序优先的顺序下不再决定任务内容，只决定**指令的措辞风格、术语层级和信息密度**。这其实是更好的用法：

- benchmark 的指令平均 429 词、FM 类 705.9 词，措辞多样性直接影响模型对长指令的鲁棒性。同一个 diff 可以让"审计师"和"分析师"两种口吻各写一版，得到两条指令不同、golden 相同的样本。
- 画像不再需要承担"这个任务是否可解"的责任 —— 任务由变换器决定，一定可解。
- 熟练度画像可以控制指令的**显式程度**：高级画像的指令更简略（"按现有公式族补全预测期"），初级画像的指令更啰嗦（逐列说明）。前者更接近 benchmark 的真实分布，后者适合课程学习早期。

一个约束：无论哪种画像，指令都必须钉死所有影响目标单元格值或公式的自由度。措辞可以自由，口径不能自由。

### 9.3 唯一解自动修补循环

路线 A 的原则是"淘汰优于修补"，因为每题都是专家的小时成本。路线 B 单位成本近零，但**多解率会显著更高** —— 反向描述一段 diff 时，LLM 很容易漏掉某个决定性约束。所以这里改成修补循环：

1. N 个（建议 3 个）独立强模型只看 `input + instruction` 试解，屏蔽 golden。
2. 比对三份产出在 `target_cells` 上的值与公式：
   - 三份都等于 golden → 收敛，入库（同时记录这是"过易"信号，用于难度打标）。
   - 三份互相一致但都不等于 golden → **指令描述的是另一个自解释的口径**，说明我们的指令写错了方向，重写指令。
   - 三份互不一致 → 指令欠定。取分歧单元格反查是哪个自由度没钉死，把该约束追加进指令，重试。
3. 最多修补两轮，仍不收敛即丢弃该题。

第二种情形值得单独记账：它是"LLM 反向描述 diff 时把语义描述偏了"的直接证据，命中率高说明指令生成的 prompt 有系统性问题，要回去改 prompt 而不是逐题修补。

Debugging 类免除这个循环 —— 修复目标就是回到 golden，唯一解天然满足。

### 9.4 两条路线按类别分工

| 类别 | 主路线 | 理由 |
|---|---|---|
| Debugging | **B（近乎免费）** | 任何能干净重算的真实工作簿即 golden，跑 mutation operator 得 input，指令沿用官方"不告知位置和类型"的通用措辞，**完全不需要指令生成也不需要唯一解校验**。这是路线 B 回报最高的分支，而 Debugging 是 benchmark 最弱的一类（最佳 12.00%），在 MVP 配比里占 38% |
| Template | **B** | 目标是公式族、传播方向、绝对/相对引用、格式保持，全部可由拆解真实工作簿的公式族程序化生成；真实语料自带合并单元格、层级表头、尾空格表名这些定位难点，比人工造的更脏也更真 |
| Financial Model | **A** | 需要 15.3 张表、1164.5 个待改单元格、带假设表与三表勾稽的完整模型。通用表格语料里几乎不存在这种结构，B 路线拿不到这种 golden |
| Visualization | A | 需要 golden 里已有符合业务规范的图表以抽取 chart XML 和 criteria；同时受 Windows/Excel 链路产能限制 |

结论：**路线 B 出"能力层"产能，路线 A 保"领域层"保真度。** 路线 B 覆盖的检查、程序化编辑、目标选择，正好对应 42.3% + 32.9% = 75.2% 的失败归因；路线 A 覆盖的财务语义 grounding 是前者造不出来的。两者不是替代关系，取消任何一条都会丢掉一整类能力。

### 9.5 语料来源与实际产能

| 来源 | 规模 | 用途 | 注意 |
|---|---|---|---|
| Sheetpedia | 约 29 万份表格 / 32.4 万工作簿，来自企业邮件归档与在线论坛 | 路线 B 主力语料 | 许可条款要逐条确认再入库；来源含在线论坛，与 SpreadsheetBench V1 同源，必须跑污染扫描 |
| MiMoTable | 428 份表格 / 1,719 条 triplet，7 领域，中英双语 | **取环境与难度分级方案，不取任务** | 答案是文本不是工作簿，任务形态与 SB2 不同；它的 6 个 meta operation 分级（Lookup/Edit 1 分、Calculate/Compare/Visualize 2 分、Reasoning 3 分）可以直接接进我们的 L1–L4 打标 |
| T2R-Bench / EUSES | 19 工业领域 / 公开 Excel 语料 | 补领域覆盖 | 同样先过 S0 |

产能测算必须实测，不能按语料总量线性外推。29 万份里能进路线 B 的比例受三道连续损耗：

1. **S0 重算门槛**：外部链接、volatile 函数、宏、损坏文件、PII 一律拒收。
2. **有公式**：纯数据表（无任何公式）无法支撑 Debugging 的公式类 mutation 和 Template 的公式族拆解，只能做很浅的填充题。真实语料里这个比例不低。
3. **去重后独立 lineage**：同一份模板在企业间广泛流传，29 万份的独立结构数远小于 29 万。

所以 W1 要做的是**在 2,000 份随机抽样上实测三道损耗的通过率**，再据此定路线 B 的题数承诺。这个数字定错了，后面整个排期都要重排。

### 9.6 change_plan：语义动作的正确落点

反向描述 diff 时自然会写出这样的中间产物：

```json
{"step": 1, "action": "创建工作表'预测'"}
{"step": 2, "action": "复制年份列", "range": "利润表!A2:A11 → 预测表!A2:A11"}
{"step": 3, "action": "写入营收公式", "formula": "=B2*1.05"}
```

这是**语义伪动作**，不是 scaffold 动作，不能直接序列化进训练 messages —— SFT 的动作层必须是真实的 `bash` / `view_xlsx` / `submit` 调用，observation 必须是真环境的真实回显（§2.1）。

它的正确位置是 oracle 的 `change_plan`：一个介于 diff 和轨迹之间的中间表示，由 S4 的 oracle 展开器读取，翻译成"按依赖顺序 inspect → heredoc 写 openpyxl 脚本 → 执行 → 重算 → 逐区域核对 → submit"的真实动作序列。它同时是三件事的输入：oracle 展开的脚本骨架、thought 重写时的一致性校验基准、以及审核界面上给人看的变更摘要。

### 9.7 对 §5 / §6 的增量

新增组件：

| 组件 | 说明 |
|---|---|
| `corpus/` | 大规模语料入库、许可登记、S0 批量筛选、公式密度统计、结构指纹去重 |
| `generate/transform/` | 参数化变换器（语义挖空 / 公式族拆解 / 十类错误注入），只做不需要理解语义的操作 |
| `generate/instruct/` | 画像库 + 指令反向生成 + 措辞多样性控制 |
| `screen/unique/` | 唯一解自动修补循环（多模型试解 → 分歧归因 → 约束追加） |

排期调整：W1 增加"语料抽样 2,000 份实测三道损耗通过率"；W3 的 Template + Debugging 生成器直接建在路线 B 上（这是最快见量的组合）；路线 A 的专家产能只投 FM 与 Visualization，从 W2 就并行启动，不等 W4。
