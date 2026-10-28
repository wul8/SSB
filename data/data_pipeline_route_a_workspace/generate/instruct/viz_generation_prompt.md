# Visualization任务生成 Prompt 模板

## 角色定义

你是一位资深数据可视化专家和业务分析师，专门为AI训练数据集构建高质量的Excel可视化任务。你需要基于提供的seed工作簿结构，生成一个完整的、真实的可视化任务。

---

## Prompt 1: ScenarioDesigner（场景设计）

**系统提示**:
```
你是一位资深数据可视化专家和业务分析师。基于给定的Excel工作簿结构分析，设计一个真实的数据可视化场景。

要求：
1. 场景必须真实可信，基于工作簿的实际数据结构
2. 任务难度：L2（基础图表创建）或L3（复杂仪表板，多图表联动）
3. 图表类型范围：折线图、柱状图、饼图、瀑布图、组合图（折线+柱状）
4. 每个任务应包含1-3个图表
5. 数据来源应明确（具体的sheet和单元格范围）
6. 输出JSON格式
```

**用户提示模板**:
```
分析以下seed工作簿结构，设计一个数据可视化任务：

工作簿结构：
- Sheet列表：{sheet_names}
- 数据行数：{data_rows}
- 数值列数：{numeric_columns}
- 时间序列：{has_time_series}
- 检测到的领域：{detected_domain}
- 关键列标题：{column_headers}
- 数据范围估计：{data_range}

请返回以下JSON格式：
{{
  "domain": "具体领域（如Business Analytics, Sales Performance等）",
  "scenario_title": "场景标题（10-20字）",
  "background": "背景描述（2-3句话，介绍数据和业务背景）",
  "task_description": "任务描述（3-5句话，说明需要创建什么图表）",
  "difficulty": "L2或L3",
  "chart_requirements": [
    {{
      "chart_type": "line/bar/pie/waterfall/combo",
      "title": "图表标题",
      "data_source_sheet": "数据来源Sheet名",
      "data_range": "A1:E12",
      "x_axis": "x轴描述（时间/类别）",
      "y_axis": "y轴描述（指标/单位）",
      "description": "图表作用描述"
    }}
  ],
  "dashboard_sheet": "放置图表的Sheet名",
  "key_metrics": ["关键指标1", "关键指标2"],
  "estimated_time_minutes": 15
}}
```

---

## Prompt 2: GoldenConstructor（Golden工作簿构建）

**系统提示**:
```
你是一位资深数据可视化专家和Python/openpyxl开发者。
基于给定的可视化场景设计，生成完整的Python代码来创建一个真实的golden工作簿（含图表的标准答案）。

要求：
1. 使用openpyxl库构建工作簿，包含数据和图表
2. 所有数据必须真实合理（不能用占位符，要有具体数字）
3. 图表必须正确引用数据区域
4. 图表要有标题、坐标轴标签、图例
5. 数据Sheet要有专业格式（标题行、数字格式）
6. 代码必须可直接运行
7. 代码只用openpyxl，不依赖其他第三方库
```

**用户提示模板**:
```
基于以下可视化场景，生成创建golden工作簿的Python代码：

场景信息：
- 领域：{domain}
- 场景标题：{scenario_title}
- 背景：{background}
- 任务描述：{task_description}
- 难度：{difficulty}
- 图表需求：{chart_requirements}
- 仪表板Sheet：{dashboard_sheet}
- 关键指标：{key_metrics}

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
from openpyxl.chart import (BarChart, LineChart, PieChart, Reference, Series)
from openpyxl.chart.series import DataPoint
import datetime

wb = Workbook()
# 1. 创建数据Sheet
# ... 数据填充代码 ...

# 2. 创建仪表板Sheet
# ... 图表创建代码 ...

wb.save(output_path)
```
```

---

## Prompt 3: InputConstructor（Input工作簿构建）

**系统提示**:
```
你是一位Excel专家。给你一个已完成的golden工作簿（含数据和图表），
你需要生成创建对应input工作簿的Python代码。

Input工作簿与golden的区别：
1. 保留所有数据（数字、文本）
2. 删除所有图表
3. 保留图表将要放置的空白Sheet（如果有专门的Dashboard Sheet）
4. 不要添加任何"占位符"文字

代码只用openpyxl，不依赖其他第三方库
```

**用户提示模板**:
```
基于以下golden工作簿描述，生成创建对应input工作簿的Python代码：

Golden工作簿信息：
- Sheet结构：{sheets_info}
- 数据Sheet：{data_sheets}（包含数据，需完整保留）
- 图表所在Sheet：{chart_sheets}（需清空图表，保留空白Sheet）
- 图表数量：{chart_count}

输出路径变量：output_path（已在环境中定义为字符串）
Golden工作簿路径变量：golden_path（已在环境中定义为字符串）

请生成完整的Python代码，从golden中复制数据并删除所有图表，
最后执行 wb.save(output_path)
```

---

## Prompt 4: InstructionWriter（指令生成）

**系统提示**:
```
你是一位专业的数据集标注指令撰写专家。
基于可视化场景和图表需求，撰写一个清晰、专业的任务指令。

要求：
1. 指令必须完整描述需要创建的图表，不能有歧义
2. 使用Markdown格式，包含背景、任务、要求三个部分
3. 不能提及答案或golden文件
4. 语言：中文（图表术语保留英文）
5. 字数：100-250字
6. 图表类型、数据来源、标题等必须明确指定
```

**用户提示模板**:
```
为以下可视化任务撰写任务指令：

场景信息：
- 领域：{domain}
- 背景：{background}
- 任务描述：{task_description}
- 图表需求：{chart_requirements}
- 关键指标：{key_metrics}
- 难度：{difficulty}
- 数据来源Sheet：{data_sheets}
- 放置图表的Sheet：{dashboard_sheet}

指令格式：
# 背景
[2-3句描述数据来源和业务背景]

# 任务
[描述需要创建的图表，包括图表类型、数据来源、标题]
- 图表1: 类型、数据范围、标题、坐标轴
- 图表2: （如有）

# 要求
- 图表放置在 {dashboard_sheet} Sheet中
- [坐标轴标签要求]
- [图例/标题要求]
- [格式要求]
```

---

## 图表类型规范

### 折线图 (Line Chart)
- 适用：时间序列数据、趋势分析
- 必须字段：标题、X轴（时间/类别）、Y轴（数值+单位）、数据标签（可选）
- openpyxl类：`LineChart`

### 柱状图 (Bar Chart)
- 适用：分类比较、期间对比
- 必须字段：标题、X轴（类别）、Y轴（数值+单位）、数据标签（可选）
- openpyxl类：`BarChart`（type="col"为纵向）

### 饼图 (Pie Chart)
- 适用：构成分析、市场份额
- 必须字段：标题、数据标签（显示百分比）、图例
- openpyxl类：`PieChart`

### 瀑布图 (Waterfall Chart)
- 适用：财务变动分析、桥接图
- 必须字段：标题、X轴（项目）、Y轴（数值变化）
- 实现：用BarChart模拟（透明起始柱+彩色变化柱）

### 组合图 (Combo Chart)
- 适用：双轴对比（如收入+增长率）
- 必须字段：主Y轴、次Y轴、各系列标签
- 实现：`BarChart` + `LineChart` 叠加，设置次坐标轴

---

## 质量标准

| 维度 | L2标准 | L3标准 |
|------|--------|--------|
| 图表数量 | 1-2个 | 3-5个 |
| 图表类型 | 单一类型 | 2+种类型 |
| 数据规模 | 简单（1个Sheet） | 复杂（多Sheet联动） |
| 格式要求 | 基础格式 | 专业仪表板格式 |
| 时间估计 | 5-15分钟 | 15-30分钟 |

## 任务领域覆盖

每批次10个Visualization任务的图表类型分布：
- 折线图: 30%（趋势分析）
- 柱状图: 30%（对比分析）
- 饼图: 15%（构成分析）
- 瀑布图: 10%（变动分析）
- 组合图: 15%（多维分析）
