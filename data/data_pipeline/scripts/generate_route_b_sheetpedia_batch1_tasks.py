#!/usr/bin/env python3
"""
Route B S2 任务生成 —— sheetpedia_batch1语料专用

只做S2：为corpus/sheetpedia_batch1/里通过S0入库的57个真实工作簿生成
Debugging任务 + Template任务两类task JSON，不做S3筛选、不做S4轨迹展开、
不调用任何LLM。复用run_route_b_e2e.py里已验证过的generate_tasks逻辑，
输出目录换成generated_tasks/route_b_sheetpedia_batch1/，跟其他批次的产物互不覆盖。

用法:
    python3 scripts/generate_route_b_sheetpedia_batch1_tasks.py --seed 42

输出:
    generated_tasks/route_b_sheetpedia_batch1/{debugging,template}/*.json + *_input.xlsx + *_golden.xlsx
    generated_tasks/route_b_sheetpedia_batch1/generation_summary.json
"""

import argparse
import json
import logging
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from config import PROJECT_ROOT
from run_route_b_e2e import generate_tasks  # 复用S2逻辑

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SOURCE_DIR = PROJECT_ROOT / "corpus" / "sheetpedia_batch1"
GEN_DIR = PROJECT_ROOT / "generated_tasks" / "route_b_sheetpedia_batch1"


def main():
    parser = argparse.ArgumentParser(description="Route B S2任务生成 —— sheetpedia_batch1语料（不筛选、不跑轨迹、不调用LLM）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    random.seed(args.seed)

    # generate_tasks()里写死了GEN_DIR为route_b_e2e的目录，这里通过monkeypatch重定向到本脚本自己的输出目录
    import run_route_b_e2e as e2e_mod
    e2e_mod.GEN_DIR = GEN_DIR

    GEN_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 80)
    logger.info("Route B S2 任务生成 —— sheetpedia_batch1")
    logger.info("=" * 80)

    sources = sorted(SOURCE_DIR.glob("*.xlsx"))
    logger.info(f"源工作簿(全部通过S0入库的sheetpedia_batch1): {len(sources)}")

    task_jsons, gen_errors = generate_tasks(sources, args.seed)

    summary = {
        "sources_total": len(sources),
        "debugging_generated": len(task_jsons["debugging"]),
        "template_generated": len(task_jsons["template"]),
        "generation_errors": len(gen_errors),
        "errors": gen_errors,
    }
    summary_path = GEN_DIR / "generation_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info("=" * 80)
    logger.info(f"源工作簿: {summary['sources_total']}")
    logger.info(f"Debugging任务: {summary['debugging_generated']}")
    logger.info(f"Template任务: {summary['template_generated']}")
    logger.info(f"生成失败: {summary['generation_errors']}")
    logger.info(f"摘要: {summary_path}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
