#!/usr/bin/env python3
"""
S4 批量轨迹生成脚本

处理多个通过S3筛选的任务，为每个任务生成LLM rollout轨迹。

用法:
    python batch_generate_trajectories.py <task_dir> --output <output_dir>

任务目录结构:
    task_dir/
        task1.json
        task1_input.xlsx
        task1_golden.xlsx
        task2.json
        task2_input.xlsx
        task2_golden.xlsx
        ...

输出结构:
    output_dir/
        task1__oracle_v1.json
        task2__oracle_v1.json
        ...
        generation_report.json
"""

import sys
import json
import logging
from pathlib import Path
from typing import List, Dict
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rollout.llm_rollout_generator import LLMRolloutGenerator
from rollout.golden_leak_detector import GoldenLeakDetector
from rollout.scaffold_aligner import ScaffoldAligner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def find_task_files(task_dir: Path) -> List[Path]:
    """找到所有任务JSON文件"""
    task_files = []
    for json_file in task_dir.glob("*.json"):
        # 跳过非任务文件
        if json_file.name.endswith("_report.json"):
            continue
        if json_file.name.startswith("generation_"):
            continue
        task_files.append(json_file)
    
    return sorted(task_files)


def validate_task_files(task_json: Path) -> Dict:
    """验证任务文件及其关联的input/golden文件"""
    with open(task_json, 'r', encoding='utf-8') as f:
        task = json.load(f)
    
    task_id = task.get('task_id')
    input_path = task.get('input_path')
    golden_path = task.get('golden_path')
    
    issues = []
    
    if not task_id:
        issues.append("Missing task_id field")
    
    if not input_path or not Path(input_path).exists():
        issues.append(f"Input file not found: {input_path}")
    
    if not golden_path or not Path(golden_path).exists():
        issues.append(f"Golden file not found: {golden_path}")
    
    return {
        'valid': len(issues) == 0,
        'issues': issues,
        'task_id': task_id,
        'task_type': task.get('type', 'Unknown')
    }


def generate_trajectory(
    task_json: Path,
    output_dir: Path,
    generator: LLMRolloutGenerator
) -> Dict:
    """为单个任务生成轨迹并验证"""
    task_id = task_json.stem
    logger.info(f"\n{'='*80}")
    logger.info(f"Processing: {task_id}")
    logger.info(f"{'='*80}")
    
    result = {
        'task_id': task_id,
        'task_json': str(task_json),
        'success': False,
        'trajectory_path': None,
        'steps': None,
        'errors': [],
        'validation': {
            'golden_leak': None,
            'scaffold_align': None
        }
    }
    
    try:
        # 1. 生成轨迹
        logger.info("Step 1: Generating LLM rollout trajectory...")
        rollout_result = generator.generate(
            task_json_path=task_json,
            output_dir=output_dir,
            sample_id=task_id
        )

        trajectory_path = Path(rollout_result['trajectory_path'])
        result['trajectory_path'] = str(trajectory_path)
        result['steps'] = rollout_result.get('total_steps', 0)
        
        logger.info(f"  ✓ Generated: {trajectory_path.name}")
        logger.info(f"  ✓ Steps: {result['steps']}")
        
        # 2. Golden泄漏检测
        logger.info("Step 2: Checking for golden leakage...")
        detector = GoldenLeakDetector()
        findings = detector.detect(trajectory_path)
        leak_report = detector.generate_report(findings)
        
        result['validation']['golden_leak'] = {
            'passed': leak_report['passed'],
            'total_findings': leak_report['total_findings'],
            'by_severity': leak_report['by_severity']
        }
        
        if leak_report['passed']:
            logger.info(f"  ✓ Golden Leak: PASS")
        else:
            logger.warning(f"  ✗ Golden Leak: FAIL (High={leak_report['by_severity']['high']})")
            result['errors'].append(f"Golden leak detected: {leak_report['by_severity']['high']} high-risk findings")
        
        # 3. Scaffold对齐检查
        logger.info("Step 3: Checking scaffold alignment...")
        aligner = ScaffoldAligner()
        issues = aligner.check(trajectory_path)
        align_report = aligner.generate_report(issues)
        
        result['validation']['scaffold_align'] = {
            'passed': align_report['passed'],
            'total_issues': align_report['total_issues'],
            'by_severity': align_report['by_severity']
        }
        
        if align_report['passed']:
            logger.info(f"  ✓ Scaffold Align: PASS")
        else:
            logger.warning(f"  ✗ Scaffold Align: FAIL (Errors={align_report['by_severity']['error']})")
            result['errors'].append(f"Scaffold alignment failed: {align_report['by_severity']['error']} errors")
        
        # 判断是否成功
        result['success'] = (
            leak_report['passed'] and 
            align_report['passed'] and
            len(result['errors']) == 0
        )
        
        if result['success']:
            logger.info(f"✓ SUCCESS: {task_id}")
        else:
            logger.warning(f"✗ FAILED: {task_id}")
        
    except Exception as e:
        logger.error(f"✗ ERROR: {task_id}")
        logger.error(f"  {str(e)}")
        result['errors'].append(str(e))
    
    return result


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Batch generate oracle trajectories")
    parser.add_argument('task_dir', type=Path, help="Directory containing task JSON files")
    parser.add_argument('--output', type=Path, required=True, help="Output directory for trajectories")
    parser.add_argument('--max-tasks', type=int, help="Maximum number of tasks to process")
    
    args = parser.parse_args()
    
    # 验证输入目录
    if not args.task_dir.exists():
        logger.error(f"Task directory not found: {args.task_dir}")
        sys.exit(1)
    
    # 创建输出目录
    args.output.mkdir(parents=True, exist_ok=True)
    
    # 查找任务文件
    logger.info(f"Scanning task directory: {args.task_dir}")
    task_files = find_task_files(args.task_dir)
    
    if args.max_tasks:
        task_files = task_files[:args.max_tasks]
    
    logger.info(f"Found {len(task_files)} task(s)")
    
    if not task_files:
        logger.warning("No task files found")
        sys.exit(0)
    
    # 验证任务文件
    logger.info("\nValidating task files...")
    valid_tasks = []
    invalid_tasks = []
    
    for task_file in task_files:
        validation = validate_task_files(task_file)
        if validation['valid']:
            valid_tasks.append(task_file)
            logger.info(f"  ✓ {task_file.name} ({validation['task_type']})")
        else:
            invalid_tasks.append((task_file, validation['issues']))
            logger.warning(f"  ✗ {task_file.name}: {', '.join(validation['issues'])}")
    
    logger.info(f"\nValid tasks: {len(valid_tasks)}/{len(task_files)}")
    
    if not valid_tasks:
        logger.error("No valid tasks to process")
        sys.exit(1)
    
    # 批量生成轨迹
    logger.info("\n" + "="*80)
    logger.info("Starting batch trajectory generation")
    logger.info("="*80)
    
    generator = LLMRolloutGenerator()
    results = []

    for idx, task_file in enumerate(valid_tasks, 1):
        logger.info(f"\nTask {idx}/{len(valid_tasks)}")
        result = generate_trajectory(task_file, args.output, generator)
        results.append(result)
    
    # 生成汇总报告
    logger.info("\n" + "="*80)
    logger.info("Generation Summary")
    logger.info("="*80)
    
    success_count = sum(1 for r in results if r['success'])
    fail_count = len(results) - success_count
    
    logger.info(f"Total tasks: {len(results)}")
    logger.info(f"  Success: {success_count}")
    logger.info(f"  Failed: {fail_count}")
    
    if fail_count > 0:
        logger.info("\nFailed tasks:")
        for r in results:
            if not r['success']:
                logger.info(f"  - {r['task_id']}: {', '.join(r['errors'])}")
    
    # 保存报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'task_dir': str(args.task_dir),
        'output_dir': str(args.output),
        'total_tasks': len(results),
        'success_count': success_count,
        'fail_count': fail_count,
        'results': results
    }
    
    report_path = args.output / 'generation_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\nReport saved: {report_path}")
    logger.info("="*80)


if __name__ == "__main__":
    main()
