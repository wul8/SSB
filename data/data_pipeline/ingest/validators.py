"""
S0 资产入库 - 验证器模块

实现重算门槛检查，确保只有符合标准的工作簿进入管线。
"""

import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """验证结果"""
    passed: bool
    checks: Dict[str, bool]
    errors: List[str]
    warnings: List[str]
    metadata: Dict


class WorkbookValidator:
    """工作簿验证器"""

    # Volatile函数列表
    VOLATILE_FUNCTIONS = ["NOW", "TODAY", "RAND", "RANDBETWEEN", "INDIRECT"]

    # PII关键词（简化版，实际应更全面）
    PII_KEYWORDS = [
        "ssn", "social security", "passport", "credit card",
        "driver license", "phone", "email", "address"
    ]

    def __init__(self, strict: bool = True):
        """
        Args:
            strict: 是否启用严格模式（所有检查必须通过）
        """
        self.strict = strict

    def validate(self, file_path: Path) -> ValidationResult:
        """
        执行完整的S0门槛检查

        Args:
            file_path: 工作簿文件路径

        Returns:
            ValidationResult对象
        """
        checks = {}
        errors = []
        warnings = []
        metadata = {}

        # 检查1: openpyxl可读
        try:
            wb = openpyxl.load_workbook(file_path, data_only=False)
            checks["openpyxl_readable"] = True
            metadata["num_sheets"] = len(wb.sheetnames)
            metadata["sheet_names"] = wb.sheetnames
        except InvalidFileException as e:
            checks["openpyxl_readable"] = False
            errors.append(f"openpyxl无法读取: {e}")
            return ValidationResult(False, checks, errors, warnings, metadata)
        except Exception as e:
            checks["openpyxl_readable"] = False
            errors.append(f"未知错误: {e}")
            return ValidationResult(False, checks, errors, warnings, metadata)

        # 检查2: LibreOffice可打开
        lo_check, lo_error = self._check_libreoffice_openable(file_path)
        checks["libreoffice_openable"] = lo_check
        if not lo_check:
            errors.append(f"LibreOffice无法打开: {lo_error}")

        # 检查3: 重算一致性
        if checks["libreoffice_openable"]:
            recalc_check, recalc_error = self._check_recalc_consistency(file_path)
            checks["recalc_consistent"] = recalc_check
            if not recalc_check:
                errors.append(f"重算不一致: {recalc_error}")
        else:
            checks["recalc_consistent"] = False

        # 检查4: 无外部链接
        ext_links = self._check_external_links(wb)
        checks["no_external_links"] = len(ext_links) == 0
        if ext_links:
            errors.append(f"发现{len(ext_links)}个外部链接: {ext_links[:3]}")
            metadata["external_links"] = ext_links

        # 检查5: 无volatile函数
        volatile_cells = self._check_volatile_functions(wb)
        checks["no_volatile_functions"] = len(volatile_cells) == 0
        if volatile_cells:
            warnings.append(f"发现{len(volatile_cells)}个volatile函数: {volatile_cells[:5]}")
            metadata["volatile_cells"] = volatile_cells
            # Volatile函数是warning而非error（除非strict模式）
            if self.strict:
                errors.append("严格模式：不允许volatile函数")

        # 检查6: 无PII（简化检查）
        pii_cells = self._check_pii(wb)
        checks["no_pii"] = len(pii_cells) == 0
        if pii_cells:
            errors.append(f"疑似PII: {pii_cells[:3]}")
            metadata["suspected_pii"] = pii_cells

        # 检查7: 无宏
        has_macros = self._check_macros(file_path)
        checks["no_macros"] = not has_macros
        if has_macros:
            errors.append("包含宏代码")

        # 检查8: Golden内无未解释的Excel错误
        excel_errors = self._check_excel_errors(wb)
        checks["no_unresolved_errors"] = len(excel_errors) == 0
        if excel_errors:
            warnings.append(f"发现{len(excel_errors)}个Excel错误值: {excel_errors[:5]}")
            metadata["excel_errors"] = excel_errors

        # 检查9: 有公式（路线B需要）
        formula_count = self._count_formulas(wb)
        metadata["formula_count"] = formula_count
        metadata["has_formulas"] = formula_count > 0
        if formula_count == 0:
            warnings.append("纯数据表，无公式（路线B可用性有限）")

        wb.close()

        # 判定是否通过
        passed = all(checks.values()) if self.strict else all(
            checks.get(k, False) for k in [
                "openpyxl_readable",
                "libreoffice_openable",
                "recalc_consistent",
                "no_external_links",
                "no_macros",
                "no_pii"
            ]
        )

        return ValidationResult(
            passed=passed,
            checks=checks,
            errors=errors,
            warnings=warnings,
            metadata=metadata
        )

    def _check_libreoffice_openable(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """检查LibreOffice是否能打开文件"""
        try:
            # 使用LibreOffice headless模式尝试打开
            cmd = [
                "libreoffice",
                "--headless",
                "--invisible",
                "--norestore",
                "--convert-to", "xlsx",
                "--outdir", "/tmp",
                str(file_path)
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                # 清理临时文件
                temp_output = Path("/tmp") / (file_path.stem + ".xlsx")
                if temp_output.exists():
                    temp_output.unlink()
                return True, None
            else:
                return False, result.stderr

        except subprocess.TimeoutExpired:
            return False, "超时"
        except Exception as e:
            return False, str(e)

    def _check_recalc_consistency(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """
        检查重算一致性：两次重算结果应该一致

        这是S0最关键的检查之一
        """
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir = Path(tmpdir)

                # 第一次重算（输出到独立子目录，避免与第二次转换的输入/输出路径冲突）
                pass1_dir = tmpdir / "pass1"
                pass1_dir.mkdir()
                recalc1 = pass1_dir / "recalc1.xlsx"
                success1, error1 = self._recalculate_with_libreoffice(file_path, recalc1)
                if not success1:
                    return False, f"第一次重算失败: {error1}"

                # 第二次重算（同理，独立子目录，避免LibreOffice原地覆盖输入文件导致失败）
                pass2_dir = tmpdir / "pass2"
                pass2_dir.mkdir()
                recalc2 = pass2_dir / "recalc2.xlsx"
                success2, error2 = self._recalculate_with_libreoffice(recalc1, recalc2)
                if not success2:
                    return False, f"第二次重算失败: {error2}"

                # 比较两次结果
                wb1 = openpyxl.load_workbook(recalc1, data_only=True)
                wb2 = openpyxl.load_workbook(recalc2, data_only=True)

                mismatches = []
                for sheet_name in wb1.sheetnames:
                    if sheet_name not in wb2.sheetnames:
                        mismatches.append(f"Sheet '{sheet_name}' 只在第一次存在")
                        continue

                    ws1 = wb1[sheet_name]
                    ws2 = wb2[sheet_name]

                    # Skip chart sheets (they don't have iter_rows)
                    if not hasattr(ws1, 'iter_rows'):
                        continue

                    for row in ws1.iter_rows():
                        for cell in row:
                            if cell.value is None:
                                continue

                            cell2 = ws2[cell.coordinate]
                            if not self._values_equal(cell.value, cell2.value):
                                mismatches.append(
                                    f"{sheet_name}!{cell.coordinate}: "
                                    f"{cell.value} != {cell2.value}"
                                )

                            if len(mismatches) > 10:  # 最多记录10个不一致
                                break
                        if len(mismatches) > 10:
                            break

                wb1.close()
                wb2.close()

                if mismatches:
                    return False, f"发现{len(mismatches)}处不一致: {mismatches[:3]}"

                return True, None

        except Exception as e:
            return False, f"重算检查异常: {e}"

    def _recalculate_with_libreoffice(
        self,
        input_path: Path,
        output_path: Path
    ) -> Tuple[bool, Optional[str]]:
        """使用LibreOffice重算工作簿"""
        try:
            # LibreOffice转换会自动重算
            cmd = [
                "libreoffice",
                "--headless",
                "--invisible",
                "--norestore",
                "--convert-to", "xlsx",
                "--outdir", str(output_path.parent),
                str(input_path)
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                return False, result.stderr

            # 重命名输出文件
            actual_output = output_path.parent / (input_path.stem + ".xlsx")
            if actual_output.exists() and actual_output != output_path:
                actual_output.rename(output_path)

            return output_path.exists(), None

        except subprocess.TimeoutExpired:
            return False, "超时"
        except Exception as e:
            return False, str(e)

    def _values_equal(self, v1, v2, tolerance: float = 1e-9) -> bool:
        """比较两个单元格值是否相等"""
        if v1 is None and v2 is None:
            return True
        if v1 is None or v2 is None:
            return False

        # 字符串比较
        if isinstance(v1, str) and isinstance(v2, str):
            return v1.strip() == v2.strip()

        # 数值比较（带容差）
        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            if abs(v1) < tolerance and abs(v2) < tolerance:
                return True
            return abs(v1 - v2) / max(abs(v1), abs(v2)) < tolerance

        return v1 == v2

    def _check_external_links(self, wb: openpyxl.Workbook) -> List[str]:
        """检查外部链接"""
        external_links = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            # Skip chart sheets (they don't have iter_rows)
            if not hasattr(ws, 'iter_rows'):
                continue
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value and isinstance(cell.value, str):
                        # 检查公式中的外部引用
                        if cell.value.startswith("=") and "[" in cell.value:
                            external_links.append(f"{sheet_name}!{cell.coordinate}")

        return external_links

    def _check_volatile_functions(self, wb: openpyxl.Workbook) -> List[str]:
        """检查volatile函数"""
        volatile_cells = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            # Skip chart sheets (they don't have iter_rows)
            if not hasattr(ws, 'iter_rows'):
                continue
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value and isinstance(cell.value, str):
                        if cell.value.startswith("="):
                            formula_upper = cell.value.upper()
                            for func in self.VOLATILE_FUNCTIONS:
                                if func in formula_upper:
                                    volatile_cells.append(
                                        f"{sheet_name}!{cell.coordinate}: {func}"
                                    )
                                    break

        return volatile_cells

    def _check_pii(self, wb: openpyxl.Workbook) -> List[str]:
        """简化的PII检查（实际应更严格）"""
        suspected_pii = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            # Skip chart sheets (they don't have iter_rows)
            if not hasattr(ws, 'iter_rows'):
                continue
            for row in ws.iter_rows(max_row=100):  # 只检查前100行
                for cell in row:
                    if cell.value and isinstance(cell.value, str):
                        value_lower = cell.value.lower()
                        for keyword in self.PII_KEYWORDS:
                            if keyword in value_lower:
                                suspected_pii.append(
                                    f"{sheet_name}!{cell.coordinate}: {keyword}"
                                )
                                break

            if len(suspected_pii) > 10:
                break

        return suspected_pii

    def _check_macros(self, file_path: Path) -> bool:
        """检查是否包含宏"""
        # 简化检查：xlsm后缀
        if file_path.suffix.lower() == ".xlsm":
            return True

        # 更严格的检查需要解析VBA项目
        # 这里暂时简化处理
        return False

    def _check_excel_errors(self, wb: openpyxl.Workbook) -> List[str]:
        """检查Excel错误值"""
        error_cells = []
        error_values = ["#REF!", "#VALUE!", "#NUM!", "#DIV/0!", "#N/A", "#NAME?", "#NULL!"]

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            # Skip chart sheets (they don't have iter_rows)
            if not hasattr(ws, 'iter_rows'):
                continue
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value and isinstance(cell.value, str):
                        if cell.value in error_values:
                            error_cells.append(f"{sheet_name}!{cell.coordinate}: {cell.value}")

        return error_cells

    def _count_formulas(self, wb: openpyxl.Workbook) -> int:
        """统计公式数量"""
        count = 0
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            # Skip chart sheets (they don't have iter_rows)
            if not hasattr(ws, 'iter_rows'):
                continue
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value and isinstance(cell.value, str):
                        if cell.value.startswith("="):
                            count += 1
        return count


def batch_validate(
    file_paths: List[Path],
    output_json: Optional[Path] = None,
    strict: bool = True
) -> Dict[str, ValidationResult]:
    """
    批量验证工作簿

    Args:
        file_paths: 文件路径列表
        output_json: 如果提供，将结果保存到JSON
        strict: 是否严格模式

    Returns:
        文件路径到ValidationResult的映射
    """
    validator = WorkbookValidator(strict=strict)
    results = {}

    for file_path in file_paths:
        logger.info(f"验证 {file_path.name}...")
        result = validator.validate(file_path)
        results[str(file_path)] = result

        if result.passed:
            logger.info(f"  ✓ 通过")
        else:
            logger.warning(f"  ✗ 失败: {', '.join(result.errors)}")

    # 保存结果
    if output_json:
        serializable_results = {
            path: {
                "passed": res.passed,
                "checks": res.checks,
                "errors": res.errors,
                "warnings": res.warnings,
                "metadata": res.metadata
            }
            for path, res in results.items()
        }
        with open(output_json, "w") as f:
            json.dump(serializable_results, f, indent=2, ensure_ascii=False)
        logger.info(f"结果已保存到 {output_json}")

    # 统计
    passed_count = sum(1 for r in results.values() if r.passed)
    total_count = len(results)
    logger.info(f"\n通过率: {passed_count}/{total_count} ({passed_count/total_count*100:.1f}%)")

    return results


if __name__ == "__main__":
    # 测试示例
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("用法: python validators.py <xlsx文件路径>")
        sys.exit(1)

    file_path = Path(sys.argv[1])
    validator = WorkbookValidator(strict=True)
    result = validator.validate(file_path)

    print(f"\n验证结果: {'通过' if result.passed else '失败'}")
    print(f"\n检查项:")
    for check, passed in result.checks.items():
        print(f"  {check}: {'✓' if passed else '✗'}")

    if result.errors:
        print(f"\n错误:")
        for error in result.errors:
            print(f"  - {error}")

    if result.warnings:
        print(f"\n警告:")
        for warning in result.warnings:
            print(f"  - {warning}")

    print(f"\n元数据:")
    print(json.dumps(result.metadata, indent=2, ensure_ascii=False))
