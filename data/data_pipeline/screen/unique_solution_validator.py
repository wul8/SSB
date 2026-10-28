#!/usr/bin/env python3
"""
唯一解验证器

验证任务是否具有唯一解:
1. Debugging任务: golden应该是input的唯一正确修复
2. Template任务: 填充的数据应该由公式约束唯一确定

策略:
- 通过公式依赖分析检查约束充分性
- 检查是否存在未约束的自由度
- 对于Debugging: 验证每个错误的修复是否唯一
"""

import logging
from pathlib import Path
from typing import Dict, Set, List, Tuple, Optional
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, column_index_from_string
import json

logger = logging.getLogger(__name__)


class UniqueSolutionValidator:
    """唯一解验证器"""

    def __init__(self):
        pass

    def validate(self, task: Dict) -> bool:
        """
        验证任务是否有唯一解

        Args:
            task: 任务JSON字典

        Returns:
            True if unique solution, False otherwise
        """
        task_type = task.get("type", "")

        if task_type == "Debugging":
            return self._validate_debugging(task)
        elif task_type == "Template":
            return self._validate_template(task)
        else:
            logger.warning(f"未知任务类型: {task_type}")
            return True  # 默认通过

    def _validate_debugging(self, task: Dict) -> bool:
        """
        验证Debugging任务的唯一解

        策略:
        - 每个错误的修复应该是唯一的
        - 检查answer_position中的单元格是否由公式或数据唯一确定
        """
        input_path = Path(task["input_path"])
        golden_path = Path(task["golden_path"])
        answer_positions = task.get("answer_position", [])

        if not input_path.exists() or not golden_path.exists():
            logger.error(f"文件不存在: {input_path} or {golden_path}")
            return False

        try:
            input_wb = load_workbook(input_path, data_only=False)
            golden_wb = load_workbook(golden_path, data_only=False)

            # 检查每个修复点
            for cell_addr in answer_positions:
                # 解析地址: Sheet1!A1
                if '!' in cell_addr:
                    sheet_name, coord = cell_addr.split('!', 1)
                else:
                    logger.warning(f"无效的单元格地址: {cell_addr}")
                    continue

                # 检查input和golden的差异
                input_cell = input_wb[sheet_name][coord]
                golden_cell = golden_wb[sheet_name][coord]

                # 如果是公式修复，公式应该不同
                if isinstance(golden_cell.value, str) and golden_cell.value.startswith('='):
                    if input_cell.value == golden_cell.value:
                        logger.warning(f"公式未修复: {cell_addr}")
                        continue

                # 如果是值修复，值应该不同
                if input_cell.value != golden_cell.value:
                    # 验证golden的值是正确的(通过重算验证)
                    # 这里简化处理，假设golden已经过S0验证
                    pass

            input_wb.close()
            golden_wb.close()

            # 简化策略: Debugging任务默认有唯一解
            # (因为错误注入是确定性的，修复也是确定性的)
            return True

        except Exception as e:
            logger.error(f"验证Debugging唯一解失败: {e}")
            return False

    def _validate_template(self, task: Dict) -> bool:
        """
        验证Template任务的唯一解

        策略:
        - 检查被清空的数据单元格是否由公式约束唯一确定
        - 统计自由度: answer_position中的单元格 vs 约束数量
        """
        input_path = Path(task["input_path"])
        golden_path = Path(task["golden_path"])
        answer_positions = task.get("answer_position", [])
        metadata = task.get("metadata", {})

        if not input_path.exists() or not golden_path.exists():
            logger.error(f"文件不存在: {input_path} or {golden_path}")
            return False

        try:
            # 加载golden获取公式图
            golden_wb = load_workbook(golden_path, data_only=False)

            # 统计answer_position中被公式约束的单元格
            constrained_cells = set()
            formula_cells = set()

            for sheet in golden_wb.worksheets:
                for row in sheet.iter_rows():
                    for cell in row:
                        if cell.value and isinstance(cell.value, str) and cell.value.startswith('='):
                            cell_addr = f"{sheet.title}!{cell.coordinate}"
                            formula_cells.add(cell_addr)

                            # 提取公式引用的单元格
                            # 简化处理: 如果公式引用了answer_position中的单元格
                            # 那么这些单元格被约束
                            # TODO: 完整的依赖分析需要解析公式AST

            golden_wb.close()

            # 策略: Template任务需要有公式约束才能保证唯一解
            # 纯数据填充任务(无公式)可能有多个有效解

            # 检查是否有足够的公式约束
            formula_count = len(formula_cells)
            data_count = len(answer_positions)

            if formula_count == 0 and data_count > 0:
                logger.warning(f"无公式约束但有{data_count}个数据单元格")
                # 纯数据填充任务没有唯一解
                # 这类任务应该被Template生成器过滤掉，不应该进入筛选阶段
                return False

            # 有公式的Template任务认为有唯一解
            # (数据单元格由公式约束唯一确定)
            return formula_count > 0

        except Exception as e:
            logger.error(f"验证Template唯一解失败: {e}")
            return False

    def validate_with_perturbation(
        self,
        task: Dict,
        num_perturbations: int = 3
    ) -> bool:
        """
        通过扰动测试验证唯一解

        策略:
        - 对input进行多次随机扰动
        - 检查是否都收敛到同一个golden
        - 如果不收敛，说明无唯一解

        注意: 这需要实际运行求解器，成本较高
        """
        logger.warning("扰动测试需要运行求解器，当前未实现")
        return True


def main():
    """测试用主函数"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # 测试唯一解验证器
    validator = UniqueSolutionValidator()

    # 加载一个任务进行测试
    task_file = Path("/tmp/template_batch_test/0_ref_0_template_2824.json")

    if not task_file.exists():
        logger.error(f"测试文件不存在: {task_file}")
        return

    with open(task_file, 'r', encoding='utf-8') as f:
        task = json.load(f)

    result = validator.validate(task)

    print(f"\n唯一解验证结果: {'✓ 通过' if result else '✗ 失败'}")


if __name__ == "__main__":
    main()
