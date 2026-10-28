#!/usr/bin/env python3
"""
批量测试Debugging生成器在多个demo文件上的表现

测试所有15个demo文件，每个文件生成2-3个不同类型的任务
"""

import sys
from pathlib import Path

# 添加项目根目录到path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from generate.transform.debugging_generator import DebuggingGenerator
from config import DEBUGGING_ERROR_TYPES

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


def batch_test_demo_files():
    """批量测试所有demo文件"""
    
    demo_dir = Path("/mnt/hhq/data/files_demo")
    output_dir = Path("/tmp/debugging_batch_test")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 获取所有demo文件
    demo_files = sorted(demo_dir.glob("*.xlsx"))
    
    logger.info("=" * 80)
    logger.info("Debugging生成器批量测试")
    logger.info("=" * 80)
    logger.info(f"Demo文件数: {len(demo_files)}")
    logger.info(f"输出目录: {output_dir}")
    logger.info("")
    
    generator = DebuggingGenerator(seed=42)
    
    success_count = 0
    total_tasks = 0
    total_errors_injected = 0
    
    for demo_file in demo_files:
        logger.info(f"处理: {demo_file.name}")
        
        try:
            # 每个文件生成2个任务，使用不同的错误类型
            for i, error_type in enumerate(DEBUGGING_ERROR_TYPES[:2]):
                task = generator.generate(
                    golden_path=demo_file,
                    output_dir=output_dir,
                    error_type=error_type
                )
                
                # 导出JSON
                json_path = output_dir / f"{task.task_id}.json"
                generator.export_task_json(task, json_path)
                
                logger.info(f"  ✓ {error_type}: {len(task.injected_errors)}个错误")
                
                total_tasks += 1
                total_errors_injected += len(task.injected_errors)
                
            success_count += 1
            
        except Exception as e:
            logger.error(f"  ✗ 失败: {e}")
        
        logger.info("")
    
    # 打印总结
    logger.info("=" * 80)
    logger.info("批量测试总结")
    logger.info("=" * 80)
    logger.info(f"成功处理: {success_count}/{len(demo_files)} 文件")
    logger.info(f"生成任务: {total_tasks} 个")
    logger.info(f"注入错误: {total_errors_injected} 个")
    logger.info(f"平均错误/任务: {total_errors_injected/total_tasks:.1f}")
    logger.info(f"输出目录: {output_dir}")
    logger.info("=" * 80)
    
    return success_count == len(demo_files)


if __name__ == "__main__":
    success = batch_test_demo_files()
    sys.exit(0 if success else 1)
