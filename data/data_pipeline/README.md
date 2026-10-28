# SpreadsheetBench 2 SFT数据生产管线

## 项目概览

本项目实现SpreadsheetBench 2的SFT（Supervised Fine-Tuning）数据生产管线，目标是生成1,200个可验证任务，产出约4,000条通过验证的轨迹样本。

### MVP配置（2026-08-13确认）

- **专家预算**: 仅L3/L4 + 10%抽检（约200题双专家盲解）
- **Visualization**: 推迟到第二版，MVP只做三类（Financial Model, Debugging, Template）
- **路线B配额**: 600-700题（承担全部Template + 大部分Debugging）
- **偏好数据**: MVP只留存hard negative不使用，DPO放第二版

### 任务配比（MVP 1,200题）

| 类别 | 题数 | 占比 | 难度分布 |
|------|------|------|----------|
| Debugging | 460 | 38% | L1:20% L2:30% L3:35% L4:15% |
| Financial Model | 385 | 32% | L1:20% L2:30% L3:35% L4:15% |
| Template | 215 | 18% | L1:20% L2:30% L3:35% L4:15% |
| **Total** | **1,060** | **88%** | - |

注：Visualization 140题推迟到第二版

### 两条构造路线

- **路线A（专家构造）**: 金标准工作簿由专家构造，适用于Financial Model（需要15.3张表、1164.5个待改单元格的完整模型）
- **路线B（真实语料+程序化变换）**: 真实工作簿直接作为golden，程序化变换生成input，适用于Debugging和Template（单位成本近零）

## 目录结构

```
data_pipeline/
├── schemas/              # JSON Schema定义
│   ├── task.schema.json
│   ├── trajectory.schema.json
│   └── workbook_metadata.schema.json
├── ingest/              # S0: 资产入库
│   ├── sources/         # 数据来源配置
│   ├── validators/      # 重算门槛检查
│   └── lineage/         # 来源登记
├── parse/               # S1: 结构解析
│   ├── workbook_map.py
│   ├── formula_graph.py
│   ├── style_map.py
│   └── invariants.py
├── generate/            # S2: 任务生成
│   ├── transform/       # 路线B: 参数化变换器
│   │   ├── debugging_mutators.py   # 十类错误注入
│   │   ├── template_extractor.py   # 公式族拆解
│   │   └── semantic_mask.py        # 语义挖空
│   └── instruct/        # 路线B: 指令生成
│       ├── personas.py
│       └── instruction_generator.py
├── screen/              # S3: 任务体检
│   ├── unique/          # 唯一解校验
│   │   └── multi_model_validator.py
│   ├── contamination/   # 污染扫描
│   └── difficulty.py    # 难度打标
├── rollout/             # S4: 轨迹生成
│   ├── oracle_expander.py
│   ├── thought_rewriter.py
│   └── recovery_injector.py
├── verify/              # S5: 轨迹判决
│   ├── recalculator.py
│   ├── official_scorer.py
│   └── strict_verifier.py
├── assemble/            # S6: 样本装配
│   ├── scaffold_aligner.py
│   └── batch_sampler.py
├── corpus/              # 大规模语料管理
│   ├── sheetpedia/
│   ├── mimotable/
│   └── manifest.json
├── audit/               # 人工审核界面
└── docs/                # 文档
    ├── schemas/
    ├── pipeline_guide.md
    └── verification_protocol.md
```

## 管线流程

```
S0 资产入库 → S1 结构解析 → S2 任务生成 → S3 任务体检 → S4 轨迹生成 → S5 轨迹判决 → S6 样本装配
    ↓             ↓             ↓             ↓             ↓             ↓             ↓
  过滤PII      元数据复用    路线A/B并行   淘汰率40-60%   三种来源混合   accuracy=1.0   配比抽样
  可重算       四份元数据    共用schema    唯一解/去重    oracle展开    内部严格验证   分片落盘
  无volatile   formula_graph               污染扫描      rollout       golden不泄漏
```

### 关键闸门

1. **S0门槛**: openpyxl可读、LibreOffice可重算、两次结果一致、无外部链接、无volatile函数、无PII
2. **S3体检**: 唯一解、可解性、难度打标、去重、污染扫描、强模型试解
3. **S5判决**: 官方口径accuracy==1.0 且 内部verifier全绿（无protected_violation、invariants全过、无Excel错误值）

## 核心约束

### 1. Scaffold对齐（必须逐字复刻）

- System prompt: "You are a helpful Spreadsheet Automation Engineer..."
- 三个工具: bash / view_xlsx / submit
- `view_xlsx` observation格式: `Row 17: ['EBITDA', None, '=+$D$3', ...]`（公式原文、空格为None、整行一个Python list）
- 最大轮次: 50
- Observation截断: 10000字符（头尾各半 + `<elided_chars>`）

### 2. 评分对齐（官方口径）

- modification零松弛：每题必须有完备的target_cells清单
- 1%数值容差：`|a-b|/max(|a|,|b|) <= 0.01`
- 公式比较：去`$`、转大写、`=+`归一为`=`
- Debugging分支：路径含Color→比字体颜色，含Embedded→比公式文本，其余比值
- accuracy=1.0 当且仅当 modification_accuracy==1.0 且 regression_accuracy==1.0

### 3. Golden不泄漏

- 轨迹中禁止命中 `golden|answer|target\.xlsx` 关键词
- Oracle展开时thought重写必须屏蔽golden（只看observation解释动作）
- 官方321题及其变体一律不进训练集

## 6周排期

| 周 | 交付 |
|----|------|
| W1 | schema定稿；重算服务+官方口径评分复现；污染扫描；200个seed入库；**2000份语料实测三道损耗通过率** |
| W2 | S1解析器+invariant库；解析准确率抽检；路线A的FM专家产能启动 |
| W3 | **路线B的Template+Debugging生成器**（变换器+指令反向生成+唯一解修补循环）；S3体检闸门 |
| W4 | Financial Model语义挖空（路线A）；双专家盲解流程上线 |
| W5 | S4/S5打通：oracle展开+多模型rollout+判决，产出首批1000条轨迹 |
| W6 | S6装配、配比抽样、shadow集切分；交付MVP数据包+数据卡 |

## 验收指标

### 数据侧

- 任务体检通过率、双专家盲解一致率
- 正样本池的effective step ratio中位数（显著高于rollout原始分布）
- Golden泄漏检出数 = 0
- 污染扫描命中数 = 0
- 路线B：S0三道损耗实际通过率、唯一解一轮收敛率

### 模型侧

1. **Target recall / precision**（漏改与误改）
2. **Protected-cell violation rate**
3. **Complete repair rate**（Debugging：诊断出的错是否全修）
4. **Accuracy与Modification的差距是否缩小**（北极星指标）

## 依赖与环境

- Docker（官方spreadsheet.Dockerfile同构，Python 3.11 + openpyxl + LibreOffice UNO）
- 语料来源：Sheetpedia（约29万份）、MiMoTable（428份）、T2R-Bench、EUSES
- 官方评测包：`visualization_scoring_package_92_b/`（本地已有）

## 下一步行动

1. 完成W1核心任务：重算服务实现 + 官方评分口径对齐验证
2. 准备2000份语料抽样测试S0三道损耗通过率
3. 实现S0入库模块和S1结构解析器
