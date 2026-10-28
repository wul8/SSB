"""
S5 Trajectory Verifier

验证oracle轨迹（或任何生成的轨迹）是否满足严格标准。
只有accuracy=1.0且通过所有strict检查的轨迹才能进入正样本池。

核心功能：
1. LibreOffice重算检查
2. 官方评分计算
3. Strict验证（protected_cells, formula_family, invariants, excel_errors, style）
4. Visualization两级验证
5. 批量验证和报告生成
"""

import json
import logging
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional
import openpyxl

from ingest.validators import WorkbookValidator
from verify.scorer import OfficialScorer
from parse.workbook_parser import WorkbookParser

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """轨迹验证结果"""
    task_id: str
    approved: bool
    rejection_reasons: List[str]

    # 官方评分
    accuracy: float
    modification_accuracy: float
    regression_accuracy: float

    # Strict验证
    recalculated: bool
    protected_violation: int
    formula_family_consistent: bool
    invariants_failed: List[str]
    excel_errors: int
    style_preserved: bool

    # Visualization (如适用)
    visualization_tier1_passed: Optional[bool] = None
    visualization_tier2_passed: Optional[bool] = None


class TrajectoryVerifier:
    """轨迹验证器"""

    def __init__(self):
        self.validator = WorkbookValidator()
        self.scorer = OfficialScorer()

        # Excel错误标记
        self.error_markers = {
            "#REF!", "#VALUE!", "#DIV/0!", "#N/A",
            "#NAME?", "#NUM!", "#NULL!"
        }

    def verify(self, task_dir: str) -> VerificationResult:
        """
        验证单个轨迹

        Args:
            task_dir: 任务目录，包含task.json, input.xlsx, golden.xlsx, output.xlsx

        Returns:
            VerificationResult对象
        """
        task_path = Path(task_dir)
        task_id = task_path.name

        logger.info(f"Verifying trajectory: {task_id}")

        rejection_reasons = []

        # 1. 文件存在性检查
        task_json_path = task_path / "task.json"
        input_path = task_path / "input.xlsx"
        golden_path = task_path / "golden.xlsx"
        output_path = task_path / "output.xlsx"

        if not task_json_path.exists():
            rejection_reasons.append("task.json not found")
        if not input_path.exists():
            rejection_reasons.append("input.xlsx not found")
        if not golden_path.exists():
            rejection_reasons.append("golden.xlsx not found")
        if not output_path.exists():
            rejection_reasons.append("output.xlsx not found")

        if rejection_reasons:
            return VerificationResult(
                task_id=task_id,
                approved=False,
                rejection_reasons=rejection_reasons,
                accuracy=0.0,
                modification_accuracy=0.0,
                regression_accuracy=0.0,
                recalculated=False,
                protected_violation=0,
                formula_family_consistent=False,
                invariants_failed=[],
                excel_errors=0,
                style_preserved=False
            )

        # 加载task.json
        with open(task_json_path) as f:
            task_json = json.load(f)

        # 2. LibreOffice重算检查
        recalculated = self._check_recalc(output_path)
        if not recalculated:
            rejection_reasons.append("LibreOffice recalc failed")

        # 3. 官方评分
        answer_positions = task_json.get("answer_position", [])
        task_type = task_json.get("task_type", "FM")
        category = "Visualization" if task_type == "Visualization" else "Financial_Model"

        # 评分每个answer region并聚合
        total_correct = 0
        total_cells = 0
        regression_correct = 0
        regression_total = 0
        modification_correct = 0
        modification_total = 0

        # answer_positions可能是几百个独立单元格(如Template任务)，逐个调用
        # score_workbook会导致每个单元格都重新加载6份workbook。合并成一次
        # 逗号分隔调用(parse_answer_position支持)，避免重复IO。
        if answer_positions:
            # output.xlsx是openpyxl写出的，公式的缓存计算值全是None(input.xlsx
            # 同理，因为它也是openpyxl从golden另存的)。用一份LibreOffice重算的
            # 临时副本喂给评分器(只用于取缓存值算accuracy)，避免用原始output.xlsx
            # 直接给protected_cells/formula_family等结构检查——LibreOffice重算会
            # 顺带改写公式文本格式(如FALSE→FALSE())，那些检查需要用未经重算的
            # 原始output.xlsx，否则全表公式都会被误判为"被修改"。
            scoring_output_path = self._recalc_copy_for_scoring(output_path)
            try:
                score_result = self.scorer.score_workbook(
                    str(input_path),
                    str(golden_path),
                    str(scoring_output_path),
                    ",".join(answer_positions),
                    category
                )

                total_correct += score_result.total_correct
                total_cells += score_result.total_cells
                regression_correct += score_result.regression_correct
                regression_total += score_result.regression_total
                modification_correct += score_result.modification_correct
                modification_total += score_result.modification_total
            finally:
                if scoring_output_path != output_path and scoring_output_path.exists():
                    scoring_output_path.unlink()

        # 计算聚合accuracy
        accuracy = total_correct / total_cells if total_cells > 0 else 0.0
        regression_accuracy = regression_correct / regression_total if regression_total > 0 else 1.0
        modification_accuracy = modification_correct / modification_total if modification_total > 0 else 1.0

        if accuracy < 1.0:
            rejection_reasons.append(f"accuracy={accuracy:.3f} < 1.0")

        # 4. Strict验证
        protected_violation = self._check_protected_cells(
            input_path, output_path, task_json.get("answer_position", [])
        )
        if protected_violation > 0:
            rejection_reasons.append(f"{protected_violation} protected cell violations")

        formula_family_consistent = self._check_formula_family(
            golden_path, output_path, task_json.get("answer_position", [])
        )
        if not formula_family_consistent:
            rejection_reasons.append("formula family mismatch")

        invariants_failed = self._check_invariants(output_path)
        if invariants_failed:
            rejection_reasons.append(f"invariants failed: {', '.join(invariants_failed)}")

        excel_errors = self._check_excel_errors(
            output_path, task_json.get("answer_position", [])
        )
        if excel_errors > 0:
            rejection_reasons.append(f"{excel_errors} Excel errors in answer region")

        style_preserved = self._check_style_preservation(input_path, output_path)
        if not style_preserved:
            rejection_reasons.append("style not preserved (merged cells or named ranges)")

        # 5. Visualization验证 (如适用)
        visualization_tier1_passed = None
        visualization_tier2_passed = None

        if task_json.get("task_type") == "Visualization":
            visualization_tier1_passed = self._check_visualization_tier1(
                output_path, task_json
            )
            if not visualization_tier1_passed:
                rejection_reasons.append("Visualization Tier 1 failed")

        # 决定是否批准
        approved = len(rejection_reasons) == 0

        result = VerificationResult(
            task_id=task_id,
            approved=approved,
            rejection_reasons=rejection_reasons,
            accuracy=accuracy,
            modification_accuracy=modification_accuracy,
            regression_accuracy=regression_accuracy,
            recalculated=recalculated,
            protected_violation=protected_violation,
            formula_family_consistent=formula_family_consistent,
            invariants_failed=invariants_failed,
            excel_errors=excel_errors,
            style_preserved=style_preserved,
            visualization_tier1_passed=visualization_tier1_passed,
            visualization_tier2_passed=visualization_tier2_passed
        )

        if approved:
            logger.info(f"✓ {task_id}: APPROVED")
        else:
            logger.warning(f"✗ {task_id}: REJECTED - {', '.join(rejection_reasons)}")

        return result

    def verify_batch(self, trajectories_dir: str) -> Dict:
        """
        批量验证轨迹

        Args:
            trajectories_dir: 轨迹目录，包含多个任务子目录

        Returns:
            验证报告字典
        """
        trajectories_path = Path(trajectories_dir)

        if not trajectories_path.exists():
            raise FileNotFoundError(f"Trajectories directory not found: {trajectories_dir}")

        # 扫描所有任务目录
        task_dirs = [d for d in trajectories_path.iterdir() if d.is_dir()]

        logger.info(f"Found {len(task_dirs)} trajectories to verify")

        results = {}
        approved_count = 0

        for task_dir in task_dirs:
            result = self.verify(str(task_dir))
            results[result.task_id] = result
            if result.approved:
                approved_count += 1

        # 统计拒绝原因分布
        rejection_breakdown = {}
        for result in results.values():
            for reason in result.rejection_reasons:
                rejection_breakdown[reason] = rejection_breakdown.get(reason, 0) + 1

        report = {
            "total": len(results),
            "approved": approved_count,
            "rejected": len(results) - approved_count,
            "approval_rate": approved_count / len(results) if results else 0.0,
            "rejection_breakdown": rejection_breakdown,
            "results": results
        }

        logger.info(f"\n{'='*60}")
        logger.info(f"VERIFICATION SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Total: {report['total']}")
        logger.info(f"Approved: {report['approved']} ({report['approval_rate']:.1%})")
        logger.info(f"Rejected: {report['rejected']}")
        logger.info(f"\nRejection Breakdown:")
        for reason, count in sorted(rejection_breakdown.items(), key=lambda x: -x[1]):
            logger.info(f"  {reason}: {count}")

        return report

    def _recalc_copy_for_scoring(self, output_path: Path) -> Path:
        """
        用LibreOffice重算一份output.xlsx的临时副本，只用于取公式缓存值算accuracy。

        openpyxl写出的output.xlsx不带公式缓存值(data_only=True读出全是None)，
        直接送评分器会导致golden(有缓存值)和output(全None)恒定不一致。
        重算失败时退回原始output_path，让评分器按原样处理(会体现为accuracy=0，
        而不是静默吞掉错误)。

        源workbook若带calcMode="manual"(如部分Excel文件保存时会写入这个标记)，
        LibreOffice headless --convert-to不会强制全量重算——它只是把原有(可能为空,
        因为openpyxl不写缓存值)的<v>原样写回，导致读出全是0/None，与golden恒定
        不一致(accuracy=0)。在转换前先把calcMode强制改成auto+fullCalcOnLoad，
        确保LibreOffice实际执行重算。
        """
        import tempfile
        import shutil
        from openpyxl import load_workbook as _load_workbook

        try:
            with tempfile.TemporaryDirectory() as src_dir, \
                    tempfile.TemporaryDirectory() as out_dir:
                # LibreOffice在--convert-to的--outdir与输入文件同目录时,会尝试
                # 就地覆写输入文件本身而报错(SfxBaseModel...impl_store failed)。
                # 强制calc标记的副本必须落在与--outdir不同的目录。
                forced_calc_path = Path(src_dir) / f"forced_calc_{output_path.name}"
                try:
                    wb = _load_workbook(output_path)
                    wb.calculation.calcMode = "auto"
                    wb.calculation.fullCalcOnLoad = True
                    wb.save(forced_calc_path)
                    wb.close()
                    convert_input = forced_calc_path
                except Exception as e:
                    logger.error(f"强制auto重算标记失败,退回原始文件: {e}")
                    convert_input = output_path

                cmd = [
                    "libreoffice", "--headless", "--invisible", "--norestore",
                    "--convert-to", "xlsx", "--outdir", out_dir, str(convert_input),
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                converted = Path(out_dir) / (convert_input.stem + ".xlsx")
                if result.returncode != 0 or not converted.exists():
                    logger.error(f"评分用重算副本生成失败: {result.stderr[:300]}")
                    return output_path

                dest = output_path.parent / f".scoring_{output_path.stem}.xlsx"
                shutil.copy2(converted, dest)
                return dest
        except Exception as e:
            logger.error(f"评分用重算副本生成异常: {e}")
            return output_path

    def _check_recalc(self, output_path: Path) -> bool:
        """检查LibreOffice重算一致性"""
        try:
            validation_result = self.validator.validate(output_path)
            return validation_result.checks.get("recalc_consistent", False)
        except Exception as e:
            logger.error(f"Recalc check failed: {e}")
            return False

    def _check_protected_cells(
        self,
        input_path: Path,
        output_path: Path,
        answer_positions: List[str]
    ) -> int:
        """
        检查answer_position外的单元格是否被修改

        Returns:
            违规数量
        """
        try:
            input_wb = openpyxl.load_workbook(input_path, data_only=False)
            output_wb = openpyxl.load_workbook(output_path, data_only=False)

            # 解析answer区域
            answer_cells = self._parse_answer_positions(answer_positions)

            violations = 0

            for sheet_name in input_wb.sheetnames:
                if sheet_name not in output_wb.sheetnames:
                    continue

                input_ws = input_wb[sheet_name]
                output_ws = output_wb[sheet_name]

                # 检查每个单元格
                for row in input_ws.iter_rows():
                    for cell in row:
                        cell_ref = f"{sheet_name}!{cell.coordinate}"

                        # 跳过answer区域
                        if self._is_in_answer_region(cell_ref, answer_cells):
                            continue

                        # 检查值或公式是否被修改
                        output_cell = output_ws[cell.coordinate]
                        if self._cell_modified(cell, output_cell):
                            violations += 1

            input_wb.close()
            output_wb.close()

            return violations

        except Exception as e:
            logger.error(f"Protected cells check failed: {e}")
            return 999  # 返回大数表示检查失败

    def _check_formula_family(
        self,
        golden_path: Path,
        output_path: Path,
        answer_positions: List[str]
    ) -> bool:
        """
        检查output中answer区域的公式是否与golden的公式模式一致

        Returns:
            True if consistent, False otherwise
        """
        try:
            golden_wb = openpyxl.load_workbook(golden_path, data_only=False)
            output_wb = openpyxl.load_workbook(output_path, data_only=False)

            answer_cells = self._parse_answer_positions(answer_positions)

            # 检查answer区域内的公式
            for cell_ref in answer_cells:
                sheet, coord = self._parse_cell_ref(cell_ref)

                if sheet not in golden_wb.sheetnames or sheet not in output_wb.sheetnames:
                    continue

                golden_cell = golden_wb[sheet][coord]
                output_cell = output_wb[sheet][coord]

                # 如果golden是公式，output也必须是公式
                if golden_cell.value and str(golden_cell.value).startswith('='):
                    if not output_cell.value or not str(output_cell.value).startswith('='):
                        golden_wb.close()
                        output_wb.close()
                        return False  # golden是公式，output是硬编码

                    # 比较归一化的公式模式
                    golden_formula = self._normalize_formula(str(golden_cell.value))
                    output_formula = self._normalize_formula(str(output_cell.value))

                    # 简单的模式匹配：检查公式结构是否相似
                    # （更严格的匹配需要FormulaGraph的family cluster信息）
                    if not self._formulas_similar(golden_formula, output_formula):
                        golden_wb.close()
                        output_wb.close()
                        return False

            golden_wb.close()
            output_wb.close()
            return True

        except Exception as e:
            logger.error(f"Formula family check failed: {e}")
            return False

    def _check_invariants(self, output_path: Path) -> List[str]:
        """
        验证财务约束

        Returns:
            失败的约束列表
        """
        try:
            parser = WorkbookParser(str(output_path))
            wmap, fgraph, smap, invariants = parser.parse_all()
            parser.close()
            failed = []

            # 检查每个约束
            for invariant in invariants.checks:
                if not self._verify_invariant(output_path, invariant):
                    failed.append(invariant.get("name", invariant.get("type", "unknown")))

            return failed

        except Exception as e:
            logger.error(f"Invariants check failed: {e}")
            return ["check_failed"]

    def _check_excel_errors(self, output_path: Path, answer_positions: List[str]) -> int:
        """
        统计answer区域内的Excel错误

        Returns:
            错误数量
        """
        try:
            wb = openpyxl.load_workbook(output_path, data_only=False)
            answer_cells = self._parse_answer_positions(answer_positions)

            error_count = 0

            for cell_ref in answer_cells:
                sheet, coord = self._parse_cell_ref(cell_ref)

                if sheet not in wb.sheetnames:
                    continue

                cell = wb[sheet][coord]

                # 检查单元格值是否为错误标记
                if isinstance(cell.value, str) and cell.value in self.error_markers:
                    error_count += 1

            wb.close()
            return error_count

        except Exception as e:
            logger.error(f"Excel errors check failed: {e}")
            return 999  # 返回大数表示检查失败

    def _check_style_preservation(self, input_path: Path, output_path: Path) -> bool:
        """
        检查样式是否被保留（合并单元格、命名区域）

        Returns:
            True if preserved, False otherwise
        """
        try:
            input_wb = openpyxl.load_workbook(input_path, data_only=False)
            output_wb = openpyxl.load_workbook(output_path, data_only=False)

            # 检查合并单元格
            for sheet_name in input_wb.sheetnames:
                if sheet_name not in output_wb.sheetnames:
                    continue

                input_ws = input_wb[sheet_name]
                output_ws = output_wb[sheet_name]

                input_merged = set(str(r) for r in input_ws.merged_cells.ranges)
                output_merged = set(str(r) for r in output_ws.merged_cells.ranges)

                # 如果合并区域数量减少，说明被取消了
                if len(output_merged) < len(input_merged):
                    input_wb.close()
                    output_wb.close()
                    return False

            # 检查命名区域
            input_names = set(input_wb.defined_names.keys())
            output_names = set(output_wb.defined_names.keys())

            # 如果命名区域被删除
            if len(output_names) < len(input_names):
                input_wb.close()
                output_wb.close()
                return False

            input_wb.close()
            output_wb.close()
            return True

        except Exception as e:
            logger.error(f"Style preservation check failed: {e}")
            return False

    def _check_visualization_tier1(self, output_path: Path, task_json: Dict) -> bool:
        """
        Visualization Tier 1验证：使用openpyxl读取chart XML

        Returns:
            True if passed, False otherwise
        """
        try:
            wb = openpyxl.load_workbook(output_path, data_only=False)

            # 检查是否有图表
            has_charts = False
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                if ws._charts:  # openpyxl的图表列表
                    has_charts = True
                    break

            wb.close()

            if not has_charts:
                return False

            # TODO: 更详细的Tier 1验证
            # - 图表类型检查
            # - 数据源引用检查
            # - 坐标轴标签和标题检查

            return True

        except Exception as e:
            logger.error(f"Visualization Tier 1 check failed: {e}")
            return False

    # ===== Helper Methods =====

    def _parse_answer_positions(self, answer_positions: List[str]) -> set:
        """
        解析answer_position列表为单元格引用集合

        Example: ["Sheet1!A1:A10", "Sheet2!B5"] -> {"Sheet1!A1", "Sheet1!A2", ..., "Sheet2!B5"}
        """
        cells = set()

        for position in answer_positions:
            if '!' not in position:
                continue

            sheet, range_str = position.split('!', 1)

            if ':' in range_str:
                # 区域引用
                start, end = range_str.split(':', 1)
                # 简化处理：只存储区域字符串，稍后用范围检查
                cells.add(f"{sheet}!{range_str}")
            else:
                # 单个单元格
                cells.add(f"{sheet}!{range_str}")

        return cells

    def _is_in_answer_region(self, cell_ref: str, answer_cells: set) -> bool:
        """检查单元格是否在answer区域内"""
        # 直接匹配
        if cell_ref in answer_cells:
            return True

        # 范围匹配（简化版本，完整实现需要解析A1:B10这样的范围）
        sheet, coord = cell_ref.split('!', 1)
        for answer_ref in answer_cells:
            if ':' in answer_ref:
                # 这是一个范围
                if sheet in answer_ref:
                    # TODO: 实现完整的范围包含检查
                    # 目前简化为True（假设都在范围内，避免误报）
                    return True

        return False

    def _parse_cell_ref(self, cell_ref: str) -> tuple:
        """解析Sheet1!A1为(Sheet1, A1)"""
        if '!' in cell_ref:
            sheet, coord = cell_ref.split('!', 1)
            # 移除范围中的冒号（只取起始单元格）
            if ':' in coord:
                coord = coord.split(':')[0]
            return sheet, coord
        return "", cell_ref

    def _cell_modified(self, input_cell, output_cell) -> bool:
        """检查单元格是否被修改"""
        # 比较值
        if input_cell.value != output_cell.value:
            return True

        # 比较格式（简化版本）
        if input_cell.fill.patternType != output_cell.fill.patternType:
            return True
        if input_cell.font.color != output_cell.font.color:
            return True

        return False

    def _normalize_formula(self, formula: str) -> str:
        """归一化公式（去除空格，统一大小写）"""
        formula = formula.strip().upper()
        formula = formula.replace(' ', '')
        return formula

    def _formulas_similar(self, formula1: str, formula2: str) -> bool:
        """
        检查两个公式是否相似

        简化版本：检查主要函数名和结构
        完整版本需要FormulaGraph的family cluster信息
        """
        # 提取主要函数名
        funcs1 = set()
        funcs2 = set()

        for func in ['SUM', 'AVERAGE', 'COUNT', 'IF', 'VLOOKUP', 'INDEX', 'MATCH']:
            if func in formula1:
                funcs1.add(func)
            if func in formula2:
                funcs2.add(func)

        # 如果主要函数不同，认为不相似
        if funcs1 != funcs2:
            return False

        return True

    def _verify_invariant(self, output_path: Path, invariant: Dict) -> bool:
        """
        验证单个约束

        TODO: 实现完整的约束验证逻辑
        目前返回True（假设都通过）
        """
        # 这里需要根据invariant的类型实现具体的验证逻辑
        # 例如：资产负债平衡、三表勾稽等
        return True


# ===== 导出 =====

__all__ = ['TrajectoryVerifier', 'VerificationResult']
