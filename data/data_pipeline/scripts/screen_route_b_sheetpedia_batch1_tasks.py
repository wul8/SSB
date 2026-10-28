#!/usr/bin/env python3
"""
Route B S3 筛选 —— sheetpedia_batch1语料专用

对generate_route_b_sheetpedia_batch1_tasks.py产出的104个task JSON做S3筛选
（唯一解校验 + 真实污染扫描 + 难度校验），复用run_route_b_e2e.py里的screen_tasks逻辑，
输出目录换成generated_tasks/route_b_sheetpedia_batch1/，跟其他批次的产物互不覆盖。

用法:
    python3 scripts/screen_route_b_sheetpedia_batch1_tasks.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from config import PROJECT_ROOT
from run_route_b_e2e import screen_tasks  # 复用S3逻辑

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GEN_DIR = PROJECT_ROOT / "generated_tasks" / "route_b_sheetpedia_batch1"


def main():
    # screen_tasks()里写死了GEN_DIR为route_b_e2e的目录，这里通过monkeypatch重定向到本脚本自己的输出目录
    import run_route_b_e2e as e2e_mod
    e2e_mod.GEN_DIR = GEN_DIR

    debugging_jsons = sorted((GEN_DIR / "debugging").glob("*.json"))
    template_jsons = sorted((GEN_DIR / "template").glob("*.json"))
    task_jsons = {"debugging": debugging_jsons, "template": template_jsons}

    logger.info("=" * 80)
    logger.info("Route B S3 筛选 —— sheetpedia_batch1")
    logger.info(f"待筛选: Debugging={len(debugging_jsons)}, Template={len(template_jsons)}")
    logger.info("=" * 80)

    report, passed_paths = screen_tasks(task_jsons)

    logger.info("=" * 80)
    logger.info(f"总数: {report['total']}")
    logger.info(f"通过: {report['passed']} ({report['pass_rate']:.1%})")
    logger.info(f"污染扫描: {'启用' if report['contamination_checked'] else '跳过(官方数据集路径不存在)'}")
    logger.info(f"报告: {GEN_DIR / 'screening_report.json'}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
