"""
S2 任务生成 - Debugging错误注入器

基于S1解析的元数据，向golden工作簿注入10种类型的错误，生成input工作簿。
核心思路：
1. 使用FormulaGraph定位可注入的公式单元格
2. 使用Invariants验证golden的正确性
3. 注入错误时保持工作簿的可打开性和可重算性
4. 生成自然语言指令描述错误症状（不泄露答案）
"""

import json
import logging
import random
import re
import shutil
import sys
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import openpyxl
from openpyxl import Workbook, load_workbook
from openpyxl.cell import Cell
from openpyxl.utils import get_column_letter

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import DEBUGGING_ERROR_TYPES, ERROR_COUNT_DISTRIBUTION
from parse.workbook_parser import (
    FormulaGraph,
    Invariants,
    StyleMap,
    WorkbookMap,
    WorkbookParser,
)

logger = logging.getLogger(__name__)


@dataclass
class InjectedError:
    """单个注入的错误"""
    error_type: str
    cell_address: str  # Sheet1!A1
    original_value: str
    injected_value: str
    description: str  # 对用户可见的症状描述（不泄露答案）


@dataclass
class DebuggingTask:
    """生成的Debugging任务"""
    task_id: str
    workbook_id: str
    error_type_primary: str  # 主要错误类型
    injected_errors: List[InjectedError]
    instruction: str  # 自然语言任务描述
    input_path: Path
    golden_path: Path
    metadata: Dict = field(default_factory=dict)


class DebuggingGenerator:
    """Debugging任务生成器"""

    def __init__(
        self,
        seed: int = 42,
        error_count_dist: Dict = None,
        strict: bool = True
    ):
        """
        Args:
            seed: 随机种子
            error_count_dist: 错误数量分布（默认使用config）
            strict: 是否严格模式（注入后验证invariants）
        """
        self.seed = seed
        self.error_count_dist = error_count_dist or ERROR_COUNT_DISTRIBUTION
        self.strict = strict
        random.seed(seed)

    def generate(
        self,
        golden_path: Path,
        output_dir: Path,
        task_id: Optional[str] = None,
        error_type: Optional[str] = None
    ) -> DebuggingTask:
        """
        从golden工作簿生成一个Debugging任务

        Args:
            golden_path: 正确的工作簿路径
            output_dir: 输出目录
            task_id: 任务ID（如果None则自动生成）
            error_type: 指定错误类型（如果None则随机选择）

        Returns:
            DebuggingTask对象
        """
        if not golden_path.exists():
            raise FileNotFoundError(f"Golden文件不存在: {golden_path}")

        # 解析golden工作簿的元数据
        logger.info(f"解析golden工作簿: {golden_path.name}")
        parser = WorkbookParser(golden_path)
        wmap, fgraph, smap, invs = parser.parse_all()

        # 验证golden的invariants
        if self.strict and invs.checks:
            logger.info(f"验证golden的{len(invs.checks)}个invariants")
            # TODO: 实际验证逻辑（需要重算）

        # 选择错误类型
        if error_type is None:
            error_type = random.choice(DEBUGGING_ERROR_TYPES)
        elif error_type not in DEBUGGING_ERROR_TYPES:
            raise ValueError(f"未知错误类型: {error_type}")

        # 确定错误数量
        error_count = self._sample_error_count()

        # 生成task_id
        if task_id is None:
            task_id = f"{golden_path.stem}_{error_type.replace(' ', '_').lower()}_{random.randint(1000, 9999)}"

        # 复制golden为input（稍后注入错误）
        output_dir.mkdir(parents=True, exist_ok=True)
        input_path = output_dir / f"{task_id}_input.xlsx"
        golden_output_path = output_dir / f"{task_id}_golden.xlsx"

        shutil.copy(golden_path, input_path)
        shutil.copy(golden_path, golden_output_path)

        # 加载input工作簿准备注入（保留公式）
        wb_input = load_workbook(input_path)

        # 注入错误
        logger.info(f"注入{error_count}个'{error_type}'类型错误")
        injected_errors = self._inject_errors(
            wb_input,
            error_type,
            error_count,
            fgraph,
            wmap,
            smap,
            golden_path  # 传递golden路径用于获取计算值
        )

        if not injected_errors:
            wb_input.close()
            raise ValueError(
                f"'{error_type}'注入器未找到可注入的目标模式(如INDEX-MATCH/SUM公式)，"
                f"生成的input与golden完全一致，answer_position会是空列表: {golden_path.name}"
            )

        # 保存修改后的input
        wb_input.save(input_path)
        wb_input.close()

        # 生成自然语言指令
        instruction = self._generate_instruction(
            error_type,
            injected_errors,
            wmap
        )

        task = DebuggingTask(
            task_id=task_id,
            workbook_id=golden_path.stem,
            error_type_primary=error_type,
            injected_errors=injected_errors,
            instruction=instruction,
            input_path=input_path,
            golden_path=golden_output_path,
            metadata={
                "error_count": len(injected_errors),
                "formula_cells_total": len(fgraph.cells),
                "sheets": [sheet.get("name", f"Sheet{i+1}") for i, sheet in enumerate(wmap.sheets)]
            }
        )

        logger.info(f"✓ 生成任务: {task_id}")
        return task

    def _sample_error_count(self) -> int:
        """采样错误数量"""
        rand = random.random()
        cumsum = 0.0
        for key, prob in self.error_count_dist.items():
            cumsum += prob
            if rand < cumsum:
                if isinstance(key, int):
                    return key
                elif isinstance(key, str) and "-" in key:
                    low, high = map(int, key.split("-"))
                    return random.randint(low, high)
        return 1  # fallback

    def _inject_errors(
        self,
        wb: Workbook,
        error_type: str,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap,
        golden_path: Path = None
    ) -> List[InjectedError]:
        """
        注入指定类型和数量的错误

        Returns:
            实际注入的错误列表
        """
        injector_method = {
            "Double Counting": self._inject_double_counting,
            "Embedded Hardcodes": lambda wb, c, fg, wm, sm: self._inject_embedded_hardcodes(wb, c, fg, wm, sm, golden_path),
            "Errors": self._inject_formula_errors,
            "Inconsistent Color": self._inject_inconsistent_color,
            "Incorrect Average": self._inject_incorrect_average,
            "Cross-Sheet References": self._inject_cross_sheet_ref_error,
            "Incorrect index-match": self._inject_incorrect_index_match,
            "Incorrect Sign": self._inject_incorrect_sign,
            "Relative vs Absolute References": self._inject_relative_absolute_error,
            "Unit Mismatch": self._inject_unit_mismatch,
        }.get(error_type)

        if injector_method is None:
            logger.warning(f"错误类型'{error_type}'的注入器未实现，使用通用注入")
            return self._inject_generic_formula_error(wb, count, fgraph)

        return injector_method(wb, count, fgraph, wmap, smap)

    # ========================================================================
    # 错误注入方法（每种错误类型一个）
    # ========================================================================

    def _inject_double_counting(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap
    ) -> List[InjectedError]:
        """Double Counting: SUM中重复引用某个单元格"""
        errors = []
        sum_formulas = [
            (addr, cell) for addr, cell in fgraph.cells.items()
            if cell.get("formula", "").upper().startswith("=SUM(")
        ]

        if not sum_formulas:
            logger.warning("未找到SUM公式，无法注入Double Counting")
            return errors

        candidates = random.sample(sum_formulas, min(count, len(sum_formulas)))

        for addr, cell_data in candidates:
            original_formula = cell_data["formula"]
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            # 解析SUM范围 =SUM(A1:A10) -> A1:A10
            match = re.search(r'SUM\(([^)]+)\)', original_formula, re.IGNORECASE)
            if not match:
                continue

            range_str = match.group(1)
            # 简单处理：在范围后面重复第一个单元格
            # =SUM(A1:A10) -> =SUM(A1:A10,A1)
            if ":" in range_str:
                first_cell = range_str.split(":")[0]
                injected_formula = original_formula.replace(
                    f"SUM({range_str})",
                    f"SUM({range_str},{first_cell})"
                )
            else:
                # 已经是离散单元格
                injected_formula = original_formula.replace(
                    f"SUM({range_str})",
                    f"SUM({range_str},{range_str})"
                )

            cell.value = injected_formula

            errors.append(InjectedError(
                error_type="Double Counting",
                cell_address=addr,
                original_value=original_formula,
                injected_value=injected_formula,
                description=f"Cell {addr} may be counting some values twice"
            ))

        return errors

    def _inject_embedded_hardcodes(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap,
        golden_path: Path = None
    ) -> List[InjectedError]:
        """Embedded Hardcodes: 公式中替换单元格引用为硬编码数值"""
        errors = []

        # 需要加载data_only=True的版本获取计算值
        wb_values = None
        if golden_path:
            try:
                wb_values = load_workbook(golden_path, data_only=True)
            except Exception as e:
                logger.warning(f"无法加载golden_path用于获取计算值: {e}")

        if wb_values is None:
            logger.warning("golden_path未提供或无法加载，Embedded Hardcodes注入可能失败")
            return errors

        formula_cells = [
            (addr, cell) for addr, cell in fgraph.cells.items()
            if "+" in cell.get("formula", "") or "*" in cell.get("formula", "")
        ]

        if not formula_cells:
            logger.warning("未找到适合的公式单元格（需要包含+或*）")
            return errors

        candidates = random.sample(formula_cells, min(count, len(formula_cells)))

        for addr, cell_data in candidates:
            original_formula = cell_data["formula"]
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            # 找到公式中的第一个单元格引用（同一sheet），替换为硬编码值
            # 匹配 A1 风格的引用（不包含sheet前缀）
            match = re.search(r'(?<![A-Z!])([A-Z]+\d+)(?![A-Z0-9])', original_formula)
            if not match:
                logger.debug(f"未找到可替换的单元格引用: {original_formula}")
                continue

            ref = match.group(1)
            try:
                # 使用data_only版本获取计算值
                ws_values = wb_values[sheet_name]
                hardcoded_value = ws_values[ref].value

                if hardcoded_value is None:
                    hardcoded_value = 0

                # 只有数值类型才替换
                if isinstance(hardcoded_value, (int, float)):
                    # 格式化数值，避免科学计数法
                    if isinstance(hardcoded_value, float) and hardcoded_value == int(hardcoded_value):
                        hardcoded_str = str(int(hardcoded_value))
                    else:
                        hardcoded_str = str(hardcoded_value)

                    injected_formula = original_formula.replace(ref, hardcoded_str, 1)
                    cell.value = injected_formula

                    errors.append(InjectedError(
                        error_type="Embedded Hardcodes",
                        cell_address=addr,
                        original_value=original_formula,
                        injected_value=injected_formula,
                        description=f"Cell {addr} contains hardcoded values instead of cell references"
                    ))
                else:
                    logger.debug(f"引用单元格 {ref} 值不是数值: {type(hardcoded_value).__name__}")
            except Exception as e:
                logger.debug(f"无法处理引用 {ref}: {e}")
                continue

        if wb_values:
            wb_values.close()

        return errors

    def _inject_formula_errors(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap
    ) -> List[InjectedError]:
        """Errors: 注入导致#REF!、#VALUE!、#DIV/0!的错误"""
        errors = []
        formula_cells = list(fgraph.cells.items())

        if not formula_cells:
            return errors

        candidates = random.sample(formula_cells, min(count, len(formula_cells)))

        for addr, cell_data in candidates:
            original_formula = cell_data["formula"]
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            # 随机选择错误类型
            error_kind = random.choice(["#REF!", "#DIV/0!", "#VALUE!"])

            if error_kind == "#REF!":
                # 引用一个不存在的单元格
                injected_formula = original_formula + "+ZZ9999"
            elif error_kind == "#DIV/0!":
                # 除以0
                injected_formula = f"=({original_formula.lstrip('=')})/0"
            else:  # #VALUE!
                # 在数值计算中引用文本
                injected_formula = original_formula.replace(")", '+"")')

            cell.value = injected_formula

            errors.append(InjectedError(
                error_type="Errors",
                cell_address=addr,
                original_value=original_formula,
                injected_value=injected_formula,
                description=f"Cell {addr} shows error value {error_kind}"
            ))

        return errors

    def _inject_inconsistent_color(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap
    ) -> List[InjectedError]:
        """Inconsistent Color: 修改单元格颜色使其与预期不符"""
        errors = []

        # 找到有颜色信息的单元格
        colored_cells = [
            addr for addr, style in smap.styles.items()
            if style.get("fill_color") and style.get("fill_color") != "FFFFFF"
        ]

        if not colored_cells:
            logger.warning("未找到有颜色的单元格")
            return errors

        candidates = random.sample(colored_cells, min(count, len(colored_cells)))

        for addr in candidates:
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            original_color = smap.styles[addr].get("fill_color", "FFFFFF")

            # 改为红色（表示错误）
            from openpyxl.styles import PatternFill
            cell.fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")

            errors.append(InjectedError(
                error_type="Inconsistent Color",
                cell_address=addr,
                original_value=f"color:{original_color}",
                injected_value="color:FF0000",
                description=f"Cell {addr} has incorrect highlighting color"
            ))

        return errors

    def _inject_incorrect_average(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap
    ) -> List[InjectedError]:
        """Incorrect Average: AVERAGE公式改为SUM或错误范围"""
        errors = []
        avg_formulas = [
            (addr, cell) for addr, cell in fgraph.cells.items()
            if "AVERAGE" in cell.get("formula", "").upper()
        ]

        if not avg_formulas:
            logger.warning("未找到AVERAGE公式")
            return errors

        candidates = random.sample(avg_formulas, min(count, len(avg_formulas)))

        for addr, cell_data in candidates:
            original_formula = cell_data["formula"]
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            # 改为SUM（最常见的平均值错误）
            injected_formula = original_formula.replace("AVERAGE", "SUM")
            cell.value = injected_formula

            errors.append(InjectedError(
                error_type="Incorrect Average",
                cell_address=addr,
                original_value=original_formula,
                injected_value=injected_formula,
                description=f"Cell {addr} calculates the average incorrectly"
            ))

        return errors

    def _inject_cross_sheet_ref_error(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap
    ) -> List[InjectedError]:
        """Cross-Sheet References: 跨sheet引用指向错误的sheet"""
        errors = []
        cross_sheet_formulas = [
            (addr, cell) for addr, cell in fgraph.cells.items()
            if "!" in cell.get("formula", "")
        ]

        if not cross_sheet_formulas:
            logger.warning("未找到跨sheet引用")
            return errors

        candidates = random.sample(cross_sheet_formulas, min(count, len(cross_sheet_formulas)))

        for addr, cell_data in candidates:
            original_formula = cell_data["formula"]
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            # 找到公式中的sheet引用，修改为错误的sheet名
            match = re.search(r"'?([^'!]+)'?!", original_formula)
            if match:
                old_sheet = match.group(1)
                # 改为当前sheet（造成循环引用）或随机sheet
                if old_sheet != sheet_name:
                    injected_formula = original_formula.replace(
                        f"{old_sheet}!",
                        f"{sheet_name}!",
                        1
                    )
                    cell.value = injected_formula

                    errors.append(InjectedError(
                        error_type="Cross-Sheet References",
                        cell_address=addr,
                        original_value=original_formula,
                        injected_value=injected_formula,
                        description=f"Cell {addr} references wrong sheet"
                    ))

        return errors

    def _inject_incorrect_index_match(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap
    ) -> List[InjectedError]:
        """Incorrect INDEX-MATCH: 修改INDEX或MATCH函数的参数"""
        errors = []
        index_match_formulas = [
            (addr, cell) for addr, cell in fgraph.cells.items()
            if "INDEX" in cell.get("formula", "").upper() and "MATCH" in cell.get("formula", "").upper()
        ]

        if not index_match_formulas:
            logger.warning("未找到INDEX-MATCH公式")
            return errors

        candidates = random.sample(index_match_formulas, min(count, len(index_match_formulas)))

        for addr, cell_data in candidates:
            original_formula = cell_data["formula"]
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            # 修改MATCH的第三参数（0->1或1->0）
            injected_formula = re.sub(
                r'MATCH\(([^,]+),([^,]+),0\)',
                r'MATCH(\1,\2,1)',
                original_formula,
                flags=re.IGNORECASE
            )

            if injected_formula == original_formula:
                # 如果没匹配到，尝试其他模式
                injected_formula = re.sub(
                    r'MATCH\(([^,]+),([^,]+),1\)',
                    r'MATCH(\1,\2,0)',
                    original_formula,
                    flags=re.IGNORECASE
                )

            if injected_formula != original_formula:
                cell.value = injected_formula

                errors.append(InjectedError(
                    error_type="Incorrect index-match",
                    cell_address=addr,
                    original_value=original_formula,
                    injected_value=injected_formula,
                    description=f"Cell {addr} has incorrect INDEX-MATCH lookup"
                ))

        return errors

    def _inject_incorrect_sign(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap
    ) -> List[InjectedError]:
        """Incorrect Sign: 加号改减号，乘号改除号"""
        errors = []
        arithmetic_formulas = [
            (addr, cell) for addr, cell in fgraph.cells.items()
            if any(op in cell.get("formula", "") for op in ["+", "-", "*", "/"])
        ]

        if not arithmetic_formulas:
            return errors

        candidates = random.sample(arithmetic_formulas, min(count, len(arithmetic_formulas)))

        for addr, cell_data in candidates:
            original_formula = cell_data["formula"]
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            # 随机选择一个运算符翻转
            if "+" in original_formula and random.random() < 0.5:
                injected_formula = original_formula.replace("+", "-", 1)
            elif "-" in original_formula and random.random() < 0.5:
                injected_formula = original_formula.replace("-", "+", 1)
            elif "*" in original_formula and random.random() < 0.5:
                injected_formula = original_formula.replace("*", "/", 1)
            elif "/" in original_formula:
                injected_formula = original_formula.replace("/", "*", 1)
            else:
                continue

            cell.value = injected_formula

            errors.append(InjectedError(
                error_type="Incorrect Sign",
                cell_address=addr,
                original_value=original_formula,
                injected_value=injected_formula,
                description=f"Cell {addr} has incorrect arithmetic operator"
            ))

        return errors

    def _inject_relative_absolute_error(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap
    ) -> List[InjectedError]:
        """Relative vs Absolute References: $A$1改为A1或反过来"""
        errors = []
        formula_cells = list(fgraph.cells.items())

        if not formula_cells:
            return errors

        candidates = random.sample(formula_cells, min(count, len(formula_cells)))

        for addr, cell_data in candidates:
            original_formula = cell_data["formula"]
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            # 寻找绝对引用改为相对引用
            if "$" in original_formula:
                injected_formula = original_formula.replace("$", "")
            else:
                # 相对引用改为绝对引用
                injected_formula = re.sub(
                    r'\b([A-Z]+)(\d+)\b',
                    r'$\1$\2',
                    original_formula
                )

            if injected_formula != original_formula:
                cell.value = injected_formula

                errors.append(InjectedError(
                    error_type="Relative vs Absolute References",
                    cell_address=addr,
                    original_value=original_formula,
                    injected_value=injected_formula,
                    description=f"Cell {addr} has incorrect cell reference type"
                ))

        return errors

    def _inject_unit_mismatch(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph,
        wmap: WorkbookMap,
        smap: StyleMap
    ) -> List[InjectedError]:
        """Unit Mismatch: 数值乘以或除以1000/1000000造成单位错误"""
        errors = []
        numeric_formulas = [
            (addr, cell) for addr, cell in fgraph.cells.items()
            if any(op in cell.get("formula", "") for op in ["+", "-", "*", "/"])
        ]

        if not numeric_formulas:
            return errors

        candidates = random.sample(numeric_formulas, min(count, len(numeric_formulas)))

        for addr, cell_data in candidates:
            original_formula = cell_data["formula"]
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            # 在公式末尾乘以或除以1000
            unit_factor = random.choice([1000, 1000000])
            operation = random.choice(["*", "/"])
            injected_formula = f"=({original_formula.lstrip('=')}){operation}{unit_factor}"
            cell.value = injected_formula

            errors.append(InjectedError(
                error_type="Unit Mismatch",
                cell_address=addr,
                original_value=original_formula,
                injected_value=injected_formula,
                description=f"Cell {addr} has incorrect unit conversion (thousands/millions)"
            ))

        return errors

    def _inject_generic_formula_error(
        self,
        wb: Workbook,
        count: int,
        fgraph: FormulaGraph
    ) -> List[InjectedError]:
        """通用错误注入：随机修改公式"""
        errors = []
        formula_cells = list(fgraph.cells.items())

        if not formula_cells:
            logger.warning("未找到公式单元格")
            return errors

        candidates = random.sample(formula_cells, min(count, len(formula_cells)))

        for addr, cell_data in candidates:
            original_formula = cell_data["formula"]
            sheet_name, cell_coord = addr.split("!")
            ws = wb[sheet_name]
            cell = ws[cell_coord]

            # 简单修改：在公式末尾+1
            injected_formula = f"=({original_formula.lstrip('=')})+1"
            cell.value = injected_formula

            errors.append(InjectedError(
                error_type="Generic",
                cell_address=addr,
                original_value=original_formula,
                injected_value=injected_formula,
                description=f"Cell {addr} has incorrect formula"
            ))

        return errors

    # ========================================================================
    # 指令生成
    # ========================================================================

    def _generate_instruction(
        self,
        error_type: str,
        injected_errors: List[InjectedError],
        wmap: WorkbookMap
    ) -> str:
        """
        生成自然语言任务指令

        关键原则：描述症状，不泄露答案位置
        """
        error_count = len(injected_errors)

        # 提取sheets信息 - wmap.sheets是一个list of dicts
        sheets_list = [sheet.get("name", f"Sheet{i+1}") for i, sheet in enumerate(wmap.sheets)]
        sheets_str = ", ".join(sheets_list[:3])
        if len(sheets_list) > 3:
            sheets_str += f", and {len(sheets_list) - 3} more"

        # 根据错误类型生成指令模板
        templates = {
            "Double Counting": [
                f"This workbook contains {error_count} error(s) where some values are being counted multiple times in summations. Review the formulas and fix the double counting issues.",
                f"Some cells in this spreadsheet are incorrectly summing values by including duplicate references. Identify and correct these {error_count} formula(s)."
            ],
            "Embedded Hardcodes": [
                f"This workbook has {error_count} formula(s) that contain hardcoded values instead of cell references. Replace the hardcoded values with proper cell references.",
                f"Some formulas contain literal numbers instead of referencing cells. Find and fix these {error_count} embedded hardcodes."
            ],
            "Errors": [
                f"This spreadsheet contains {error_count} cell(s) showing error values (#REF!, #VALUE!, #DIV/0!, etc.). Debug and fix these errors.",
                f"There are {error_count} formula error(s) in this workbook. Identify the root causes and correct them."
            ],
            "Inconsistent Color": [
                f"This workbook has {error_count} cell(s) with incorrect highlighting colors. Update the cell colors to match the intended formatting.",
                f"Some cells have wrong background colors. Find and correct the {error_count} inconsistent cell color(s)."
            ],
            "Incorrect Average": [
                f"This spreadsheet contains {error_count} cell(s) where averages are calculated incorrectly. Fix the average calculations.",
                f"Some cells compute averages using wrong formulas. Identify and correct these {error_count} calculation(s)."
            ],
            "Cross-Sheet References": [
                f"This workbook has {error_count} formula(s) that reference the wrong sheet. Correct the cross-sheet references.",
                f"Some formulas pull data from incorrect sheets. Find and fix these {error_count} cross-sheet reference error(s)."
            ],
            "Incorrect index-match": [
                f"This spreadsheet contains {error_count} INDEX-MATCH formula(s) with incorrect lookup parameters. Fix the lookup formulas.",
                f"Some INDEX-MATCH formulas have wrong match types or parameters. Identify and correct these {error_count} lookup error(s)."
            ],
            "Incorrect Sign": [
                f"This workbook has {error_count} formula(s) with incorrect arithmetic operators (+ vs -, × vs ÷). Fix the signs.",
                f"Some calculations use wrong arithmetic operators. Find and correct these {error_count} sign error(s)."
            ],
            "Relative vs Absolute References": [
                f"This spreadsheet contains {error_count} formula(s) with incorrect cell reference types (relative vs absolute). Fix the $ anchor usage.",
                f"Some formulas have wrong relative/absolute references. Identify and correct these {error_count} reference type error(s)."
            ],
            "Unit Mismatch": [
                f"This workbook has {error_count} cell(s) with unit conversion errors (thousands, millions, etc.). Fix the unit mismatches.",
                f"Some values are in wrong units (off by 1000x or 1000000x). Find and correct these {error_count} unit error(s)."
            ]
        }

        # 随机选择一个模板
        template_list = templates.get(error_type, [
            f"This workbook contains {error_count} error(s). Review the formulas and correct them."
        ])
        instruction = random.choice(template_list)

        # 添加上下文信息
        instruction += f"\n\nThe workbook contains {len(sheets_list)} sheet(s): {sheets_str}."

        return instruction

    # ========================================================================
    # 批量生成
    # ========================================================================

    def batch_generate(
        self,
        golden_files: List[Path],
        output_dir: Path,
        tasks_per_file: int = 1,
        error_types: Optional[List[str]] = None
    ) -> List[DebuggingTask]:
        """
        批量生成Debugging任务

        Args:
            golden_files: golden工作簿列表
            output_dir: 输出目录
            tasks_per_file: 每个文件生成几个任务
            error_types: 限制错误类型（如果None则使用全部10种）

        Returns:
            生成的任务列表
        """
        if error_types is None:
            error_types = DEBUGGING_ERROR_TYPES

        tasks = []
        for golden_path in golden_files:
            logger.info(f"处理文件: {golden_path.name}")
            for i in range(tasks_per_file):
                try:
                    error_type = random.choice(error_types)
                    task = self.generate(
                        golden_path=golden_path,
                        output_dir=output_dir,
                        error_type=error_type
                    )
                    tasks.append(task)
                except Exception as e:
                    logger.error(f"生成任务失败: {golden_path.name} - {e}")
                    continue

        logger.info(f"✓ 批量生成完成: {len(tasks)}/{len(golden_files) * tasks_per_file}")
        return tasks

    def export_task_json(self, task: DebuggingTask, output_path: Path):
        """导出任务为JSON格式（符合task.schema.json）"""
        # answer_position由注入的错误单元格地址构成，S5评分依赖此字段
        # 计算accuracy，留空会导致total_cells=0从而accuracy恒为0
        answer_position = [err.cell_address for err in task.injected_errors]

        task_dict = {
            "task_id": task.task_id,
            "workbook_id": task.workbook_id,
            "type": "Debugging",
            "sub_type": task.error_type_primary,
            "difficulty": "L2",  # TODO: 自动评估难度
            "instruction": task.instruction,
            "input_path": str(task.input_path),
            "golden_path": str(task.golden_path),
            "answer_position": answer_position,
            "criteria": [],  # Debugging类型不需要criteria
            "metadata": {
                **task.metadata,
                "error_count": len(task.injected_errors),
                "injected_errors": [
                    {
                        "type": err.error_type,
                        "cell": err.cell_address,
                        "description": err.description
                    }
                    for err in task.injected_errors
                ]
            }
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(task_dict, f, indent=2, ensure_ascii=False)

        logger.info(f"✓ 导出任务JSON: {output_path}")


def main():
    """测试生成器"""
    import sys
    logging.basicConfig(level=logging.DEBUG)

    if len(sys.argv) < 3:
        print("用法: python debugging_generator.py <golden.xlsx> <output_dir> [--error-type TYPE]")
        sys.exit(1)

    golden_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    # 解析error_type参数
    error_type = None
    if len(sys.argv) >= 5 and sys.argv[3] == "--error-type":
        error_type = sys.argv[4]

    generator = DebuggingGenerator(seed=42)
    task = generator.generate(golden_path, output_dir, error_type=error_type)

    print(f"\n生成任务:")
    print(f"  Task ID: {task.task_id}")
    print(f"  错误类型: {task.error_type_primary}")
    print(f"  错误数量: {len(task.injected_errors)}")
    print(f"\n指令:")
    print(f"  {task.instruction}")
    print(f"\n注入的错误:")
    for err in task.injected_errors:
        print(f"  - {err.cell_address}: {err.description}")

    # 导出JSON
    json_path = output_dir / f"{task.task_id}.json"
    generator.export_task_json(task, json_path)


if __name__ == "__main__":
    main()
