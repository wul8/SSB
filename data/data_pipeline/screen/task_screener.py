#!/usr/bin/env python3
"""
S3 任务筛选器

对S2生成的任务进行质量筛选:
1. 唯一解验证: 检查任务是否有唯一解
2. 污染扫描: 检测与官方321题的重叠
3. 难度分级: L1-L4自动分类和验证

核心逻辑:
- 唯一解验证: 多次随机扰动输入检查golden一致性
- 污染扫描: 集成contamination_scanner的6种方法
- 难度分级: 验证生成器标注的难度是否合理
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import json
import hashlib
from openpyxl import load_workbook

logger = logging.getLogger(__name__)


@dataclass
class ScreeningResult:
    """筛选结果"""
    task_id: str
    passed: bool
    unique_solution: bool
    contaminated: bool
    difficulty_valid: bool
    difficulty_adjusted: Optional[str] = None
    issues: List[str] = None

    def __post_init__(self):
        if self.issues is None:
            self.issues = []


class TaskScreener:
    """任务筛选器"""

    def __init__(
        self,
        contamination_scanner=None,
        unique_solution_validator=None,
        auto_fix_difficulty=True
    ):
        """
        Args:
            contamination_scanner: ContaminationScanner实例
            unique_solution_validator: UniqueSolutionValidator实例
            auto_fix_difficulty: 是否自动修正难度标注（默认True）
        """
        self.contamination_scanner = contamination_scanner
        self.unique_solution_validator = unique_solution_validator
        self.auto_fix_difficulty = auto_fix_difficulty

    def screen_task(
        self,
        task_json_path: Path,
        check_unique_solution: bool = True,
        check_contamination: bool = True,
        check_difficulty: bool = True
    ) -> ScreeningResult:
        """
        筛选单个任务

        Args:
            task_json_path: 任务JSON文件路径
            check_unique_solution: 是否检查唯一解
            check_contamination: 是否检查污染
            check_difficulty: 是否检查难度

        Returns:
            ScreeningResult对象
        """
        # 加载任务JSON
        with open(task_json_path, 'r', encoding='utf-8') as f:
            task = json.load(f)

        task_id = task["task_id"]
        issues = []

        # 1. 唯一解验证
        unique_solution = True
        if check_unique_solution and self.unique_solution_validator:
            unique_solution = self._check_unique_solution(task)
            if not unique_solution:
                issues.append("No unique solution detected")

        # 2. 污染扫描
        contaminated = False
        if check_contamination and self.contamination_scanner:
            contaminated = self._check_contamination(task)
            if contaminated:
                issues.append("Contamination detected with official dataset")

        # 3. 难度验证与自动修正
        difficulty_valid = True
        difficulty_adjusted = None
        difficulty_fixed = False
        if check_difficulty:
            difficulty_valid, difficulty_adjusted = self._check_difficulty(task)
            if not difficulty_valid:
                if self.auto_fix_difficulty:
                    # 自动修正难度标注
                    self._fix_difficulty(task_json_path, difficulty_adjusted)
                    difficulty_fixed = True
                    difficulty_valid = True  # 修正后视为通过
                    issues.append(f"Difficulty auto-fixed: {task['difficulty']} → {difficulty_adjusted}")
                    logger.info(f"✓ 自动修正难度: {task_id} {task['difficulty']} → {difficulty_adjusted}")
                else:
                    issues.append(f"Difficulty mismatch: {task['difficulty']} → {difficulty_adjusted}")

        # 综合判断
        passed = unique_solution and not contaminated and difficulty_valid

        result = ScreeningResult(
            task_id=task_id,
            passed=passed,
            unique_solution=unique_solution,
            contaminated=contaminated,
            difficulty_valid=difficulty_valid,
            difficulty_adjusted=difficulty_adjusted,
            issues=issues
        )

        logger.info(f"筛选结果: {task_id} - {'✓ 通过' if passed else '✗ 未通过'}")
        if issues:
            for issue in issues:
                logger.info(f"  - {issue}")

        return result

    def _check_unique_solution(self, task: Dict) -> bool:
        """
        检查唯一解

        策略:
        - 对于Debugging任务: golden应该是input的唯一正确修复
        - 对于Template任务: 填充的数据应该由公式约束唯一确定

        实现:
        - 加载input和golden
        - 验证golden是input的有效修复
        - 检查是否存在其他有效解(通过公式依赖分析)
        """
        if not self.unique_solution_validator:
            logger.warning("UniqueSolutionValidator未提供，跳过唯一解检查")
            return True

        # 委托给专门的validator
        return self.unique_solution_validator.validate(task)

    def _check_contamination(self, task: Dict) -> bool:
        """
        检查污染

        使用contamination_scanner的6种方法检测
        """
        if not self.contamination_scanner:
            logger.warning("ContaminationScanner未提供，跳过污染检查")
            return False

        # 委托给contamination_scanner.check_task
        candidate_task = {
            "task_id": task.get("task_id", "unknown"),
            "input_file_path": task["input_path"],
            "instruction": task.get("instruction", ""),
            "answer_position": self._flatten_answer_position(task.get("answer_position", [])),
            "lineage_family": task.get("workbook_id"),
        }

        is_clean, reasons = self.contamination_scanner.check_task(candidate_task)
        if not is_clean:
            logger.warning(f"污染检测命中: {task.get('task_id')} - {reasons}")

        return not is_clean

    def _flatten_answer_position(self, answer_position) -> str:
        """answer_position在我们的task.json里是list[str]，官方数据集里是单个逗号分隔字符串"""
        if isinstance(answer_position, list):
            return ",".join(answer_position)
        return answer_position or ""

    def _check_difficulty(self, task: Dict) -> Tuple[bool, Optional[str]]:
        """
        检查难度标注是否合理

        策略:
        - 重新计算难度得分
        - 与标注的难度对比
        - 如果偏差>1级则认为不合理

        Returns:
            (是否合理, 建议的难度级别)
        """
        stated_difficulty = task["difficulty"]
        metadata = task.get("metadata", {})

        # 重新计算难度得分
        score = self._calculate_difficulty_score(task, metadata)

        # 映射到难度级别
        if score < 30:
            calculated = "L1"
        elif score < 50:
            calculated = "L2"
        elif score < 70:
            calculated = "L3"
        else:
            calculated = "L4"

        # 检查是否一致
        valid = (calculated == stated_difficulty)

        if not valid:
            logger.warning(
                f"难度偏差: {task['task_id']} - "
                f"标注={stated_difficulty}, 计算={calculated}, 得分={score}"
            )

        return valid, calculated if not valid else None

    def _fix_difficulty(self, task_json_path: Path, new_difficulty: str) -> None:
        """
        修正任务JSON文件中的难度标注

        Args:
            task_json_path: 任务JSON文件路径
            new_difficulty: 新的难度级别
        """
        try:
            with open(task_json_path, 'r', encoding='utf-8') as f:
                task_data = json.load(f)

            old_difficulty = task_data.get('difficulty', 'unknown')
            task_data['difficulty'] = new_difficulty

            with open(task_json_path, 'w', encoding='utf-8') as f:
                json.dump(task_data, f, indent=2, ensure_ascii=False)

            logger.info(f"已修正难度标注: {task_json_path.name} ({old_difficulty} → {new_difficulty})")
        except Exception as e:
            logger.error(f"修正难度标注失败: {task_json_path.name} - {e}")
            raise

    def _calculate_difficulty_score(self, task: Dict, metadata: Dict) -> int:
        """
        计算难度得分

        因素:
        - 数据单元格数量 (0-30分)
        - 公式单元格数量 (0-30分)
        - Sheet数量 (0-20分)
        - 不变量约束 (0-20分)
        """
        score = 0

        # 1. 数据单元格 (answer_position长度)
        answer_count = len(task.get("answer_position", []))
        if answer_count < 10:
            score += 5
        elif answer_count < 30:
            score += 15
        elif answer_count < 50:
            score += 25
        else:
            score += 30

        # 2. 公式单元格
        formula_count = metadata.get("formula_cells_total", 0)
        if formula_count < 10:
            score += 5
        elif formula_count < 50:
            score += 15
        elif formula_count < 100:
            score += 25
        else:
            score += 30

        # 3. Sheet数量
        sheet_count = len(metadata.get("sheets", []))
        if sheet_count <= 2:
            score += 5
        elif sheet_count <= 5:
            score += 10
        elif sheet_count <= 10:
            score += 15
        else:
            score += 20

        # 4. 不变量约束 (从metadata提取)
        invariant_count = 0
        if "invariants" in metadata:
            invariant_count = len(metadata["invariants"].get("checks", []))

        if invariant_count == 0:
            score += 0
        elif invariant_count <= 2:
            score += 10
        else:
            score += 20

        return score

    def batch_screen(
        self,
        task_dir: Path,
        output_path: Path,
        check_unique_solution: bool = True,
        check_contamination: bool = True,
        check_difficulty: bool = True
    ) -> Dict:
        """
        批量筛选任务目录

        Args:
            task_dir: 任务JSON文件所在目录
            output_path: 筛选报告输出路径
            check_unique_solution: 是否检查唯一解
            check_contamination: 是否检查污染
            check_difficulty: 是否检查难度

        Returns:
            筛选统计信息
        """
        # 查找所有任务JSON文件
        task_files = list(task_dir.glob("*_template_*.json")) + \
                     list(task_dir.glob("*_debugging_*.json"))

        if not task_files:
            logger.error(f"未找到任务JSON文件: {task_dir}")
            return {}

        logger.info(f"找到{len(task_files)}个任务文件")

        results = []
        stats = {
            "total": len(task_files),
            "passed": 0,
            "failed": 0,
            "unique_solution_failed": 0,
            "contaminated": 0,
            "difficulty_mismatch": 0,
            "difficulty_auto_fixed": 0
        }

        for task_file in task_files:
            try:
                result = self.screen_task(
                    task_file,
                    check_unique_solution=check_unique_solution,
                    check_contamination=check_contamination,
                    check_difficulty=check_difficulty
                )

                results.append({
                    "task_id": result.task_id,
                    "passed": result.passed,
                    "unique_solution": result.unique_solution,
                    "contaminated": result.contaminated,
                    "difficulty_valid": result.difficulty_valid,
                    "difficulty_adjusted": result.difficulty_adjusted,
                    "issues": result.issues
                })

                # 更新统计
                if result.passed:
                    stats["passed"] += 1
                else:
                    stats["failed"] += 1

                    if not result.unique_solution:
                        stats["unique_solution_failed"] += 1
                    if result.contaminated:
                        stats["contaminated"] += 1
                    if not result.difficulty_valid:
                        stats["difficulty_mismatch"] += 1

                # 统计自动修正的难度
                if "auto-fixed" in " ".join(result.issues).lower():
                    stats["difficulty_auto_fixed"] += 1

            except Exception as e:
                logger.error(f"筛选{task_file.name}时出错: {e}")
                stats["failed"] += 1

        # 生成报告
        report = {
            "statistics": stats,
            "results": results
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"筛选报告已保存: {output_path}")

        # 打印总结
        print("\n" + "="*80)
        print("任务筛选总结")
        print("="*80)
        print(f"总任务数: {stats['total']}")
        print(f"通过: {stats['passed']} ({stats['passed']/stats['total']*100:.1f}%)")
        print(f"失败: {stats['failed']} ({stats['failed']/stats['total']*100:.1f}%)")
        print()
        print("处理详情:")
        print(f"  难度自动修正: {stats['difficulty_auto_fixed']}")
        print(f"  唯一解验证失败: {stats['unique_solution_failed']}")
        print(f"  污染检测命中: {stats['contaminated']}")
        print(f"  难度标注偏差(未修正): {stats['difficulty_mismatch']}")
        print("="*80)

        return stats


def main():
    """测试用主函数"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # 测试任务筛选器
    task_dir = Path("/tmp/template_batch_test")
    output_path = Path("/tmp/screening_report.json")

    if not task_dir.exists():
        logger.error(f"任务目录不存在: {task_dir}")
        return

    # 创建筛选器(暂不提供污染扫描器和唯一解验证器)
    screener = TaskScreener()

    # 批量筛选(只检查难度)
    stats = screener.batch_screen(
        task_dir=task_dir,
        output_path=output_path,
        check_unique_solution=False,  # 暂未实现
        check_contamination=False,    # 暂未实现
        check_difficulty=True
    )

    print(f"\n筛选完成，详细报告: {output_path}")


if __name__ == "__main__":
    main()
