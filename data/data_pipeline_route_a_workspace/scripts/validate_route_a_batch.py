#!/usr/bin/env python3
"""
路线A批量验证脚本

验证专家标注的FM和Visualization任务批次，确保质量和完整性。

验证项目:
1. 任务文件完整性 (task.json, input.xlsx, golden.xlsx)
2. S0门槛检查 (input和golden都需要通过)
3. 元数据完整性 (必填字段、格式正确性)
4. Criteria可验证性
5. 唯一解检查 (FM任务)
6. Visualization criteria结构检查

Usage:
    python validate_route_a_batch.py \
        --task-dir /path/to/tasks \
        --output-report batch_report.json
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import sys

# 添加项目根目录到path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingest.validators import WorkbookValidator
from screen.unique_solution_validator import UniqueSolutionValidator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RouteABatchValidator:
    """路线A批量验证器"""

    REQUIRED_TASK_FIELDS = [
        'task_id', 'task_type', 'difficulty', 'instruction',
        'input_workbook', 'golden_workbook', 'answer_position', 'criteria'
    ]

    REQUIRED_METADATA_FIELDS = [
        'route', 'domain', 'concepts', 'estimated_time_minutes',
        'seed_workbook_id', 'generation_model', 'creation_date'
    ]

    VALID_TASK_TYPES = ['FM', 'Visualization']
    VALID_DIFFICULTIES = ['L1', 'L2', 'L3', 'L4']

    def __init__(self):
        self.wb_validator = WorkbookValidator()
        self.solution_validator = UniqueSolutionValidator()

    def validate_batch(
        self,
        task_dir: Path,
        skip_s0: bool = False
    ) -> Dict:
        """
        验证一批任务

        Args:
            task_dir: 任务目录（每个子目录一个任务）
            skip_s0: 是否跳过S0门槛检查（用于快速验证）

        Returns:
            验证报告字典
        """
        logger.info(f"开始验证批次: {task_dir}")
        logger.info("="*80)

        # 扫描所有任务
        tasks = self._scan_tasks(task_dir)
        logger.info(f"找到 {len(tasks)} 个任务")

        results = []
        success_count = 0
        fail_count = 0

        for idx, task_path in enumerate(tasks, 1):
            logger.info(f"\n[{idx}/{len(tasks)}] 验证任务: {task_path.name}")
            logger.info("-"*60)

            result = self._validate_single_task(task_path, skip_s0)
            results.append(result)

            if result['passed']:
                success_count += 1
                logger.info(f"✓ 任务 {task_path.name} 验证通过")
            else:
                fail_count += 1
                logger.error(f"✗ 任务 {task_path.name} 验证失败")
                for issue in result['issues']:
                    logger.error(f"  - {issue}")

        # 生成报告
        report = {
            'timestamp': datetime.now().isoformat(),
            'task_dir': str(task_dir),
            'total_tasks': len(tasks),
            'success_count': success_count,
            'fail_count': fail_count,
            'success_rate': success_count / len(tasks) if tasks else 0,
            'results': results
        }

        logger.info("\n" + "="*80)
        logger.info("批次验证完成")
        logger.info(f"总任务数: {len(tasks)}")
        logger.info(f"通过: {success_count} ({success_count/len(tasks)*100:.1f}%)")
        logger.info(f"失败: {fail_count} ({fail_count/len(tasks)*100:.1f}%)")

        return report

    def _scan_tasks(self, task_dir: Path) -> List[Path]:
        """扫描任务目录"""
        tasks = []
        for item in sorted(task_dir.iterdir()):
            if item.is_dir():
                task_json = item / 'task.json'
                if task_json.exists():
                    tasks.append(item)
        return tasks

    def _validate_single_task(
        self,
        task_path: Path,
        skip_s0: bool
    ) -> Dict:
        """验证单个任务"""
        result = {
            'task_path': str(task_path),
            'task_id': task_path.name,
            'passed': True,
            'issues': []
        }

        try:
            # 1. 检查文件完整性
            task_json_path = task_path / 'task.json'
            if not task_json_path.exists():
                result['passed'] = False
                result['issues'].append("task.json不存在")
                return result

            with open(task_json_path) as f:
                task = json.load(f)

            result['task_id'] = task.get('task_id', task_path.name)
            result['task_type'] = task.get('task_type', 'Unknown')

            # 检查input和golden文件
            input_path = task_path / task.get('input_workbook', 'input.xlsx')
            golden_path = task_path / task.get('golden_workbook', 'golden.xlsx')

            if not input_path.exists():
                result['passed'] = False
                result['issues'].append(f"Input文件不存在: {input_path.name}")

            if not golden_path.exists():
                result['passed'] = False
                result['issues'].append(f"Golden文件不存在: {golden_path.name}")

            if not result['passed']:
                return result

            # 2. 验证task.json结构
            self._validate_task_structure(task, result)

            # 3. S0门槛检查
            if not skip_s0:
                self._validate_s0_threshold(input_path, golden_path, result)

            # 4. 任务类型特定验证
            task_type = task.get('task_type')
            if task_type == 'FM':
                self._validate_fm_task(task, input_path, golden_path, result)
            elif task_type == 'Visualization':
                self._validate_visualization_task(task, result)

        except Exception as e:
            result['passed'] = False
            result['issues'].append(f"验证异常: {str(e)}")

        return result

    def _validate_task_structure(self, task: Dict, result: Dict):
        """验证task.json结构"""
        # 检查必填字段
        for field in self.REQUIRED_TASK_FIELDS:
            if field not in task:
                result['passed'] = False
                result['issues'].append(f"缺少必填字段: {field}")

        # 检查metadata必填字段
        metadata = task.get('metadata', {})
        for field in self.REQUIRED_METADATA_FIELDS:
            if field not in metadata:
                result['passed'] = False
                result['issues'].append(f"metadata缺少必填字段: {field}")

        # 检查路线标记
        if metadata.get('route') != 'A':
            result['passed'] = False
            result['issues'].append(f"route字段应为'A'，实际为'{metadata.get('route')}'")

        # 检查任务类型
        task_type = task.get('task_type')
        if task_type not in self.VALID_TASK_TYPES:
            result['passed'] = False
            result['issues'].append(f"无效的task_type: {task_type}")

        # 检查难度
        difficulty = task.get('difficulty')
        if difficulty not in self.VALID_DIFFICULTIES:
            result['passed'] = False
            result['issues'].append(f"无效的difficulty: {difficulty}")

        # 检查criteria非空
        criteria = task.get('criteria', [])
        if not criteria or len(criteria) == 0:
            result['passed'] = False
            result['issues'].append("criteria为空")

        # 检查answer_position非空
        answer_position = task.get('answer_position', [])
        if not answer_position or len(answer_position) == 0:
            result['passed'] = False
            result['issues'].append("answer_position为空")

    def _validate_s0_threshold(
        self,
        input_path: Path,
        golden_path: Path,
        result: Dict
    ):
        """S0门槛检查"""
        logger.info("  执行S0门槛检查...")

        # 检查input
        input_result = self.wb_validator.validate(input_path)
        if not input_result.passed:
            result['passed'] = False
            for error in input_result.errors:
                result['issues'].append(f"Input S0检查: {error}")

        # 检查golden
        golden_result = self.wb_validator.validate(golden_path)
        if not golden_result.passed:
            result['passed'] = False
            for error in golden_result.errors:
                result['issues'].append(f"Golden S0检查: {error}")

    def _validate_fm_task(
        self,
        task: Dict,
        input_path: Path,
        golden_path: Path,
        result: Dict
    ):
        """FM任务特定验证"""
        logger.info("  验证FM任务特定要求...")

        # 检查concepts字段
        concepts = task.get('metadata', {}).get('concepts', [])
        if not concepts or len(concepts) == 0:
            result['passed'] = False
            result['issues'].append("FM任务metadata.concepts不能为空")

        # 检查难度范围
        difficulty = task.get('difficulty')
        if difficulty not in ['L3', 'L4']:
            result['issues'].append(f"警告: FM任务难度建议为L3-L4，当前为{difficulty}")

        # TODO: 唯一解验证（需要S1元数据）
        # validation_result = self.solution_validator.validate(task, metadata={})
        # if not validation_result['has_unique_solution']:
        #     result['passed'] = False
        #     result['issues'].append("唯一解验证失败")

    def _validate_visualization_task(self, task: Dict, result: Dict):
        """Visualization任务特定验证"""
        logger.info("  验证Visualization任务特定要求...")

        # 检查visualization_criteria字段
        viz_criteria = task.get('visualization_criteria', [])
        if not viz_criteria or len(viz_criteria) == 0:
            result['passed'] = False
            result['issues'].append("Visualization任务缺少visualization_criteria字段")
            return

        # 验证每个criterion结构
        for idx, criterion in enumerate(viz_criteria):
            if 'criterion' not in criterion:
                result['passed'] = False
                result['issues'].append(f"visualization_criteria[{idx}]缺少criterion字段")

            if 'tier' not in criterion:
                result['passed'] = False
                result['issues'].append(f"visualization_criteria[{idx}]缺少tier字段")

            tier = criterion.get('tier')
            if tier not in [1, 2]:
                result['passed'] = False
                result['issues'].append(f"visualization_criteria[{idx}] tier必须为1或2")


def main():
    parser = argparse.ArgumentParser(description='验证路线A任务批次')
    parser.add_argument(
        '--task-dir',
        type=Path,
        required=True,
        help='任务目录路径'
    )
    parser.add_argument(
        '--output-report',
        type=Path,
        default=Path('batch_validation_report.json'),
        help='输出报告路径'
    )
    parser.add_argument(
        '--skip-s0',
        action='store_true',
        help='跳过S0门槛检查（快速验证模式）'
    )

    args = parser.parse_args()

    if not args.task_dir.exists():
        logger.error(f"任务目录不存在: {args.task_dir}")
        return 1

    # 执行验证
    validator = RouteABatchValidator()
    report = validator.validate_batch(args.task_dir, skip_s0=args.skip_s0)

    # 保存报告
    with open(args.output_report, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info(f"\n报告已保存到: {args.output_report}")

    # 返回状态码
    return 0 if report['fail_count'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
