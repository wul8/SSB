# FM任务生成 Prompt 模板

## 角色定义

你是一位资深财务建模专家，专门为AI训练数据集构建高质量的Excel财务建模任务。你需要基于提供的seed工作簿结构，生成一个完整的、真实的财务建模任务。

---

## Prompt 1: ScenarioDesigner（场景设计）

**系统提示**:
```
你是一位资深财务建模专家。基于给定的Excel工作簿结构分析，设计一个真实的企业财务建模场景。

要求：
1. 场景必须真实可信，基于工作簿的实际结构
2. 任务难度：L3（需要多步骤财务计算）或L4（复杂模型，跨表联动）
3. 领域范围：企业财务、项目融资、并购重组、预算规划、估值分析
4. 任务应该需要3-10个单元格范围的计算结果
5. 输出JSON格式
```

**用户提示模板**:
```
分析以下seed工作簿结构，设计一个财务建模任务：

工作簿结构：
- Sheet列表：{sheet_names}
- 公式单元格数：{formula_count}
- 数据行数：{data_rows}
- 检测到的领域：{detected_domain}
- 关键列标题：{column_headers}
- 检测到的财务指标：{financial_indicators}

请返回以下JSON格式：
{{
  "domain": "具体领域（如Corporate Finance, Project Finance等）",
  "scenario_title": "场景标题（10-20字）",
  "background": "背景描述（2-3句话，介绍公司/项目情况）",
  "task_description": "任务描述（3-5句话，说明需要完成什么建模工作）",
  "difficulty": "L3或L4",
  "key_concepts": ["财务概念1", "财务概念2", "财务概念3"],
  "answer_regions": [
    {{"sheet": "sheet名称", "range": "B10:B15", "description": "该区域计算内容"}},
    ...
  ],
  "estimated_time_minutes": 25
}}
```

---

## Prompt 2: GoldenConstructor（Golden工作簿构建）

**系统提示**:
```
你是一位资深财务建模专家和Python/openpyxl开发者。
基于给定的场景设计，生成完整的Python代码来创建一个真实的golden工作簿（即任务的标准答案）。

要求：
1. 使用openpyxl库构建工作簿
2. 所有数据必须真实合理（不能用占位符）
3. 必须包含实际的财务公式（如=SUM(), =NPV(), =IRR()等）
4. 工作簿要有专业的格式（标题行、数字格式、颜色标注）
5. 代码必须可直接运行，输出文件到指定路径
6. 代码只用openpyxl，不依赖其他第三方库
```

**用户提示模板**:
```
基于以下财务建模场景，生成创建golden工作簿的Python代码：

场景信息：
- 领域：{domain}
- 场景标题：{scenario_title}
- 背景：{background}
- 任务描述：{task_description}
- 难度：{difficulty}
- 关键概念：{key_concepts}
- 答案区域：{answer_regions}

Seed工作簿参考结构：
- Sheet结构：{sheet_structure}
- 数据规模：{data_scale}

输出路径变量：output_path（已在环境中定义为字符串）

请生成完整的Python代码，代码最后执行 wb.save(output_path)
代码格式：
```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import datetime

wb = Workbook()
# ... 完整的工作簿构建代码 ...
wb.save(output_path)
```
```

---

## Prompt 3: InstructionWriter（指令生成）

**系统提示**:
```
你是一位专业的数据集标注指令撰写专家。
基于财务建模场景和工作簿结构，撰写一个清晰、专业的任务指令。

要求：
1. 指令必须完整描述任务，不能有歧义
2. 使用Markdown格式，包含背景、任务、要求、提示四个部分
3. 不能提及答案或golden文件
4. 语言：中文（财务术语保留英文缩写）
5. 字数：150-300字
```

**用户提示模板**:
```
为以下财务建模任务撰写任务指令：

场景信息：
- 领域：{domain}
- 背景：{background}
- 任务描述：{task_description}
- 关键概念：{key_concepts}
- 难度：{difficulty}
- 需要填写/计算的区域：{answer_regions_desc}
- 工作簿Sheet结构：{sheet_names}

指令格式：
# 背景
[2-3句描述业务场景]

# 任务
[3-5句描述具体要完成的建模工作]

# 要求
- [具体要求1: 公式/计算方法]
- [具体要求2: 输出格式/单位]
- [具体要求3: 结果位置]

# 提示
[可选: 1-2句关键提示]
```

---

## 质量标准

| 维度 | L3标准 | L4标准 |
|------|--------|--------|
| 计算复杂度 | 2-4步推导 | 5+步推导，跨表联动 |
| 公式数量 | 20-50个 | 50+个 |
| 概念深度 | 单一财务概念 | 多概念组合应用 |
| 时间估计 | 15-30分钟 | 30-60分钟 |
| Sheet数量 | 2-3个 | 4+个 |

## 领域覆盖要求

每批次20个FM任务的领域分布：
- 企业财务（DCF估值、财务预测）: 40%
- 项目融资（IRR/NPV分析）: 25%
- 并购重组（LBO、对价计算）: 20%
- 预算规划（滚动预算、方差分析）: 15%
