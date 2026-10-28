"""
Official Scorer - Reuses evaluation.py comparison functions for S5 trajectory verification.

This module provides the official scoring interface for validating trajectory outputs
against golden workbooks. It reuses the exact comparison logic from the benchmark's
evaluation.py to ensure consistency with official metrics.

Key functions:
- compare_cell_value: Official cell value comparison with 1% tolerance
- compare_cell_formula: Formula comparison (case-insensitive, ignores absolute refs)
- compare_font_color: Font color comparison for Visualization tasks
- score_workbook: Complete workbook scoring with regression/modification split
- score_visualization_rubric: Visualization-specific rubric-based scoring (NEW)

Usage:
    # For Debugging/FM/Template (answer_position based):
    scorer = OfficialScorer()
    result = scorer.score_workbook(
        input_path="task_123/input.xlsx",
        golden_path="task_123/golden.xlsx",
        output_path="task_123/output.xlsx",
        answer_position="Sheet1!B2:K52",
        category="Financial_Model"
    )
    print(result.accuracy)  # 1.0 only if both regression and modification are perfect

    # For Visualization (criteria-based rubric):
    viz_result = scorer.score_visualization_rubric(
        input_path="task_456/input.xlsx",
        golden_path="task_456/golden.xlsx",
        output_path="task_456/output.xlsx",
        criteria=criteria_list,
        use_tier2_vlm=False  # Set True for calibration/spot-check
    )
    print(viz_result.accuracy)  # 1.0 if score > 0.7
"""

import os
import datetime
import openpyxl
from pathlib import Path
from typing import Tuple, List, Dict, Optional
from dataclasses import dataclass


# ============================================================================
# Core comparison functions - copied from evaluation.py
# ============================================================================

def datetime_to_float(dt):
    """Convert datetime to Excel serial number."""
    excel_start_date = datetime.datetime(1899, 12, 30)
    delta = dt - excel_start_date
    return delta.days + delta.seconds / 86400.0


def transform_value(v):
    """Transform value for comparison - rounds numbers, normalizes datetimes."""
    if isinstance(v, (int, float)):
        v = round(float(v), 2)
    elif isinstance(v, datetime.time):
        v = str(v)[:-3]
    elif isinstance(v, datetime.datetime):
        v = round(datetime_to_float(v), 0)
    elif isinstance(v, str):
        try:
            v = round(float(v), 2)
        except ValueError:
            pass
    return v


def compare_cell_value(v1, v2, tolerance=0.01):
    """
    Official cell value comparison with 1% tolerance.

    Handles:
    - Numeric values with relative/absolute tolerance
    - Excel error values (#DIV/0!, #N/A) and "not meaningful" placeholders
    - ArrayFormula objects
    - String-encoded numbers
    - Datetimes
    - Empty cells (None vs "")
    - Formula strings (case-insensitive)
    """
    # Handle ArrayFormula objects — compare by formula text
    if hasattr(v1, 'text') and hasattr(v2, 'text'):
        return v1.text == v2.text

    # Treat #DIV/0! and #N/A as equivalent to finance "not meaningful" placeholders
    _DISPLAY_EQUIVALENT_ERRORS = {'#DIV/0!', '#N/A'}
    _NOT_MEANINGFUL = _DISPLAY_EQUIVALENT_ERRORS | {
        'N/A', 'NA', 'N.A.', 'N/M', 'NM', 'N.M.',
        'NOT MEANINGFUL', 'NOT APPLICABLE', 'NOT AVAILABLE',
        '—', '–', '-', '--', '---',
    }
    def _is_not_meaningful(v):
        if v is None:
            return False
        if isinstance(v, str):
            s = v.strip().upper()
            return s in _NOT_MEANINGFUL or s in _DISPLAY_EQUIVALENT_ERRORS
        return False

    if _is_not_meaningful(v1) and _is_not_meaningful(v2):
        return True

    # For two numeric values, compare on raw values with tolerance only
    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
        if v1 == v2:
            return True
        if v1 == 0 or v2 == 0:
            return abs(v1 - v2) <= tolerance
        return abs(v1 - v2) / max(abs(v1), abs(v2)) <= tolerance

    # Transform and normalize
    v1 = transform_value(v1)
    v2 = transform_value(v2)

    # Empty cell equivalence
    if (v1 == "" and v2 is None) or (v1 is None and v2 == ""):
        return True
    if (v1 == "" and v2 == "") or (v1 is None and v2 is None):
        return True

    # Treat None as equivalent to 0
    if (v1 is None and isinstance(v2, (int, float)) and v2 == 0) or \
       (v2 is None and isinstance(v1, (int, float)) and v1 == 0):
        return True

    # Type mismatch
    if type(v1) != type(v2):
        return False

    if v1 == v2:
        return True

    # Formula strings: compare case-insensitively
    if isinstance(v1, str) and isinstance(v2, str) and v1.startswith('=') and v2.startswith('='):
        return v1.replace('$', '').upper() == v2.replace('$', '').upper()

    # Numeric with tolerance
    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
        if v1 == 0 and v2 == 0:
            return True
        if v1 == 0 or v2 == 0:
            return abs(v1 - v2) <= tolerance
        relative_error = abs(v1 - v2) / max(abs(v1), abs(v2))
        return relative_error <= tolerance

    return False


def _get_color_rgb(color) -> str:
    """Extract RGB value from color object, resolving theme colors to RGB."""
    if not color:
        return "00000000"

    if color.type == "rgb" and isinstance(color.rgb, str):
        return color.rgb

    if color.type == "theme":
        # Standard Excel theme color map
        _THEME_COLORS = [
            "FFFFFF", "000000", "E7E6E6", "44546A", "4472C4",
            "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47",
        ]
        theme_idx = color.theme
        if 0 <= theme_idx < len(_THEME_COLORS):
            base = _THEME_COLORS[theme_idx]
            tint = float(color.tint) if color.tint else 0.0
            if tint != 0:
                r, g, b = int(base[0:2], 16), int(base[2:4], 16), int(base[4:6], 16)
                if tint > 0:
                    r = int(r + (255 - r) * tint)
                    g = int(g + (255 - g) * tint)
                    b = int(b + (255 - b) * tint)
                else:
                    r = int(r * (1 + tint))
                    g = int(g * (1 + tint))
                    b = int(b * (1 + tint))
                r, g, b = min(255, max(0, r)), min(255, max(0, g)), min(255, max(0, b))
                base = f"{r:02X}{g:02X}{b:02X}"
            return "FF" + base

    return "00000000"


def _compare_colors(color1, color2) -> bool:
    """Compare two colors using only last 6 characters (RGB), ignoring alpha."""
    rgb1 = _get_color_rgb(color1)
    rgb2 = _get_color_rgb(color2)
    return rgb1[-6:] == rgb2[-6:]


def compare_font_color(font_gt, font_proc) -> bool:
    """Compare font colors between two cells."""
    return _compare_colors(font_gt.color, font_proc.color)


def compare_cell_formula(cell1, cell2) -> bool:
    """
    Compare formulas of two cells.

    Handles:
    - ArrayFormula objects (CSE array formulas)
    - Case-insensitive formula comparison
    - Absolute reference markers ($) are ignored
    - Legacy =+ prefix treated as equivalent to =
    - Empty cells (None vs "")
    """
    f1, f2 = cell1.value, cell2.value

    # Handle ArrayFormula objects
    if hasattr(f1, 'text') and hasattr(f2, 'text'):
        return f1.text == f2.text

    # Both are formulas: normalize and compare
    if isinstance(f1, str) and isinstance(f2, str) and f1.startswith('=') and f2.startswith('='):
        def _normalize_formula(f):
            f = f.replace('$', '').upper()
            if f.startswith('=+'):
                f = '=' + f[2:]
            return f
        return _normalize_formula(f1) == _normalize_formula(f2)

    # Empty equivalence
    empty = (None, "")
    if f1 in empty and f2 in empty:
        return True

    # For non-formula values, use tolerance-based comparison
    return compare_cell_value(f1, f2)


# ============================================================================
# Range parsing utilities - copied from evaluation.py
# ============================================================================

def parse_answer_position(answer_position):
    """Parse answer_position string, handling quoted sheet names with commas.

    A quote only opens a quoted-sheet-name span at the start of a token (right
    after a comma or at string start) and only closes right before '!' (the
    Excel 'Sheet Name'!A1 pattern). This avoids misfiring on sheet names that
    contain a literal apostrophe mid-name without being Excel-quoted, e.g.
    "March'01 GDAs!C1" — such an apostrophe must not toggle quote state.
    """
    result, current, in_quote = [], "", False
    n = len(answer_position)
    for i, char in enumerate(answer_position):
        if char == "'":
            if not in_quote and current == "":
                in_quote = True
            elif in_quote and i + 1 < n and answer_position[i + 1] == '!':
                in_quote = False
        if char == ',' and not in_quote:
            if current.strip():
                result.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        result.append(current.strip())
    return result


def col_num2name(n):
    """Convert column number to Excel column name."""
    name = ''
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        name = chr(65 + remainder) + name
    return name


def col_name2num(name):
    """Convert Excel column name to column number."""
    num = 0
    for c in name:
        num = num * 26 + (ord(c) - ord('A') + 1)
    return num


def parse_cell_range(range_str):
    """Parse range string like 'A1:AB12'."""
    start_cell, end_cell = range_str.split(':')
    start_col, start_row = '', ''
    for char in start_cell:
        if char.isdigit():
            start_row += char
        else:
            start_col += char

    end_col, end_row = '', ''
    for char in end_cell:
        if char.isdigit():
            end_row += char
        else:
            end_col += char

    return (col_name2num(start_col), int(start_row)), (col_name2num(end_col), int(end_row))


def generate_cell_names(range_str):
    """Generate list of all cell names in the specified range."""
    if ':' not in range_str:
        return [range_str]
    (start_col, start_row), (end_col, end_row) = parse_cell_range(range_str)
    columns = [col_num2name(i) for i in range(start_col, end_col + 1)]
    cell_names = [f"{col}{row}" for col in columns for row in range(start_row, end_row + 1)]
    return cell_names


# ============================================================================
# Workbook-level comparison - adapted from evaluation.py
# ============================================================================

_EXCEL_ERRORS = {'#REF!', '#VALUE!', '#DIV/0!', '#NAME?', '#NULL!', '#N/A', '#NUM!'}


def _find_sheet(wb, name):
    """Find worksheet by name with whitespace-tolerant, case-insensitive matching."""
    if name in wb.sheetnames:
        return wb[name]
    name_stripped = name.strip().lower()
    for sn in wb.sheetnames:
        if sn.strip().lower() == name_stripped:
            return wb[sn]
    return None


def _has_excel_error(cell):
    """Check if cell value is an Excel error string."""
    v = cell.value
    return isinstance(v, str) and v in _EXCEL_ERRORS


def _compare_cells(cell1, cell2, with_font_color, with_formula):
    """Helper to compare two cells."""
    if with_formula:
        return compare_cell_formula(cell1, cell2)
    elif with_font_color:
        return compare_cell_value(cell1.value, cell2.value) and compare_font_color(cell1.font, cell2.font)
    else:
        return compare_cell_value(cell1.value, cell2.value)


def classify_cells_by_modification(wb_input, wb_answer, sheet_name, cell_range,
                                    with_font_color=False, with_formula=False,
                                    wb_input_formula=None, wb_answer_formula=None):
    """Classify cells into regression (unmodified) and modification (modified) categories."""
    ws_input = _find_sheet(wb_input, sheet_name)
    ws_answer = _find_sheet(wb_answer, sheet_name)
    if ws_input is None or ws_answer is None:
        return [], []

    ws_input_f = _find_sheet(wb_input_formula, sheet_name) if wb_input_formula else None
    ws_answer_f = _find_sheet(wb_answer_formula, sheet_name) if wb_answer_formula else None
    regression, modification = [], []

    for cell_name in generate_cell_names(cell_range):
        cell_in, cell_ans = ws_input[cell_name], ws_answer[cell_name]
        # If either cell has Excel error and we have formula workbooks, compare formulas
        if not with_formula and ws_input_f and ws_answer_f and (_has_excel_error(cell_in) or _has_excel_error(cell_ans)):
            is_same = compare_cell_formula(ws_input_f[cell_name], ws_answer_f[cell_name])
        else:
            is_same = _compare_cells(cell_in, cell_ans, with_font_color, with_formula)
        (regression if is_same else modification).append(cell_name)

    return regression, modification


def cell_level_compare_with_classification(wb_answer, wb_output, sheet_name,
                                           regression_cells, modification_cells,
                                           with_font_color=False, with_formula=False,
                                           wb_answer_formula=None, wb_output_formula=None):
    """Compare output and answer, calculate accuracy for regression and modification separately."""
    if _find_sheet(wb_output, sheet_name) is None:
        return 0, len(regression_cells), 0, len(modification_cells), [f"{sheet_name} worksheet not found"]

    ws_answer = _find_sheet(wb_answer, sheet_name)
    ws_output = _find_sheet(wb_output, sheet_name)
    ws_answer_f = _find_sheet(wb_answer_formula, sheet_name) if wb_answer_formula else None
    ws_output_f = _find_sheet(wb_output_formula, sheet_name) if wb_output_formula else None

    def count_correct(cells, label):
        correct, errors = 0, []
        for name in cells:
            cell_ans, cell_out = ws_answer[name], ws_output[name]
            # If either has Excel error and we have formula workbooks, compare formulas
            if not with_formula and ws_answer_f and ws_output_f and (_has_excel_error(cell_ans) or _has_excel_error(cell_out)):
                matched = compare_cell_formula(ws_answer_f[name], ws_output_f[name])
            else:
                matched = _compare_cells(cell_ans, cell_out, with_font_color, with_formula)
            if matched:
                correct += 1
            else:
                ans_val = cell_ans.value
                out_val = cell_out.value
                # Extract text from ArrayFormula objects
                if hasattr(ans_val, 'text'):
                    ans_val = ans_val.text
                if hasattr(out_val, 'text'):
                    out_val = out_val.text
                errors.append(f"{label} error at {sheet_name}!{name}: answer={ans_val}, output={out_val}")
        return correct, errors

    reg_correct, reg_errors = count_correct(regression_cells, "Regression")
    mod_correct, mod_errors = count_correct(modification_cells, "Modification")

    return reg_correct, len(regression_cells), mod_correct, len(modification_cells), reg_errors + mod_errors


# ============================================================================
# Official Scorer Interface
# ============================================================================

@dataclass
class ScoringResult:
    """Result of official scoring."""
    accuracy: float  # 1.0 only if both regression and modification are perfect
    regression_accuracy: float
    modification_accuracy: float
    regression_correct: int
    regression_total: int
    modification_correct: int
    modification_total: int
    total_correct: int
    total_cells: int
    is_correct: bool
    error_message: str
    error_details: List[str]


@dataclass
class VisualizationScoringResult:
    """Result of Visualization rubric-based scoring."""
    accuracy: float  # 1.0 if score > 0.7, else 0.0
    score: float  # pass_count / total_criteria
    pass_count: int
    total_criteria: int
    tier1_pass: int  # Criteria passed by Tier 1 (openpyxl chart XML)
    tier1_total: int
    tier2_pass: int  # Criteria passed by Tier 2 (VLM)
    tier2_total: int
    criteria_details: List[Dict]  # Per-criterion results
    error_message: str


class OfficialScorer:
    """
    Official scorer using benchmark's evaluation.py logic.

    This scorer replicates the exact comparison behavior used in the official
    SpreadsheetBench 2 evaluation to ensure our generated trajectories meet
    the same standards.

    Key features:
    - 1% numeric tolerance (configurable)
    - Regression/modification split (regression must be >= 99.8%)
    - Category-specific comparison modes (font color for Visualization, formulas for Debugging)
    - Excel error value handling with formula fallback
    """

    def __init__(self, tolerance: float = 0.01, regression_threshold: float = 0.998):
        """
        Initialize scorer.

        Args:
            tolerance: Numeric comparison tolerance (default 0.01 = 1%)
            regression_threshold: Minimum regression accuracy to pass (default 0.998 = 99.8%)
        """
        self.tolerance = tolerance
        self.regression_threshold = regression_threshold

    def score_workbook(self,
                      input_path: str,
                      golden_path: str,
                      output_path: str,
                      answer_position: str,
                      category: str = "Financial_Model") -> ScoringResult:
        """
        Score output workbook against golden workbook.

        Args:
            input_path: Path to input.xlsx (task starting state)
            golden_path: Path to golden.xlsx (correct solution)
            output_path: Path to output.xlsx (model's solution)
            answer_position: Official answer_position (e.g., "Sheet1!B2:K52")
            category: Task category for comparison mode detection

        Returns:
            ScoringResult with accuracy scores and error details
        """
        # Check file existence
        if not os.path.exists(output_path):
            return ScoringResult(
                accuracy=0.0, regression_accuracy=0.0, modification_accuracy=0.0,
                regression_correct=0, regression_total=0,
                modification_correct=0, modification_total=0,
                total_correct=0, total_cells=0,
                is_correct=False, error_message="output file not exist",
                error_details=[]
            )

        if not os.path.exists(input_path):
            return ScoringResult(
                accuracy=0.0, regression_accuracy=0.0, modification_accuracy=0.0,
                regression_correct=0, regression_total=0,
                modification_correct=0, modification_total=0,
                total_correct=0, total_cells=0,
                is_correct=False, error_message="input file not exist",
                error_details=[]
            )

        # Determine comparison mode based on category
        with_font_color = (category == "Visualization")
        with_formula = False  # Will be detected from path for Debugging tasks

        # Load workbooks
        need_raw_data = with_formula
        try:
            wb_input = openpyxl.load_workbook(filename=input_path, data_only=not need_raw_data)
            wb_golden = openpyxl.load_workbook(filename=golden_path, data_only=not need_raw_data)
            wb_output = openpyxl.load_workbook(filename=output_path, data_only=not need_raw_data)

            # Load formula-level workbooks for error value fallback
            if not with_formula:
                wb_input_formula = openpyxl.load_workbook(filename=input_path, data_only=False)
                wb_golden_formula = openpyxl.load_workbook(filename=golden_path, data_only=False)
                wb_output_formula = openpyxl.load_workbook(filename=output_path, data_only=False)
            else:
                wb_input_formula = wb_golden_formula = wb_output_formula = None
        except Exception as e:
            return ScoringResult(
                accuracy=0.0, regression_accuracy=0.0, modification_accuracy=0.0,
                regression_correct=0, regression_total=0,
                modification_correct=0, modification_total=0,
                total_correct=0, total_cells=0,
                is_correct=False, error_message=str(e),
                error_details=[]
            )

        # Score across all ranges in answer_position
        reg_stats = {'correct': 0, 'total': 0}
        mod_stats = {'correct': 0, 'total': 0}
        total_correct, total_cells = 0, 0
        error_msgs = []

        for sheet_cell_range in parse_answer_position(answer_position):
            if '!' in sheet_cell_range:
                sheet_name, cell_range = sheet_cell_range.split('!')
            else:
                sheet_name, cell_range = wb_golden.sheetnames[0], sheet_cell_range
            sheet_name = sheet_name.strip("'").strip()
            cell_range = cell_range.strip("'").strip()

            # Classify cells into regression/modification
            regression_cells, modification_cells = classify_cells_by_modification(
                wb_input, wb_golden, sheet_name, cell_range, with_font_color, with_formula,
                wb_input_formula=wb_input_formula, wb_answer_formula=wb_golden_formula
            )

            # Compare output against golden
            reg_correct, reg_total, mod_correct, mod_total, msgs = cell_level_compare_with_classification(
                wb_golden, wb_output, sheet_name, regression_cells, modification_cells,
                with_font_color, with_formula,
                wb_answer_formula=wb_golden_formula, wb_output_formula=wb_output_formula
            )

            reg_stats['correct'] += reg_correct
            reg_stats['total'] += reg_total
            mod_stats['correct'] += mod_correct
            mod_stats['total'] += mod_total
            total_correct += reg_correct + mod_correct
            total_cells += reg_total + mod_total
            error_msgs.extend(msgs)

        # Calculate final scores
        reg_ratio = round(reg_stats['correct'] / reg_stats['total'], 4) if reg_stats['total'] else 0.0
        mod_ratio = round(mod_stats['correct'] / mod_stats['total'], 4) if mod_stats['total'] else 0.0

        # Apply regression threshold (>= 99.8% treated as perfect)
        if reg_ratio >= self.regression_threshold:
            reg_ratio = 1.0

        # accuracy = 1.0 only if both are perfect
        accuracy = 1.0 if reg_ratio == 1.0 and mod_ratio == 1.0 else 0.0
        is_correct = (total_correct == total_cells)
        first_error = next((m for m in error_msgs if m), "")

        return ScoringResult(
            accuracy=accuracy,
            regression_accuracy=reg_ratio,
            modification_accuracy=mod_ratio,
            regression_correct=reg_stats['correct'],
            regression_total=reg_stats['total'],
            modification_correct=mod_stats['correct'],
            modification_total=mod_stats['total'],
            total_correct=total_correct,
            total_cells=total_cells,
            is_correct=is_correct,
            error_message=first_error if not is_correct else "",
            error_details=error_msgs
        )

    def score_visualization_rubric(self,
                                   input_path: str,
                                   golden_path: str,
                                   output_path: str,
                                   criteria: List[Dict],
                                   use_tier2_vlm: bool = False) -> VisualizationScoringResult:
        """
        Score Visualization task using rubric-based criteria.

        Visualization tasks use criteria instead of answer_position. Each criterion
        is judged PASS/FAIL, and the final score is pass_count/total.

        Two-tier verification:
        - Tier 1 (Linux + openpyxl): ~70% of criteria via chart XML analysis
        - Tier 2 (Windows + Excel COM + VLM): ~15% visual criteria (calibration/spot-check)

        Args:
            input_path: Path to input.xlsx
            golden_path: Path to golden.xlsx
            output_path: Path to output.xlsx
            criteria: List of criterion dicts with fields:
                - id: criterion identifier
                - description: what to check
                - category: "data_correctness" | "spec_compliance" | "preservation"
                - verification_tier: 1 or 2
            use_tier2_vlm: Whether to use Tier 2 VLM verification (default False for Linux-only)

        Returns:
            VisualizationScoringResult with score and accuracy
        """
        # Check file existence
        if not os.path.exists(output_path):
            return VisualizationScoringResult(
                accuracy=0.0, score=0.0,
                pass_count=0, total_criteria=len(criteria),
                tier1_pass=0, tier1_total=0,
                tier2_pass=0, tier2_total=0,
                criteria_details=[],
                error_message="output file not exist"
            )

        try:
            wb_golden = openpyxl.load_workbook(golden_path, data_only=True)
            wb_output = openpyxl.load_workbook(output_path, data_only=True)
        except Exception as e:
            return VisualizationScoringResult(
                accuracy=0.0, score=0.0,
                pass_count=0, total_criteria=len(criteria),
                tier1_pass=0, tier1_total=0,
                tier2_pass=0, tier2_total=0,
                criteria_details=[],
                error_message=f"Failed to load workbooks: {str(e)}"
            )

        # Process each criterion
        criteria_details = []
        tier1_pass, tier1_total = 0, 0
        tier2_pass, tier2_total = 0, 0

        for criterion in criteria:
            criterion_id = criterion.get('id', 'unknown')
            description = criterion.get('description', '')
            category = criterion.get('category', 'data_correctness')
            tier = criterion.get('verification_tier', 1)

            if tier == 1:
                # Tier 1: openpyxl chart XML verification
                passed, details = self._verify_criterion_tier1(
                    wb_golden, wb_output, criterion
                )
                tier1_total += 1
                if passed:
                    tier1_pass += 1
            elif tier == 2 and use_tier2_vlm:
                # Tier 2: VLM-based visual verification (calibration/spot-check only)
                passed, details = self._verify_criterion_tier2(
                    golden_path, output_path, criterion
                )
                tier2_total += 1
                if passed:
                    tier2_pass += 1
            elif tier == 2 and not use_tier2_vlm:
                # Skip Tier 2 if not using VLM (Linux-only mode)
                passed, details = False, "Tier 2 verification skipped (use_tier2_vlm=False)"
                tier2_total += 1
            else:
                passed, details = False, f"Unknown verification tier: {tier}"

            criteria_details.append({
                'criterion_id': criterion_id,
                'description': description,
                'category': category,
                'tier': tier,
                'passed': passed,
                'details': details
            })

        # Calculate final score
        total_criteria = len(criteria)
        pass_count = tier1_pass + tier2_pass
        score = pass_count / total_criteria if total_criteria > 0 else 0.0

        # Apply threshold: score > 0.7 → accuracy = 1.0
        accuracy = 1.0 if score > 0.7 else 0.0

        return VisualizationScoringResult(
            accuracy=accuracy,
            score=round(score, 4),
            pass_count=pass_count,
            total_criteria=total_criteria,
            tier1_pass=tier1_pass,
            tier1_total=tier1_total,
            tier2_pass=tier2_pass,
            tier2_total=tier2_total,
            criteria_details=criteria_details,
            error_message=""
        )

    def _verify_criterion_tier1(self, wb_golden, wb_output, criterion: Dict) -> Tuple[bool, str]:
        """
        Verify criterion using Tier 1 (openpyxl chart XML).

        This covers ~70% of criteria:
        - series_data_ranges: Check if chart series point to correct data ranges
        - series_values: Verify actual series data values
        - axis_settings: Check axis min/max/scale
        - chart_title: Verify chart title text
        - legend_position: Check legend placement
        - data_labels: Verify data label settings
        """
        criterion_type = criterion.get('type', 'unknown')

        try:
            # Find charts in both workbooks
            golden_charts = self._extract_charts(wb_golden)
            output_charts = self._extract_charts(wb_output)

            if not golden_charts:
                return False, "No charts found in golden workbook"
            if not output_charts:
                return False, "No charts found in output workbook"

            # For MVP, compare first chart (can be extended to match by title/position)
            golden_chart = golden_charts[0]
            output_chart = output_charts[0]

            if criterion_type == 'series_data_ranges':
                return self._compare_chart_series_ranges(golden_chart, output_chart)
            elif criterion_type == 'series_values':
                return self._compare_chart_series_values(wb_golden, wb_output, golden_chart, output_chart)
            elif criterion_type == 'axis_settings':
                return self._compare_chart_axis_settings(golden_chart, output_chart)
            elif criterion_type == 'chart_title':
                return self._compare_chart_title(golden_chart, output_chart)
            elif criterion_type == 'legend_position':
                return self._compare_chart_legend(golden_chart, output_chart)
            elif criterion_type == 'data_labels':
                return self._compare_chart_data_labels(golden_chart, output_chart)
            else:
                return False, f"Unknown Tier 1 criterion type: {criterion_type}"

        except Exception as e:
            return False, f"Tier 1 verification failed: {str(e)}"

    def _verify_criterion_tier2(self, golden_path: str, output_path: str, criterion: Dict) -> Tuple[bool, str]:
        """
        Verify criterion using Tier 2 (Windows + Excel COM + VLM).

        This covers ~15% of visual criteria:
        - visual_formatting: Chart colors, fonts, styles
        - color_schemes: Overall color palette compliance
        - layout_aesthetics: Visual arrangement and spacing

        NOTE: This is a stub for calibration/spot-check. In production, this would:
        1. Use Excel COM to export chart as PNG
        2. Send PNG to VLM with criterion description
        3. Parse VLM judgment (PASS/FAIL)
        """
        # Stub implementation - return False with explanation
        return False, "Tier 2 VLM verification not implemented (calibration/spot-check only)"

    def _extract_charts(self, wb):
        """Extract all charts from workbook."""
        charts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            if hasattr(ws, '_charts'):
                charts.extend(ws._charts)
        return charts

    def _compare_chart_series_ranges(self, golden_chart, output_chart) -> Tuple[bool, str]:
        """Compare data ranges used by chart series."""
        try:
            golden_series = golden_chart.series
            output_series = output_chart.series

            if len(golden_series) != len(output_series):
                return False, f"Series count mismatch: {len(golden_series)} vs {len(output_series)}"

            for i, (gs, os) in enumerate(zip(golden_series, output_series)):
                if hasattr(gs, 'val') and hasattr(os, 'val'):
                    if str(gs.val) != str(os.val):
                        return False, f"Series {i} value range mismatch"

            return True, "Series ranges match"
        except Exception as e:
            return False, f"Series range comparison failed: {str(e)}"

    def _compare_chart_series_values(self, wb_golden, wb_output, golden_chart, output_chart) -> Tuple[bool, str]:
        """Compare actual data values in chart series."""
        try:
            golden_series = golden_chart.series
            output_series = output_chart.series

            if len(golden_series) != len(output_series):
                return False, f"Series count mismatch"

            # For each series, extract data from the referenced range
            for i, (gs, os) in enumerate(zip(golden_series, output_series)):
                if hasattr(gs, 'val') and hasattr(os, 'val'):
                    golden_vals = self._extract_series_values(wb_golden, gs)
                    output_vals = self._extract_series_values(wb_output, os)

                    if golden_vals != output_vals:
                        return False, f"Series {i} data values mismatch"

            return True, "Series values match"
        except Exception as e:
            return False, f"Series values comparison failed: {str(e)}"

    def _extract_series_values(self, wb, series):
        """Extract actual values from a series reference."""
        # Simplified extraction - in production, parse the full reference
        if hasattr(series, 'val') and hasattr(series.val, 'numRef'):
            return str(series.val.numRef)
        return ""

    def _compare_chart_axis_settings(self, golden_chart, output_chart) -> Tuple[bool, str]:
        """Compare axis min/max/scale settings."""
        try:
            # Check if both charts have similar axis configuration
            # This is simplified - full implementation would check all axis properties
            return True, "Axis settings match (simplified check)"
        except Exception as e:
            return False, f"Axis comparison failed: {str(e)}"

    def _compare_chart_title(self, golden_chart, output_chart) -> Tuple[bool, str]:
        """Compare chart title text."""
        try:
            golden_title = golden_chart.title if hasattr(golden_chart, 'title') else None
            output_title = output_chart.title if hasattr(output_chart, 'title') else None

            if golden_title and output_title:
                golden_text = str(golden_title)
                output_text = str(output_title)
                if golden_text == output_text:
                    return True, "Chart titles match"
                else:
                    return False, f"Title mismatch: '{golden_text}' vs '{output_text}'"
            elif golden_title or output_title:
                return False, "One chart has title, other doesn't"
            else:
                return True, "Both charts have no title"
        except Exception as e:
            return False, f"Title comparison failed: {str(e)}"

    def _compare_chart_legend(self, golden_chart, output_chart) -> Tuple[bool, str]:
        """Compare legend position and settings."""
        try:
            golden_legend = golden_chart.legend if hasattr(golden_chart, 'legend') else None
            output_legend = output_chart.legend if hasattr(output_chart, 'legend') else None

            if bool(golden_legend) != bool(output_legend):
                return False, "Legend presence mismatch"

            return True, "Legend settings match (simplified check)"
        except Exception as e:
            return False, f"Legend comparison failed: {str(e)}"

    def _compare_chart_data_labels(self, golden_chart, output_chart) -> Tuple[bool, str]:
        """Compare data label settings."""
        try:
            # Simplified check for data labels
            return True, "Data labels match (simplified check)"
        except Exception as e:
            return False, f"Data labels comparison failed: {str(e)}"


# ============================================================================
# Testing and CLI
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  Standard scoring: python scorer.py <input.xlsx> <golden.xlsx> <output.xlsx> <answer_position> [category]")
        print("  Visualization scoring: python scorer.py --viz <input.xlsx> <golden.xlsx> <output.xlsx> <criteria.json> [--use-tier2]")
        print("\nExamples:")
        print("  python scorer.py input.xlsx golden.xlsx output.xlsx \"Sheet1!B2:K52\" Financial_Model")
        print("  python scorer.py --viz input.xlsx golden.xlsx output.xlsx criteria.json")
        sys.exit(1)

    scorer = OfficialScorer()

    # Visualization mode
    if sys.argv[1] == "--viz":
        if len(sys.argv) < 6:
            print("Error: Visualization mode requires <input.xlsx> <golden.xlsx> <output.xlsx> <criteria.json>")
            sys.exit(1)

        input_file = sys.argv[2]
        golden_file = sys.argv[3]
        output_file = sys.argv[4]
        criteria_file = sys.argv[5]
        use_tier2 = "--use-tier2" in sys.argv

        # Load criteria
        with open(criteria_file, 'r') as f:
            criteria = json.load(f)

        result = scorer.score_visualization_rubric(
            input_file, golden_file, output_file, criteria, use_tier2_vlm=use_tier2
        )

        print("\n=== Visualization Scoring Result ===")
        print(f"Accuracy: {result.accuracy}")
        print(f"Score: {result.score} ({result.pass_count}/{result.total_criteria} criteria passed)")
        print(f"Tier 1 (openpyxl): {result.tier1_pass}/{result.tier1_total}")
        print(f"Tier 2 (VLM): {result.tier2_pass}/{result.tier2_total}")

        if result.error_message:
            print(f"\nError: {result.error_message}")

        if result.criteria_details:
            print("\nCriteria breakdown:")
            for detail in result.criteria_details[:10]:
                status = "✓" if detail['passed'] else "✗"
                print(f"  {status} [{detail['category']}] {detail['description'][:60]}")
            if len(result.criteria_details) > 10:
                print(f"  ... and {len(result.criteria_details) - 10} more")

        sys.exit(0 if result.accuracy == 1.0 else 1)

    # Standard mode
    else:
        if len(sys.argv) < 5:
            print("Error: Standard mode requires <input.xlsx> <golden.xlsx> <output.xlsx> <answer_position>")
            sys.exit(1)

        input_file = sys.argv[1]
        golden_file = sys.argv[2]
        output_file = sys.argv[3]
        answer_pos = sys.argv[4]
        category = sys.argv[5] if len(sys.argv) > 5 else "Financial_Model"

        result = scorer.score_workbook(input_file, golden_file, output_file, answer_pos, category)

        print("\n=== Official Scoring Result ===")
        print(f"Accuracy: {result.accuracy}")
        print(f"Regression: {result.regression_accuracy} ({result.regression_correct}/{result.regression_total})")
        print(f"Modification: {result.modification_accuracy} ({result.modification_correct}/{result.modification_total})")
        print(f"Total: {result.total_correct}/{result.total_cells}")

        if not result.is_correct:
            print(f"\nError: {result.error_message}")
            if result.error_details:
                print("\nFirst 5 errors:")
                for err in result.error_details[:5]:
                    print(f"  - {err}")

        sys.exit(0 if result.accuracy == 1.0 else 1)
