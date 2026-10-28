#!/usr/bin/env python3
"""
Route A LLM Task Generator

Generates FM and Visualization tasks using Claude API based on seed workbooks.
Implements the complete generation pipeline: seed analysis → workbook generation →
instruction writing → metadata assembly.

Usage:
    # Generate 10 FM tasks
    python generate_route_a_tasks.py --task-type fm --seed-dir seed_library/ \
        --output-dir generated_tasks/fm_batch_001 --count 10

    # Generate 5 Visualization tasks with difficulty mix
    python generate_route_a_tasks.py --task-type visualization \
        --seed-dir seed_library/ --output-dir generated_tasks/viz_batch_001 \
        --count 5 --difficulty-mix "L2:0.3,L3:0.7"
"""

import os
import sys
import json
import argparse
import logging
import datetime
import random
import time
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from openpyxl import load_workbook
import anthropic

# Import config
from config import TASK_DISTRIBUTION, SCAFFOLD_CONFIG


@dataclass
class GenerationResult:
    """Result of a single task generation"""
    success: bool
    task_id: str
    task_dir: Optional[Path] = None
    error: Optional[str] = None
    retry_count: int = 0
    generation_time_seconds: float = 0.0


class SeedAnalyzer:
    """Analyzes seed workbooks to extract structure information"""

    def analyze(self, seed_path: Path) -> Dict[str, Any]:
        """Extract metadata from seed workbook"""
        try:
            wb = load_workbook(seed_path, data_only=False)

            analysis = {
                "seed_path": str(seed_path),
                "sheet_names": wb.sheetnames,
                "sheet_count": len(wb.sheetnames),
                "formula_count": 0,
                "data_rows": 0,
                "numeric_columns": 0,
                "column_headers": [],
                "has_time_series": False,
                "detected_domain": "General",
                "data_range": "",
            }

            # Analyze each sheet
            for sheet_name in wb.sheetnames[:3]:  # Limit to first 3 sheets
                ws = wb[sheet_name]
                max_row = ws.max_row
                max_col = ws.max_column

                analysis["data_rows"] += max_row

                # Count formulas
                for row in ws.iter_rows(min_row=1, max_row=min(max_row, 100)):
                    for cell in row:
                        if cell.value and isinstance(cell.value, str) and cell.value.startswith('='):
                            analysis["formula_count"] += 1

                # Extract column headers (first row)
                if max_row > 0:
                    headers = []
                    for col in range(1, min(max_col + 1, 20)):
                        cell_value = ws.cell(1, col).value
                        if cell_value:
                            headers.append(str(cell_value))
                    analysis["column_headers"].extend(headers[:10])

                # Count numeric columns
                if max_row > 1:
                    for col in range(1, min(max_col + 1, 20)):
                        cell_value = ws.cell(2, col).value
                        if isinstance(cell_value, (int, float)):
                            analysis["numeric_columns"] += 1

            # Detect domain based on keywords
            all_text = " ".join(analysis["column_headers"]).lower()
            if any(kw in all_text for kw in ["revenue", "cost", "profit", "dcf", "npv", "irr"]):
                analysis["detected_domain"] = "Corporate Finance"
            elif any(kw in all_text for kw in ["sales", "market", "customer"]):
                analysis["detected_domain"] = "Business Analytics"

            # Check time series
            if any(kw in all_text for kw in ["date", "month", "year", "quarter"]):
                analysis["has_time_series"] = True

            wb.close()
            return analysis

        except Exception as e:
            logging.error(f"Failed to analyze seed {seed_path}: {e}")
            return None


class RouteAGenerator:
    """Main generator for Route A tasks using Claude API"""

    def __init__(self, api_key: str, task_type: str, output_dir: Path,
                 model: str = "claude-3-5-sonnet-20241022",
                 base_url: Optional[str] = None):
        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url
        )
        self.task_type = task_type.lower()
        self.output_dir = output_dir
        self.model = model
        self.analyzer = SeedAnalyzer()

        # Load prompt templates
        self.prompts = self._load_prompts()

    def _load_prompts(self) -> Dict[str, str]:
        """Load generation prompt templates"""
        prompt_dir = project_root / "generate" / "instruct"

        if self.task_type == "fm":
            prompt_file = prompt_dir / "fm_generation_prompt.md"
        elif self.task_type in ["visualization", "viz"]:
            prompt_file = prompt_dir / "viz_generation_prompt.md"
        else:
            raise ValueError(f"Unknown task type: {self.task_type}")

        with open(prompt_file, 'r', encoding='utf-8') as f:
            content = f.read()

        return {"full_prompt": content}

    def generate_task(self, seed_path: Path, task_index: int,
                     difficulty: Optional[str] = None) -> GenerationResult:
        """Generate a single task from a seed workbook"""
        start_time = time.time()
        task_id = self._generate_task_id(task_index)
        task_dir = self.output_dir / task_id

        logging.info(f"Generating task {task_id} from seed {seed_path.name}")

        try:
            # Step 1: Analyze seed
            seed_analysis = self.analyzer.analyze(seed_path)
            if not seed_analysis:
                return GenerationResult(
                    success=False,
                    task_id=task_id,
                    error="Failed to analyze seed workbook"
                )

            # Step 2: Design scenario
            scenario = self._design_scenario(seed_analysis, difficulty)
            if not scenario:
                return GenerationResult(
                    success=False,
                    task_id=task_id,
                    error="Failed to design scenario"
                )

            # Step 3: Generate golden workbook
            golden_path = task_dir / f"{task_id}_golden.xlsx"
            task_dir.mkdir(parents=True, exist_ok=True)

            if not self._generate_golden_workbook(scenario, seed_analysis, golden_path):
                return GenerationResult(
                    success=False,
                    task_id=task_id,
                    task_dir=task_dir,
                    error="Failed to generate golden workbook"
                )

            # Step 4: Generate input workbook
            input_path = task_dir / f"{task_id}_input.xlsx"
            if not self._generate_input_workbook(golden_path, scenario, input_path):
                return GenerationResult(
                    success=False,
                    task_id=task_id,
                    task_dir=task_dir,
                    error="Failed to generate input workbook"
                )

            # Step 5: Generate instruction
            instruction = self._generate_instruction(scenario, seed_analysis)
            if not instruction:
                return GenerationResult(
                    success=False,
                    task_id=task_id,
                    task_dir=task_dir,
                    error="Failed to generate instruction"
                )

            # Step 6: Generate criteria
            criteria_data = self._generate_criteria(scenario)

            # Step 7: Assemble task.json
            task_json = self._assemble_task_json(
                task_id, scenario, instruction, criteria_data, seed_path
            )

            task_json_path = task_dir / "task.json"
            with open(task_json_path, 'w', encoding='utf-8') as f:
                json.dump(task_json, f, ensure_ascii=False, indent=2)

            generation_time = time.time() - start_time
            logging.info(f"✓ Successfully generated {task_id} in {generation_time:.1f}s")

            return GenerationResult(
                success=True,
                task_id=task_id,
                task_dir=task_dir,
                generation_time_seconds=generation_time
            )

        except Exception as e:
            logging.error(f"✗ Failed to generate {task_id}: {e}")
            return GenerationResult(
                success=False,
                task_id=task_id,
                task_dir=task_dir if task_dir.exists() else None,
                error=str(e)
            )

    def _generate_task_id(self, index: int) -> str:
        """Generate unique task ID"""
        prefix = "fm" if self.task_type == "fm" else "viz"
        timestamp = datetime.datetime.now().strftime("%Y%m%d")
        return f"{prefix}_{timestamp}_{index:03d}"

    def _design_scenario(self, seed_analysis: Dict, difficulty: Optional[str]) -> Optional[Dict]:
        """Step 1: Design scenario using Claude API"""
        logging.info("  [1/5] Designing scenario...")

        # Build user prompt
        if self.task_type == "fm":
            user_prompt = f"""分析以下seed工作簿结构，设计一个财务建模任务：

工作簿结构：
- Sheet列表：{seed_analysis['sheet_names']}
- 公式单元格数：{seed_analysis['formula_count']}
- 数据行数：{seed_analysis['data_rows']}
- 检测到的领域：{seed_analysis['detected_domain']}
- 关键列标题：{seed_analysis['column_headers'][:10]}

请返回以下JSON格式（只返回JSON，不要其他文字）：
{{
  "domain": "具体领域（如Corporate Finance, Project Finance等）",
  "scenario_title": "场景标题（10-20字）",
  "background": "背景描述（2-3句话，介绍公司/项目情况）",
  "task_description": "任务描述（3-5句话，说明需要完成什么建模工作）",
  "difficulty": "{difficulty or 'L3或L4'}",
  "key_concepts": ["财务概念1", "财务概念2", "财务概念3"],
  "answer_regions": [
    {{"sheet": "sheet名称", "range": "B10:B15", "description": "该区域计算内容"}}
  ],
  "estimated_time_minutes": 25
}}"""
        else:  # visualization
            user_prompt = f"""分析以下seed工作簿结构，设计一个数据可视化任务：

工作簿结构：
- Sheet列表：{seed_analysis['sheet_names']}
- 数据行数：{seed_analysis['data_rows']}
- 数值列数：{seed_analysis['numeric_columns']}
- 时间序列：{seed_analysis['has_time_series']}
- 检测到的领域：{seed_analysis['detected_domain']}
- 关键列标题：{seed_analysis['column_headers'][:10]}

请返回以下JSON格式（只返回JSON，不要其他文字）：
{{
  "domain": "具体领域（如Business Analytics, Sales Performance等）",
  "scenario_title": "场景标题（10-20字）",
  "background": "背景描述（2-3句话，介绍数据和业务背景）",
  "task_description": "任务描述（3-5句话，说明需要创建什么图表）",
  "difficulty": "{difficulty or 'L2或L3'}",
  "chart_requirements": [
    {{
      "chart_type": "line/bar/pie/waterfall/combo",
      "title": "图表标题",
      "data_source_sheet": "数据来源Sheet名",
      "data_range": "A1:E12",
      "x_axis": "x轴描述",
      "y_axis": "y轴描述",
      "description": "图表作用描述"
    }}
  ],
  "dashboard_sheet": "Dashboard",
  "key_metrics": ["关键指标1", "关键指标2"],
  "estimated_time_minutes": 15
}}"""

        system_prompt = """你是一位资深财务建模和数据可视化专家。基于给定的Excel工作簿结构分析，设计一个真实的任务场景。
要求：
1. 场景必须真实可信
2. 任务难度合理
3. 输出严格的JSON格式，不要添加任何额外说明"""

        response = self._call_claude_api(system_prompt, user_prompt)
        if not response:
            return None

        # Parse JSON response
        try:
            # Extract JSON from response (might have markdown code blocks)
            content = response.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            scenario = json.loads(content)
            logging.info(f"    ✓ Designed scenario: {scenario.get('scenario_title', 'N/A')}")
            return scenario
        except json.JSONDecodeError as e:
            logging.error(f"    ✗ Failed to parse scenario JSON: {e}")
            logging.debug(f"    Response: {response[:500]}")
            return None

    def _generate_golden_workbook(self, scenario: Dict, seed_analysis: Dict,
                                   output_path: Path) -> bool:
        """Step 2: Generate golden workbook using Claude API + Python execution"""
        logging.info("  [2/5] Generating golden workbook...")

        # Build user prompt based on task type
        if self.task_type == "fm":
            user_prompt = f"""基于以下财务建模场景，生成创建golden工作簿的Python代码：

场景信息：
- 领域：{scenario['domain']}
- 场景标题：{scenario['scenario_title']}
- 背景：{scenario['background']}
- 任务描述：{scenario['task_description']}
- 难度：{scenario['difficulty']}
- 关键概念：{scenario['key_concepts']}
- 答案区域：{scenario['answer_regions']}

Seed工作簿参考结构：
- Sheet结构：{seed_analysis['sheet_names']}
- 数据规模：{seed_analysis['data_rows']} 行

输出路径变量：output_path（已在环境中定义为字符串）

请生成完整的Python代码，代码最后执行 wb.save(output_path)
只返回代码，用```python包围，不要其他说明"""
        else:  # visualization
            user_prompt = f"""基于以下可视化场景，生成创建golden工作簿的Python代码（含数据和图表）：

场景信息：
- 领域：{scenario['domain']}
- 场景标题：{scenario['scenario_title']}
- 背景：{scenario['background']}
- 任务描述：{scenario['task_description']}
- 难度：{scenario['difficulty']}
- 图表需求：{scenario['chart_requirements']}
- 仪表板Sheet：{scenario['dashboard_sheet']}
- 关键指标：{scenario['key_metrics']}

Seed工作簿参考结构：
- Sheet结构：{seed_analysis['sheet_names']}
- 数据规模：{seed_analysis['data_rows']} 行

输出路径变量：output_path（已在环境中定义为字符串）

请生成完整的Python代码，代码最后执行 wb.save(output_path)
只返回代码，用```python包围，不要其他说明"""

        system_prompt = """你是一位资深Excel开发专家和Python/openpyxl开发者。
生成完整可运行的Python代码来创建Excel工作簿。
要求：
1. 使用openpyxl库
2. 所有数据必须真实合理
3. 必须包含实际的公式
4. 代码可直接运行"""

        response = self._call_claude_api(system_prompt, user_prompt)
        if not response:
            return False

        # Extract Python code
        code = self._extract_python_code(response)
        if not code:
            logging.error("    ✗ Failed to extract Python code from response")
            return False

        # Execute Python code to generate workbook
        return self._execute_workbook_generation_code(code, output_path)

    def _generate_input_workbook(self, golden_path: Path, scenario: Dict,
                                  output_path: Path) -> bool:
        """Step 3: Generate input workbook"""
        logging.info("  [3/5] Generating input workbook...")

        if self.task_type == "fm":
            # For FM tasks: copy golden but clear ALL formulas using fixed code
            try:
                import openpyxl
                from openpyxl.cell.cell import MergedCell

                # Load golden workbook
                wb = openpyxl.load_workbook(golden_path, data_only=False)

                formula_count = 0
                cleared_count = 0

                # Clear all formulas in all sheets
                for sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                    for row in ws.iter_rows():
                        for cell in row:
                            # Skip merged cells (they don't have direct values)
                            if isinstance(cell, MergedCell):
                                continue

                            # Clear formula cells
                            if cell.data_type == 'f':
                                formula_count += 1
                                cell.value = None
                                cleared_count += 1

                # Save as input workbook
                wb.save(output_path)
                logging.info(f"    ✓ Generated input workbook: cleared {cleared_count}/{formula_count} formulas")
                return True

            except Exception as e:
                logging.error(f"    ✗ Failed to generate input workbook")
                logging.error(f"    Error: {e}")
                return False
        else:
            # For Visualization tasks: remove charts from golden
            user_prompt = f"""基于以下golden工作簿描述，生成创建对应input工作簿的Python代码：

Golden工作簿路径：{golden_path}
图表所在Sheet：{scenario.get('dashboard_sheet', 'Dashboard')}
图表数量：{len(scenario.get('chart_requirements', []))}

任务：从golden中复制所有数据，删除所有图表，保留空白的图表Sheet

输出路径变量：output_path（已在环境中定义）
Golden路径变量：golden_path（已在环境中定义）

请生成完整的Python代码，只返回代码，用```python包围"""

            system_prompt = """你是Excel专家。生成代码从golden工作簿创建input工作簿：
1. 复制所有数据Sheet
2. 删除所有图表
3. 保留图表Sheet但为空白

重要的openpyxl处理规则：
- 在清除任何单元格之前，必须先取消所有合并单元格
- 取消合并操作：先用list()复制merged_cells集合，再遍历取消
- 取消合并后，只能修改原合并区域的左上角单元格
- 删除图表使用：ws._charts.clear()

正确的合并单元格处理模式：
```python
# 取消所有合并单元格
merged_ranges = list(ws.merged_cells.ranges)
for merged_range in merged_ranges:
    ws.unmerge_cells(str(merged_range))
```

代码必须用openpyxl库"""

            response = self._call_claude_api(system_prompt, user_prompt)
            if not response:
                return False

            code = self._extract_python_code(response)
            if not code:
                return False

            # Add path definitions
            code_with_paths = f"""
golden_path = r"{golden_path}"
output_path = r"{output_path}"

{code}
"""
            return self._execute_workbook_generation_code(code_with_paths, output_path)

    def _generate_instruction(self, scenario: Dict, seed_analysis: Dict) -> Optional[str]:
        """Step 4: Generate task instruction"""
        logging.info("  [4/5] Generating instruction...")

        if self.task_type == "fm":
            user_prompt = f"""为以下财务建模任务撰写任务指令：

场景信息：
- 领域：{scenario['domain']}
- 背景：{scenario['background']}
- 任务描述：{scenario['task_description']}
- 关键概念：{scenario['key_concepts']}
- 难度：{scenario['difficulty']}
- 需要填写的区域：{scenario['answer_regions']}
- 工作簿Sheet：{seed_analysis['sheet_names'][:3]}

指令格式（Markdown）：
# 背景
[2-3句描述业务场景]

# 任务
[3-5句描述具体要完成的建模工作]

# 要求
- [具体要求1]
- [具体要求2]
- [具体要求3]

# 提示
[1-2句关键提示]

只返回Markdown格式的指令，不要其他说明"""
        else:  # visualization
            user_prompt = f"""为以下可视化任务撰写任务指令：

场景信息：
- 领域：{scenario['domain']}
- 背景：{scenario['background']}
- 任务描述：{scenario['task_description']}
- 图表需求：{scenario['chart_requirements']}
- 关键指标：{scenario['key_metrics']}
- 难度：{scenario['difficulty']}
- 放置图表的Sheet：{scenario.get('dashboard_sheet', 'Dashboard')}

指令格式（Markdown）：
# 背景
[2-3句描述数据来源和业务背景]

# 任务
[描述需要创建的图表]
- 图表1: 类型、数据范围、标题、坐标轴
- 图表2: （如有）

# 要求
- 图表放置在 {scenario.get('dashboard_sheet', 'Dashboard')} Sheet中
- [坐标轴标签要求]
- [图例/标题要求]

只返回Markdown格式的指令，不要其他说明"""

        system_prompt = """你是专业的数据集标注指令撰写专家。
撰写清晰、专业的任务指令。
要求：
1. 使用Markdown格式
2. 不能提及答案或golden文件
3. 中文撰写，150-300字"""

        response = self._call_claude_api(system_prompt, user_prompt)
        if response:
            logging.info("    ✓ Generated instruction")
        return response

    def _generate_criteria(self, scenario: Dict) -> Dict:
        """Step 5: Generate verification criteria"""
        logging.info("  [5/5] Generating criteria...")

        if self.task_type == "fm":
            # Extract answer positions from scenario
            criteria = []
            for region in scenario.get('answer_regions', []):
                criteria.append(f"{region['sheet']}!{region['range']}: {region['description']}")

            return {
                "answer_position": [f"{r['sheet']}!{r['range']}" for r in scenario.get('answer_regions', [])],
                "criteria": criteria if criteria else ["计算结果准确", "公式逻辑正确", "格式符合要求"]
            }
        else:  # visualization
            # Generate visualization_criteria
            viz_criteria = []
            for chart_req in scenario.get('chart_requirements', []):
                viz_criteria.extend([
                    {"criterion": f"图表类型正确 ({chart_req['chart_type']})", "tier": 1},
                    {"criterion": f"数据源正确 ({chart_req['data_source_sheet']})", "tier": 1},
                    {"criterion": f"图表标题: {chart_req['title']}", "tier": 1},
                    {"criterion": f"坐标轴标签正确", "tier": 2},
                ])

            return {
                "answer_position": [scenario.get('dashboard_sheet', 'Dashboard')],
                "criteria": ["图表创建完成", "数据引用正确", "格式符合要求"],
                "visualization_criteria": viz_criteria[:8]  # Limit to 8 criteria
            }

    def _assemble_task_json(self, task_id: str, scenario: Dict, instruction: str,
                           criteria_data: Dict, seed_path: Path) -> Dict:
        """Step 6: Assemble complete task.json"""

        task_type_upper = "FM" if self.task_type == "fm" else "Visualization"

        task_json = {
            "task_id": task_id,
            "task_type": task_type_upper,
            "difficulty": scenario['difficulty'],
            "instruction": instruction,
            "input_workbook": f"{task_id}_input.xlsx",
            "golden_workbook": f"{task_id}_golden.xlsx",
            "answer_position": criteria_data.get('answer_position', []),
            "criteria": criteria_data.get('criteria', []),
            "metadata": {
                "route": "A",
                "domain": scenario.get('domain', 'General'),
                "concepts": scenario.get('key_concepts', scenario.get('key_metrics', [])),
                "estimated_time_minutes": scenario.get('estimated_time_minutes', 20),
                "seed_workbook_id": seed_path.stem,
                "generation_model": self.model,
                "creation_date": datetime.datetime.now().strftime("%Y-%m-%d"),
                "lineage": {
                    "source": "seed",
                    "seed_id": seed_path.stem,
                    "transformation": "llm_generated"
                }
            }
        }

        # Add visualization_criteria if present
        if 'visualization_criteria' in criteria_data:
            task_json['visualization_criteria'] = criteria_data['visualization_criteria']

        return task_json

    def _call_claude_api(self, system_prompt: str, user_prompt: str,
                         max_retries: int = 3) -> Optional[str]:
        """Call Claude API with retry logic"""
        for attempt in range(max_retries):
            try:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}]
                )
                # Extract text from response, filtering out thinking blocks
                for block in message.content:
                    if hasattr(block, 'text'):
                        return block.text
                raise ValueError("No text block found in response")
            except Exception as e:
                logging.warning(f"    API call attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logging.error(f"    ✗ API call failed after {max_retries} attempts")
                    return None

    def _extract_python_code(self, response: str) -> Optional[str]:
        """Extract Python code from Claude response"""
        # Look for code blocks
        if "```python" in response:
            code = response.split("```python")[1].split("```")[0].strip()
            return code
        elif "```" in response:
            code = response.split("```")[1].split("```")[0].strip()
            return code
        else:
            # Assume entire response is code
            return response.strip()

    def _execute_workbook_generation_code(self, code: str, output_path: Path) -> bool:
        """Execute Python code to generate workbook"""
        try:
            # Create a temporary Python file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False,
                                            encoding='utf-8') as f:
                # Inject output_path at the beginning
                f.write(f"output_path = r'{output_path}'\n\n")
                f.write(code)
                temp_script = f.name

            # Execute the script
            result = subprocess.run(
                [sys.executable, temp_script],
                capture_output=True,
                text=True,
                timeout=60
            )

            # Clean up
            os.unlink(temp_script)

            if result.returncode == 0 and output_path.exists():
                logging.info(f"    ✓ Generated workbook: {output_path.name}")
                return True
            else:
                logging.error(f"    ✗ Code execution failed")
                if result.stderr:
                    logging.error(f"    Error: {result.stderr[:500]}")
                return False

        except subprocess.TimeoutExpired:
            logging.error(f"    ✗ Code execution timeout (>60s)")
            return False
        except Exception as e:
            logging.error(f"    ✗ Code execution error: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Route A LLM Task Generator")
    parser.add_argument("--task-type", required=True, choices=["fm", "visualization", "viz"],
                       help="Task type to generate")
    parser.add_argument("--seed-dir", required=True, type=Path,
                       help="Directory containing seed workbooks")
    parser.add_argument("--output-dir", required=True, type=Path,
                       help="Output directory for generated tasks")
    parser.add_argument("--count", type=int, default=10,
                       help="Number of tasks to generate")
    parser.add_argument("--difficulty-mix", type=str,
                       help="Difficulty distribution (e.g., 'L2:0.3,L3:0.7')")
    parser.add_argument("--api-key", type=str,
                       help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    parser.add_argument("--model", type=str, default="claude-3-5-sonnet-20241022",
                       help="Claude model to use")
    parser.add_argument("--base-url", type=str,
                       help="Custom API base URL (optional)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # Get API key
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logging.error("API key required. Set --api-key or ANTHROPIC_API_KEY environment variable")
        return 1

    # Validate seed directory
    if not args.seed_dir.exists():
        logging.error(f"Seed directory not found: {args.seed_dir}")
        return 1

    # Find seed files
    all_seed_files = list(args.seed_dir.glob("*.xlsx"))
    if not all_seed_files:
        logging.error(f"No .xlsx files found in {args.seed_dir}")
        return 1

    # Filter out oversized files (>500KB) that cause API timeouts
    MAX_SEED_SIZE = 500 * 1024  # 500KB
    seed_files = [f for f in all_seed_files if f.stat().st_size <= MAX_SEED_SIZE]
    excluded_count = len(all_seed_files) - len(seed_files)

    if not seed_files:
        logging.error(f"No seed files under {MAX_SEED_SIZE//1024}KB found")
        return 1

    logging.info(f"Found {len(seed_files)} seed workbooks (excluded {excluded_count} oversized files)")

    # Parse difficulty mix
    difficulty_dist = {}
    if args.difficulty_mix:
        for item in args.difficulty_mix.split(','):
            level, prob = item.split(':')
            difficulty_dist[level.strip()] = float(prob.strip())
    else:
        # Default difficulty distribution
        if args.task_type == "fm":
            difficulty_dist = {"L3": 0.4, "L4": 0.6}
        else:
            difficulty_dist = {"L2": 0.3, "L3": 0.7}

    logging.info(f"Difficulty distribution: {difficulty_dist}")

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize generator
    generator = RouteAGenerator(
        api_key=api_key,
        task_type=args.task_type,
        output_dir=args.output_dir,
        model=args.model,
        base_url=args.base_url
    )

    # Generate tasks
    results = []
    for i in range(args.count):
        # Select random seed
        seed_file = random.choice(seed_files)

        # Select difficulty based on distribution
        difficulty = random.choices(
            list(difficulty_dist.keys()),
            weights=list(difficulty_dist.values())
        )[0]

        logging.info(f"\n{'='*60}")
        logging.info(f"Task {i+1}/{args.count} - Difficulty: {difficulty}")
        logging.info(f"{'='*60}")

        result = generator.generate_task(seed_file, i + 1, difficulty)
        results.append(result)

        # Brief pause between tasks
        if i < args.count - 1:
            time.sleep(1)

    # Generate report
    report_path = args.output_dir / "generation_report.json"
    report = {
        "task_type": args.task_type,
        "count_requested": args.count,
        "count_succeeded": sum(1 for r in results if r.success),
        "count_failed": sum(1 for r in results if not r.success),
        "difficulty_distribution": difficulty_dist,
        "model": args.model,
        "timestamp": datetime.datetime.now().isoformat(),
        "results": [
            {
                "task_id": r.task_id,
                "success": r.success,
                "error": r.error,
                "generation_time_seconds": r.generation_time_seconds
            }
            for r in results
        ]
    }

    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Print summary
    success_count = sum(1 for r in results if r.success)
    fail_count = sum(1 for r in results if not r.success)
    total_time = sum(r.generation_time_seconds for r in results)
    avg_time = total_time / len(results) if results else 0

    logging.info(f"\n{'='*60}")
    logging.info(f"GENERATION SUMMARY")
    logging.info(f"{'='*60}")
    logging.info(f"Total requested: {args.count}")
    logging.info(f"✓ Succeeded: {success_count} ({success_count/args.count*100:.1f}%)")
    logging.info(f"✗ Failed: {fail_count} ({fail_count/args.count*100:.1f}%)")
    logging.info(f"Average time per task: {avg_time:.1f}s")
    logging.info(f"Total time: {total_time:.1f}s ({total_time/60:.1f}m)")
    logging.info(f"\nReport saved to: {report_path}")

    return 0 if success_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
