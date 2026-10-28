#!/usr/bin/env python3
"""
S2 Template任务生成器

基于真实工作簿(golden)通过数据清空和公式保留生成Template填充任务。

核心逻辑:
1. 识别数据区域和公式区域
2. 清空数据区域的值(保留格式)，成为input.xlsx(空模板)
3. 保留golden.xlsx作为填充后的正确答案
4. 生成自然语言指令，描述需要填充的内容和公式
5. 答案位置为被清空的数据单元格

基于S1元数据智能定位:
- WorkbookMap: 识别数据sheet和计算sheet
- FormulaGraph: 区分源数据单元格和公式单元格
- StyleMap: 保留格式信息
"""

import random
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from openpyxl import load_workbook, Workbook
from openpyxl.utils import get_column_letter, column_index_from_string
import json
import hashlib

# 添加项目根目录到path以便导入
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from parse.workbook_parser import WorkbookParser

logger = logging.getLogger(__name__)


@dataclass
class DataRegion:
    """数据区域定义"""
    sheet_name: str
    min_row: int
    max_row: int
    min_col: int
    max_col: int
    cell_count: int
    description: str = ""

    def to_range_str(self) -> str:
        """转换为Excel范围字符串"""
        start_col = get_column_letter(self.min_col)
        end_col = get_column_letter(self.max_col)
        return f"{self.sheet_name}!{start_col}{self.min_row}:{end_col}{self.max_row}"


@dataclass
class TemplateTask:
    """Template任务定义"""
    task_id: str
    workbook_id: str
    difficulty: str
    instruction: str
    input_path: Path
    golden_path: Path
    answer_position: List[str]  # 被清空的单元格地址列表
    criteria: List[str]
    metadata: Dict
    data_regions: List[DataRegion] = field(default_factory=list)


class TemplateGenerator:
    """Template任务生成器"""

    def __init__(self, seed: Optional[int] = None):
        self.seed = seed
        if seed is not None:
            random.seed(seed)

    def generate(
        self,
        golden_path: Path,
        output_dir: Path,
        task_id: Optional[str] = None,
        workbook_id: Optional[str] = None
    ) -> TemplateTask:
        """
        生成Template任务

        Args:
            golden_path: 金标准工作簿路径(完整数据)
            output_dir: 输出目录
            task_id: 任务ID(可选，自动生成)
            workbook_id: 工作簿ID(可选，从文件名提取)

        Returns:
            TemplateTask对象
        """
        logger.info(f"生成Template任务: {golden_path}")

        # 解析S1元数据
        parser = WorkbookParser(golden_path)
        wmap, fgraph, smap, invs = parser.parse_all()
        parser.close()

        # 转换为字典格式
        metadata = {
            "workbook_map": wmap.to_dict(),
            "formula_graph": fgraph.to_dict(),
            "style_map": smap.to_dict(),
            "invariants": invs.to_dict()
        }

        # 提取workbook_id
        if workbook_id is None:
            workbook_id = golden_path.stem

        # 识别数据区域
        data_regions = self._identify_data_regions(golden_path, metadata)

        if not data_regions:
            raise ValueError(f"未找到可清空的数据区域: {golden_path}")

        logger.info(f"识别到{len(data_regions)}个数据区域")

        # 生成task_id
        if task_id is None:
            random_suffix = random.randint(1000, 9999)
            task_id = f"{workbook_id}_template_{random_suffix}"

        # 创建input.xlsx (清空数据)
        input_path = output_dir / f"{task_id}_input.xlsx"
        answer_cells = self._create_input_workbook(
            golden_path, input_path, data_regions
        )

        # 复制golden.xlsx
        golden_output_path = output_dir / f"{task_id}_golden.xlsx"
        import shutil
        shutil.copy2(golden_path, golden_output_path)

        # 生成指令
        instruction = self._generate_instruction(data_regions, metadata)

        # 生成criteria
        criteria = self._generate_criteria(data_regions, metadata)

        # 评估难度
        difficulty = self._estimate_difficulty(data_regions, metadata)

        # 构建任务对象
        task = TemplateTask(
            task_id=task_id,
            workbook_id=workbook_id,
            difficulty=difficulty,
            instruction=instruction,
            input_path=input_path,
            golden_path=golden_output_path,
            answer_position=answer_cells,
            criteria=criteria,
            data_regions=data_regions,
            metadata={
                "cleared_cells_count": len(answer_cells),
                "data_regions_count": len(data_regions),
                "sheets": [s["name"] for s in metadata["workbook_map"]["sheets"]],
                "formula_cells_total": len(metadata["formula_graph"]["cells"]),
                "data_regions": [
                    {
                        "range": r.to_range_str(),
                        "cell_count": r.cell_count,
                        "description": r.description
                    }
                    for r in data_regions
                ]
            }
        )

        formula_cells_total = len(metadata["formula_graph"]["cells"])

        logger.info(f"✓ 生成Template任务: {task_id}")
        logger.info(f"  清空{len(answer_cells)}个数据单元格")
        logger.info(f"  涉及{len(data_regions)}个数据区域")
        logger.info(f"  公式单元格: {formula_cells_total}")
        logger.info(f"  难度: {difficulty}")

        # 验证: Template任务必须有公式约束
        if formula_cells_total == 0 and len(answer_cells) > 0:
            logger.warning(f"生成的Template任务无公式约束,将被S3筛选器拒绝")
            logger.warning(f"建议: 跳过纯数据工作簿,选择有公式的工作簿生成Template任务")

        return task

    def _identify_data_regions(
        self,
        golden_path: Path,
        metadata: Dict
    ) -> List[DataRegion]:
        """
        识别可清空的数据区域

        策略:
        1. 公式单元格不清空(保留公式)
        2. 标题行/列不清空(保留结构)
        3. 空单元格不清空
        4. 识别连续的数据块
        """
        wb = load_workbook(golden_path, data_only=False)
        formula_cells = set(metadata["formula_graph"]["cells"].keys())

        data_regions = []

        # metadata["workbook_map"]["sheets"] is a list, not a dict
        for sheet_info in metadata["workbook_map"]["sheets"]:
            sheet_name = sheet_info["name"]
            ws = wb[sheet_name]

            # 跳过空sheet
            if ws.max_row is None or ws.max_row == 0:
                continue

            # 识别数据区域
            regions = self._find_data_blocks(
                ws, sheet_name, formula_cells
            )
            data_regions.extend(regions)

        wb.close()
        return data_regions

    def _find_data_blocks(
        self,
        ws,
        sheet_name: str,
        formula_cells: Set[str]
    ) -> List[DataRegion]:
        """
        在一个sheet中查找数据块

        策略:
        1. 找到所有非空、非公式的单元格
        2. 聚类为连续区域
        3. 过滤掉小于5个单元格的区域(可能是标题)
        """
        # 收集所有数据单元格
        data_cells = []

        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue

                cell_addr = f"{sheet_name}!{cell.coordinate}"

                # 跳过公式单元格
                if cell_addr in formula_cells:
                    continue

                # 跳过可能的标题(第一行或第一列的文本)
                if cell.row == 1 or cell.column == 1:
                    if isinstance(cell.value, str):
                        continue

                data_cells.append((cell.row, cell.column, cell.value))

        if not data_cells:
            return []

        # 简单策略: 找最大连续矩形区域
        rows = [c[0] for c in data_cells]
        cols = [c[1] for c in data_cells]

        min_row, max_row = min(rows), max(rows)
        min_col, max_col = min(cols), max(cols)

        cell_count = len(data_cells)

        # 过滤太小的区域
        if cell_count < 5:
            return []

        # 生成描述
        description = self._describe_data_region(
            ws, min_row, max_row, min_col, max_col
        )

        region = DataRegion(
            sheet_name=sheet_name,
            min_row=min_row,
            max_row=max_row,
            min_col=min_col,
            max_col=max_col,
            cell_count=cell_count,
            description=description
        )

        return [region]

    def _describe_data_region(
        self,
        ws,
        min_row: int,
        max_row: int,
        min_col: int,
        max_col: int
    ) -> str:
        """生成数据区域的描述"""
        # 检查附近的标题单元格
        row_header = None
        col_header = None

        # 检查左侧列标题
        if min_col > 1:
            left_cell = ws.cell(min_row, min_col - 1)
            if left_cell.value and isinstance(left_cell.value, str):
                row_header = left_cell.value

        # 检查上方行标题
        if min_row > 1:
            top_cell = ws.cell(min_row - 1, min_col)
            if top_cell.value and isinstance(top_cell.value, str):
                col_header = top_cell.value

        # 构建描述
        if row_header and col_header:
            return f"{row_header} data for {col_header}"
        elif row_header:
            return f"{row_header} data"
        elif col_header:
            return f"Data for {col_header}"
        else:
            return "Data block"

    def _create_input_workbook(
        self,
        golden_path: Path,
        input_path: Path,
        data_regions: List[DataRegion]
    ) -> List[str]:
        """
        创建input工作簿(清空数据区域)

        Returns:
            被清空的单元格地址列表(answer_position)
        """
        wb = load_workbook(golden_path)
        answer_cells = []

        for region in data_regions:
            ws = wb[region.sheet_name]

            # 清空区域内的数据单元格
            for row in range(region.min_row, region.max_row + 1):
                for col in range(region.min_col, region.max_col + 1):
                    cell = ws.cell(row, col)

                    # 跳过公式单元格
                    if cell.value and isinstance(cell.value, str):
                        if cell.value.startswith('='):
                            continue

                    # 清空值(保留格式)
                    if cell.value is not None:
                        cell_addr = f"{region.sheet_name}!{cell.coordinate}"
                        answer_cells.append(cell_addr)
                        cell.value = None

        wb.save(input_path)
        wb.close()

        return answer_cells

    def _generate_instruction(
        self,
        data_regions: List[DataRegion],
        metadata: Dict
    ) -> str:
        """生成任务指令"""
        # Get sheet names from list
        sheet_names = [s["name"] for s in metadata["workbook_map"]["sheets"]]
        sheets_list = ", ".join(sheet_names)
        sheet_count = len(sheet_names)

        # 统计被清空的单元格数
        total_cells = sum(r.cell_count for r in data_regions)

        # 构建指令
        instruction = f"This workbook template has {total_cells} empty data cell(s) "
        instruction += f"that need to be filled in. "

        if len(data_regions) == 1:
            instruction += f"The data region is in '{data_regions[0].sheet_name}' "
            instruction += f"at range {data_regions[0].to_range_str().split('!')[1]}. "
        else:
            instruction += f"The data is spread across {len(data_regions)} region(s) "
            instruction += f"in sheet(s): {', '.join(set(r.sheet_name for r in data_regions))}. "

        instruction += f"\n\nFill in the missing data values. "
        instruction += f"The workbook contains formulas that will automatically calculate "
        instruction += f"derived values once you fill in the source data."

        instruction += f"\n\nThe workbook contains {sheet_count} sheet(s): {sheets_list}."

        return instruction

    def _generate_criteria(
        self,
        data_regions: List[DataRegion],
        metadata: Dict
    ) -> List[str]:
        """生成评分标准"""
        criteria = []

        # 基础标准
        criteria.append(
            "All data cells in the specified regions must be filled with correct values"
        )

        # 公式完整性
        formula_count = len(metadata["formula_graph"]["cells"])
        if formula_count > 0:
            criteria.append(
                f"All {formula_count} formula(s) must remain unchanged and calculate correctly"
            )

        # 格式保留
        criteria.append(
            "Cell formatting (colors, borders, number formats) must be preserved"
        )

        # 不变量检查
        invariants = metadata.get("invariants", {}).get("checks", [])
        if invariants:
            criteria.append(
                f"Workbook invariants must be satisfied ({len(invariants)} constraint(s) detected)"
            )

        return criteria

    def _estimate_difficulty(
        self,
        data_regions: List[DataRegion],
        metadata: Dict
    ) -> str:
        """
        评估难度

        难度因素:
        - 数据单元格数量
        - 公式单元格数量
        - Sheet数量
        - 是否有不变量约束
        """
        total_data_cells = sum(r.cell_count for r in data_regions)
        formula_count = len(metadata["formula_graph"]["cells"])
        sheet_count = len(metadata["workbook_map"]["sheets"])
        invariant_count = len(metadata.get("invariants", {}).get("checks", []))

        # 计算复杂度得分
        score = 0

        # 数据单元格 (0-30分)
        if total_data_cells < 10:
            score += 5
        elif total_data_cells < 30:
            score += 15
        elif total_data_cells < 50:
            score += 25
        else:
            score += 30

        # 公式单元格 (0-30分)
        if formula_count < 10:
            score += 5
        elif formula_count < 50:
            score += 15
        elif formula_count < 100:
            score += 25
        else:
            score += 30

        # Sheet数量 (0-20分)
        if sheet_count <= 2:
            score += 5
        elif sheet_count <= 5:
            score += 10
        elif sheet_count <= 10:
            score += 15
        else:
            score += 20

        # 不变量约束 (0-20分)
        if invariant_count == 0:
            score += 0
        elif invariant_count <= 2:
            score += 10
        else:
            score += 20

        # 映射到难度级别
        if score < 30:
            return "L1"
        elif score < 50:
            return "L2"
        elif score < 70:
            return "L3"
        else:
            return "L4"

    def export_task_json(self, task: TemplateTask, output_path: Path):
        """导出任务JSON"""
        task_dict = {
            "task_id": task.task_id,
            "workbook_id": task.workbook_id,
            "type": "Template",
            "sub_type": "Data Filling",
            "difficulty": task.difficulty,
            "instruction": task.instruction,
            "input_path": str(task.input_path),
            "golden_path": str(task.golden_path),
            "answer_position": task.answer_position,
            "criteria": task.criteria,
            "metadata": task.metadata
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(task_dict, f, indent=2, ensure_ascii=False)

        logger.info(f"导出任务JSON: {output_path}")


def main():
    """测试用主函数"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # 测试文件
    demo_dir = Path("/mnt/hhq/data/files_demo")
    golden_path = demo_dir / "0_ref_0.xlsx"

    if not golden_path.exists():
        logger.error(f"测试文件不存在: {golden_path}")
        return

    # 创建输出目录
    output_dir = Path("/tmp/template_test")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 生成任务
    generator = TemplateGenerator(seed=42)
    task = generator.generate(
        golden_path=golden_path,
        output_dir=output_dir
    )

    # 导出JSON
    json_path = output_dir / f"{task.task_id}.json"
    generator.export_task_json(task, json_path)

    print("\n" + "="*80)
    print("生成成功!")
    print("="*80)
    print(f"Task ID: {task.task_id}")
    print(f"难度: {task.difficulty}")
    print(f"清空单元格数: {len(task.answer_position)}")
    print(f"数据区域数: {len(task.data_regions)}")
    print(f"\n输出文件:")
    print(f"  - {task.input_path}")
    print(f"  - {task.golden_path}")
    print(f"  - {json_path}")
    print("="*80)


if __name__ == "__main__":
    main()
