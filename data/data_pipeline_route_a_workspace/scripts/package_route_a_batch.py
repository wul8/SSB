#!/usr/bin/env python3
"""
路线A任务打包和提交工具

将专家标注的任务打包为标准格式，准备提交到主pipeline。

功能:
1. 验证任务批次
2. 生成任务索引
3. 打包为统一格式
4. 生成提交报告

Usage:
    python package_route_a_batch.py \
        --task-dir /path/to/tasks \
        --output-dir /path/to/output \
        --batch-id batch_001
"""

import argparse
import json
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RouteAPackager:
    """路线A任务打包器"""

    def __init__(self):
        pass

    def package_batch(
        self,
        task_dir: Path,
        output_dir: Path,
        batch_id: str,
        validation_report: Optional[Path] = None
    ) -> Dict:
        """
        打包任务批次

        Args:
            task_dir: 任务源目录
            output_dir: 输出目录
            batch_id: 批次ID
            validation_report: 验证报告路径（可选）

        Returns:
            打包报告
        """
        logger.info(f"开始打包批次: {batch_id}")
        logger.info("="*80)

        # 创建输出目录
        batch_output = output_dir / batch_id
        batch_output.mkdir(parents=True, exist_ok=True)

        # 扫描任务
        tasks = self._scan_tasks(task_dir)
        logger.info(f"找到 {len(tasks)} 个任务")

        # 检查验证报告
        validated_tasks = set()
        if validation_report and validation_report.exists():
            with open(validation_report) as f:
                report = json.load(f)
                validated_tasks = {
                    r['task_id'] for r in report['results']
                    if r['passed']
                }
            logger.info(f"验证报告: {len(validated_tasks)} 个任务通过验证")

        # 打包每个任务
        packaged = []
        skipped = []

        for task_path in tasks:
            task_id = task_path.name

            # 如果有验证报告，只打包通过的任务
            if validation_report and task_id not in validated_tasks:
                skipped.append({
                    'task_id': task_id,
                    'reason': '未通过验证'
                })
                continue

            try:
                self._package_single_task(task_path, batch_output)
                packaged.append(task_id)
                logger.info(f"✓ 打包任务: {task_id}")
            except Exception as e:
                skipped.append({
                    'task_id': task_id,
                    'reason': str(e)
                })
                logger.error(f"✗ 打包失败: {task_id} - {e}")

        # 生成批次索引
        index = self._generate_batch_index(batch_output, packaged)
        index_path = batch_output / 'batch_index.json'
        with open(index_path, 'w') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

        # 生成打包报告
        report = {
            'timestamp': datetime.now().isoformat(),
            'batch_id': batch_id,
            'source_dir': str(task_dir),
            'output_dir': str(batch_output),
            'total_tasks': len(tasks),
            'packaged_count': len(packaged),
            'skipped_count': len(skipped),
            'packaged_tasks': packaged,
            'skipped_tasks': skipped,
            'index_path': str(index_path)
        }

        report_path = batch_output / 'packaging_report.json'
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info("\n" + "="*80)
        logger.info("打包完成")
        logger.info(f"总任务数: {len(tasks)}")
        logger.info(f"已打包: {len(packaged)}")
        logger.info(f"已跳过: {len(skipped)}")
        logger.info(f"输出目录: {batch_output}")
        logger.info(f"批次索引: {index_path}")
        logger.info(f"打包报告: {report_path}")

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

    def _package_single_task(self, task_path: Path, output_dir: Path):
        """打包单个任务"""
        # 读取task.json
        with open(task_path / 'task.json') as f:
            task = json.load(f)

        task_id = task['task_id']
        task_output = output_dir / task_id
        task_output.mkdir(parents=True, exist_ok=True)

        # 复制task.json
        shutil.copy(task_path / 'task.json', task_output / 'task.json')

        # 复制input和golden工作簿
        input_name = task['input_workbook']
        golden_name = task['golden_workbook']

        input_src = task_path / input_name
        golden_src = task_path / golden_name

        if not input_src.exists():
            raise FileNotFoundError(f"Input工作簿不存在: {input_name}")
        if not golden_src.exists():
            raise FileNotFoundError(f"Golden工作簿不存在: {golden_name}")

        # 标准化文件名
        shutil.copy(input_src, task_output / f"{task_id}_input.xlsx")
        shutil.copy(golden_src, task_output / f"{task_id}_golden.xlsx")

        # 更新task.json中的文件名
        task['input_workbook'] = f"{task_id}_input.xlsx"
        task['golden_workbook'] = f"{task_id}_golden.xlsx"

        with open(task_output / 'task.json', 'w') as f:
            json.dump(task, f, indent=2, ensure_ascii=False)

    def _generate_batch_index(
        self,
        batch_dir: Path,
        task_ids: List[str]
    ) -> Dict:
        """生成批次索引"""
        index = {
            'batch_id': batch_dir.name,
            'creation_date': datetime.now().isoformat(),
            'task_count': len(task_ids),
            'tasks': []
        }

        for task_id in task_ids:
            task_path = batch_dir / task_id / 'task.json'
            with open(task_path) as f:
                task = json.load(f)

            index['tasks'].append({
                'task_id': task_id,
                'task_type': task['task_type'],
                'difficulty': task['difficulty'],
                'domain': task.get('metadata', {}).get('domain', 'Unknown'),
                'generation_model': task.get('metadata', {}).get('generation_model', 'unknown'),
                'task_json': str(task_path.relative_to(batch_dir.parent))
            })

        return index


def main():
    parser = argparse.ArgumentParser(description='打包路线A任务批次')
    parser.add_argument(
        '--task-dir',
        type=Path,
        required=True,
        help='任务源目录'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        required=True,
        help='输出目录'
    )
    parser.add_argument(
        '--batch-id',
        type=str,
        required=True,
        help='批次ID（如batch_001）'
    )
    parser.add_argument(
        '--validation-report',
        type=Path,
        help='验证报告路径（只打包通过验证的任务）'
    )

    args = parser.parse_args()

    if not args.task_dir.exists():
        logger.error(f"任务目录不存在: {args.task_dir}")
        return 1

    # 创建输出目录
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 打包批次
    packager = RouteAPackager()
    report = packager.package_batch(
        args.task_dir,
        args.output_dir,
        args.batch_id,
        args.validation_report
    )

    return 0 if report['skipped_count'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
