"""
S1 结构解析器 - 产出四份元数据：
  1. workbook_map   - sheet角色、used_range、header、时间轴
  2. formula_graph  - R1C1归一化、公式家族、依赖图
  3. style_map      - 颜色、合并区域、命名区域
  4. invariants     - 资产负债表平衡、三表勾稽、合计行
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, column_index_from_string

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import PARSE_CONFIG


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

class WorkbookMap:
    def __init__(self, workbook_id: str):
        self.workbook_id = workbook_id
        self.sheets: List[Dict] = []

    def to_dict(self) -> Dict:
        return {"workbook_id": self.workbook_id, "sheets": self.sheets}


class FormulaGraph:
    def __init__(self, workbook_id: str):
        self.workbook_id = workbook_id
        self.cells: Dict[str, Dict] = {}          # addr -> cell_info
        self.edges: List[Dict] = []               # {from, to, cross_sheet}
        self.formula_families: Dict[str, Dict] = {}
        self.broken_references: List[str] = []
        self.hardcoded_constants: List[Dict] = []

    def to_dict(self) -> Dict:
        return {
            "workbook_id": self.workbook_id,
            "cells": self.cells,
            "edges": self.edges,
            "formula_families": self.formula_families,
            "broken_references": self.broken_references,
            "hardcoded_constants": self.hardcoded_constants,
        }


class StyleMap:
    def __init__(self, workbook_id: str):
        self.workbook_id = workbook_id
        self.styles: Dict[str, Dict] = {}         # addr -> style_info
        self.merged_regions: List[str] = []
        self.named_ranges: Dict[str, str] = {}

    def to_dict(self) -> Dict:
        return {
            "workbook_id": self.workbook_id,
            "styles": self.styles,
            "merged_regions": self.merged_regions,
            "named_ranges": self.named_ranges,
        }


class Invariants:
    def __init__(self, workbook_id: str):
        self.workbook_id = workbook_id
        self.checks: List[Dict] = []

    def to_dict(self) -> Dict:
        return {"workbook_id": self.workbook_id, "checks": self.checks}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _cell_addr(sheet_name: str, cell) -> str:
    return f"{sheet_name}!{cell.coordinate}"


def _color_to_hex(color) -> Optional[str]:
    if color is None:
        return None
    try:
        if hasattr(color, "rgb") and color.rgb and color.rgb != "00000000":
            return f"#{color.rgb[2:]}"   # ARGB -> RGB
        if hasattr(color, "theme"):
            return f"theme:{color.theme}"
    except Exception:
        pass
    return None


def _used_range(ws) -> str:
    """返回 'A1:ZZ999' 格式的used range"""
    if ws.min_row is None:
        return "A1:A1"
    return (f"{get_column_letter(ws.min_column)}{ws.min_row}:"
            f"{get_column_letter(ws.max_column)}{ws.max_row}")


def _normalize_r1c1(formula: str, row: int, col: int) -> str:
    """
    把 A1 引用替换成 R[+n]C[+m] 相对形式，方便公式家族聚类。
    仅处理简单 A1 和 $A$1 两种格式，不处理跨表引用（保留原文）。
    """
    def replace_ref(m: re.Match) -> str:
        prefix = m.group(1) or ""  # 可能含 sheet 前缀，直接保留
        if "!" in prefix:
            return m.group(0)  # 跨表引用不归一化

        col_str = m.group(2)
        row_str = m.group(3)
        abs_col = col_str.startswith("$")
        abs_row = row_str.startswith("$")
        c_idx = column_index_from_string(col_str.lstrip("$"))
        r_idx = int(row_str.lstrip("$"))

        c_part = str(c_idx) if abs_col else f"[{c_idx - col:+d}]"
        r_part = str(r_idx) if abs_row else f"[{r_idx - row:+d}]"
        return f"R{r_part}C{c_part}"

    pattern = re.compile(
        r"([A-Za-z0-9_]+!)?"       # 可选的 sheet 前缀
        r"(\$?[A-Z]{1,3})"         # 列
        r"(\$?[0-9]{1,7})",        # 行
        re.IGNORECASE,
    )
    return pattern.sub(replace_ref, formula)


def _formula_family_id(r1c1: str) -> str:
    return hashlib.md5(r1c1.encode()).hexdigest()[:8]


def _parse_cell_refs(formula: str, sheet_name: str) -> List[Tuple[str, str, bool]]:
    """
    从公式中提取引用的单元格地址列表。
    返回 [(sheet, coord, cross_sheet), ...]
    仅提取单个单元格（非区域），简化实现。
    """
    refs = []
    # 跨表引用：Sheet1!A1 或 'Sheet 1'!A1
    cross_pattern = re.compile(
        r"'?([^'!]+)'?!(\$?[A-Z]{1,3}\$?[0-9]{1,7})", re.IGNORECASE
    )
    for m in cross_pattern.finditer(formula):
        refs.append((m.group(1), m.group(2).replace("$", ""), True))

    # 同表引用：A1（排除已匹配的跨表部分）
    clean = cross_pattern.sub("", formula)
    local_pattern = re.compile(r"\$?([A-Z]{1,3})\$?([0-9]{1,7})", re.IGNORECASE)
    for m in local_pattern.finditer(clean):
        coord = m.group(1).upper() + m.group(2)
        refs.append((sheet_name, coord, False))

    return refs


# ---------------------------------------------------------------------------
# 主解析器
# ---------------------------------------------------------------------------

class WorkbookParser:
    """S1 结构解析器，解析一个工作簿，返回四份元数据对象。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.workbook_id = self.path.stem
        self._wb_formula = load_workbook(self.path, read_only=True, data_only=False)
        self._wb_value = load_workbook(self.path, read_only=True, data_only=True)

    def close(self):
        self._wb_formula.close()
        self._wb_value.close()

    def parse_all(self) -> Tuple[WorkbookMap, FormulaGraph, StyleMap, Invariants]:
        wmap = self.parse_workbook_map()
        fgraph = self.parse_formula_graph()
        smap = self.parse_style_map()
        invs = self.parse_invariants(wmap, fgraph)
        return wmap, fgraph, smap, invs

    # ------------------------------------------------------------------
    # 1. workbook_map
    # ------------------------------------------------------------------

    def parse_workbook_map(self) -> WorkbookMap:
        wmap = WorkbookMap(self.workbook_id)
        for sheet_name in self._wb_formula.sheetnames:
            ws = self._wb_formula[sheet_name]
            sheet_info = self._parse_sheet_map(ws, sheet_name)
            wmap.sheets.append(sheet_info)
        return wmap

    def _parse_sheet_map(self, ws, sheet_name: str) -> Dict:
        used = _used_range(ws)
        role = self._detect_sheet_role(ws, sheet_name)
        header_row, header_col = self._detect_header(ws)
        time_axis = self._detect_time_axis(ws, header_row)
        unit = self._detect_unit(ws)
        regions = self._detect_regions(ws)

        return {
            "name": sheet_name,
            "role": role,
            "used_range": used,
            "header_row": header_row,
            "header_col": header_col,
            "time_axis": time_axis,
            "unit": unit,
            "regions": regions,
        }

    def _detect_sheet_role(self, ws, name: str) -> str:
        name_l = name.lower()
        hidden_keywords = ["helper", "hidden", "lookup", "ref", "data"]
        output_keywords = ["output", "result", "report", "summary", "dashboard"]
        input_keywords = ["input", "assumption", "driver", "param"]
        calc_keywords = ["model", "calc", "computation", "forecast", "projection",
                         "income", "balance", "cash", "pnl", "pl"]
        control_keywords = ["control", "scenario", "switch", "toggle"]

        for kw in control_keywords:
            if kw in name_l:
                return "control"
        for kw in input_keywords:
            if kw in name_l:
                return "input"
        for kw in output_keywords:
            if kw in name_l:
                return "output"
        for kw in calc_keywords:
            if kw in name_l:
                return "calculation"
        for kw in hidden_keywords:
            if kw in name_l:
                return "hidden"

        # 启发式：大量公式 → calculation，少量 → summary，无 → input or unknown
        formula_count = sum(
            1 for row in ws.iter_rows()
            for cell in row
            if cell.value and isinstance(cell.value, str) and cell.value.startswith("=")
        )
        if formula_count > 50:
            return "calculation"
        if formula_count > 5:
            return "summary"
        return "unknown"

    def _detect_header(self, ws) -> Tuple[Optional[int], Optional[int]]:
        """返回 (header_row, header_col)，从第一行/列中找文本最密集的行。"""
        best_row = None
        best_count = 0
        for i, row in enumerate(ws.iter_rows(max_row=10), start=1):
            count = sum(
                1 for c in row
                if c.value and isinstance(c.value, str) and len(c.value.strip()) > 0
            )
            if count > best_count:
                best_count = count
                best_row = i
        return best_row, 1

    def _detect_time_axis(self, ws, header_row: Optional[int]) -> Optional[Dict]:
        if header_row is None:
            return None

        year_pattern = re.compile(r"(19|20)\d{2}")
        date_cols = []
        for cell in ws[header_row]:
            val = str(cell.value) if cell.value is not None else ""
            if year_pattern.search(val):
                date_cols.append(cell.column)

        if len(date_cols) < 2:
            return None

        return {
            "direction": "horizontal",
            "start_col": get_column_letter(date_cols[0]),
            "end_col": get_column_letter(date_cols[-1]),
        }

    def _detect_unit(self, ws) -> Optional[str]:
        unit_patterns = {
            "thousands": re.compile(r"\$?000|thousands|'000|k\b", re.I),
            "millions": re.compile(r"millions|mm\b|\$m\b", re.I),
            "billions": re.compile(r"billions|bn\b|\$b\b", re.I),
        }
        for row in ws.iter_rows(max_row=5):
            for cell in row:
                if cell.value and isinstance(cell.value, str):
                    for unit, pat in unit_patterns.items():
                        if pat.search(cell.value):
                            return unit
        return None

    def _detect_regions(self, ws) -> Dict:
        input_cells, formula_cells, output_cells = [], [], []
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    formula_cells.append(cell.coordinate)
                elif isinstance(cell.value, (int, float)):
                    input_cells.append(cell.coordinate)

        # 最后一列/行的公式单元格视为 output
        if formula_cells:
            output_cells = formula_cells[-min(10, len(formula_cells)):]

        return {
            "input_area": input_cells[:20],
            "formula_area": formula_cells[:20],
            "output_area": output_cells,
        }

    # ------------------------------------------------------------------
    # 2. formula_graph
    # ------------------------------------------------------------------

    def parse_formula_graph(self) -> FormulaGraph:
        fg = FormulaGraph(self.workbook_id)

        for sheet_name in self._wb_formula.sheetnames:
            ws = self._wb_formula[sheet_name]
            for row in ws.iter_rows():
                for cell in row:
                    if not (cell.value and isinstance(cell.value, str)
                            and cell.value.startswith("=")):
                        continue

                    addr = f"{sheet_name}!{cell.coordinate}"
                    formula = cell.value
                    r1c1 = _normalize_r1c1(formula, cell.row, cell.column)
                    fam_id = _formula_family_id(r1c1)

                    fg.cells[addr] = {
                        "formula": formula,
                        "r1c1_normalized": r1c1,
                        "formula_family_id": fam_id,
                        "is_hardcoded": False,
                        "precedents": [],
                        "dependents": [],
                    }

                    # 更新公式家族
                    if fam_id not in fg.formula_families:
                        fg.formula_families[fam_id] = {
                            "r1c1_pattern": r1c1,
                            "member_cells": [],
                            "propagation_direction": "unknown",
                        }
                    fg.formula_families[fam_id]["member_cells"].append(addr)

                    # 提取依赖边
                    refs = _parse_cell_refs(formula, sheet_name)
                    for ref_sheet, ref_coord, cross in refs:
                        ref_addr = f"{ref_sheet}!{ref_coord}"
                        fg.cells[addr]["precedents"].append(ref_addr)
                        fg.edges.append({"from": ref_addr, "to": addr, "cross_sheet": cross})

                # 硬编码常量（数值单元格，无公式）
                    pass

            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None and not (
                        isinstance(cell.value, str) and cell.value.startswith("=")
                    ) and isinstance(cell.value, (int, float)):
                        addr = f"{sheet_name}!{cell.coordinate}"
                        if addr not in fg.cells:
                            fg.hardcoded_constants.append({"cell": addr, "value": cell.value})

        # 反填 dependents
        for edge in fg.edges:
            src = edge["from"]
            dst = edge["to"]
            if src in fg.cells:
                if dst not in fg.cells[src].get("dependents", []):
                    fg.cells[src].setdefault("dependents", []).append(dst)

        # 推断公式家族传播方向
        for fam_id, fam in fg.formula_families.items():
            members = fam["member_cells"]
            if len(members) < 2:
                continue
            rows = set()
            cols = set()
            for m in members:
                parts = m.split("!")
                coord = parts[-1]
                col_m = re.match(r"([A-Z]+)(\d+)", coord)
                if col_m:
                    cols.add(col_m.group(1))
                    rows.add(int(col_m.group(2)))
            if len(rows) > len(cols):
                fam["propagation_direction"] = "vertical"
            elif len(cols) > len(rows):
                fam["propagation_direction"] = "horizontal"
            else:
                fam["propagation_direction"] = "both"

        return fg

    # ------------------------------------------------------------------
    # 3. style_map
    # ------------------------------------------------------------------

    def parse_style_map(self) -> StyleMap:
        sm = StyleMap(self.workbook_id)

        # openpyxl read_only 不支持样式，需重新加载
        wb = load_workbook(self.path, data_only=True)

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            for merge in ws.merged_cells.ranges:
                sm.merged_regions.append(str(merge))

            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is None and cell.font is None:
                        continue
                    addr = f"{sheet_name}!{cell.coordinate}"
                    style: Dict = {}

                    try:
                        if cell.number_format:
                            style["number_format"] = cell.number_format
                        if cell.font:
                            fc = _color_to_hex(cell.font.color)
                            if fc:
                                style["font_color"] = fc
                            if cell.font.bold:
                                style["bold"] = True
                        if cell.fill and cell.fill.fgColor:
                            fc2 = _color_to_hex(cell.fill.fgColor)
                            if fc2:
                                style["fill_color"] = fc2
                        if cell.border:
                            has_border = any([
                                cell.border.left and cell.border.left.border_style,
                                cell.border.right and cell.border.right.border_style,
                                cell.border.top and cell.border.top.border_style,
                                cell.border.bottom and cell.border.bottom.border_style,
                            ])
                            if has_border:
                                style["has_border"] = True
                    except Exception:
                        pass

                    coord_str = cell.coordinate
                    is_merged = any(
                        coord_str in str(mr) for mr in ws.merged_cells.ranges
                    )
                    if is_merged:
                        style["is_merged"] = True

                    if style:
                        sm.styles[addr] = style

        # 命名区域
        try:
            for name, defn in wb.defined_names.items():
                sm.named_ranges[name] = str(defn.attr_text)
        except Exception:
            pass

        wb.close()
        return sm

    # ------------------------------------------------------------------
    # 4. invariants
    # ------------------------------------------------------------------

    def parse_invariants(self, wmap: WorkbookMap, fg: FormulaGraph) -> Invariants:
        inv = Invariants(self.workbook_id)
        wb = self._wb_value

        for sheet_info in wmap.sheets:
            sheet_name = sheet_info["name"]
            ws = wb[sheet_name]
            self._detect_sum_equals_total(ws, sheet_name, inv)
            self._detect_balance_sheet(ws, sheet_name, inv)

        return inv

    def _detect_sum_equals_total(self, ws, sheet_name: str, inv: Invariants):
        """检测 SUM(范围) == 合计行 的关系。"""
        total_patterns = re.compile(
            r"^(total|subtotal|sum|合计|小计|总计)\s*", re.I
        )
        for row in ws.iter_rows():
            label_cell = row[0]
            if label_cell.value and isinstance(label_cell.value, str):
                if total_patterns.match(label_cell.value.strip()):
                    # 找到合计行，取第一个数值列
                    for cell in row[1:]:
                        if isinstance(cell.value, (int, float)):
                            inv.checks.append({
                                "name": f"{sheet_name}_sum_total_{cell.coordinate}",
                                "type": "sum_equals_total",
                                "cell": f"{sheet_name}!{cell.coordinate}",
                                "related_cells": [],
                                "expected": str(cell.value),
                                "tolerance": 0.01,
                                "rationale": f"合计行 '{label_cell.value}' 应等于上方各项之和",
                            })
                            break

    def _detect_balance_sheet(self, ws, sheet_name: str, inv: Invariants):
        """检测资产 = 负债 + 权益 的平衡关系。"""
        asset_pat = re.compile(r"^total\s+assets?$", re.I)
        liab_pat = re.compile(r"^total\s+(liabilities?\s*(and\s*equity)?|负债)", re.I)
        equity_pat = re.compile(r"^(total\s+)?(equity|shareholders|stockholders|权益)", re.I)

        assets_cell = liab_cell = equity_cell = None
        for row in ws.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str):
                    v = cell.value.strip()
                    if asset_pat.match(v):
                        assets_cell = cell.coordinate
                    elif liab_pat.match(v):
                        liab_cell = cell.coordinate
                    elif equity_pat.match(v):
                        equity_cell = cell.coordinate

        if assets_cell and (liab_cell or equity_cell):
            related = [c for c in [liab_cell, equity_cell] if c]
            inv.checks.append({
                "name": f"{sheet_name}_balance_sheet_balance",
                "type": "balance_sheet_balance",
                "cell": f"{sheet_name}!{assets_cell}",
                "related_cells": [f"{sheet_name}!{c}" for c in related],
                "expected": "assets == liabilities + equity",
                "tolerance": 0.01,
                "rationale": "资产负债表恒等式",
            })
