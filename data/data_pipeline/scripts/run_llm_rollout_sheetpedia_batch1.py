#!/usr/bin/env python3
"""
LLM Rollout —— sheetpedia_batch1 (S3筛选通过) 批量跑轨迹

对generated_tasks/route_b_sheetpedia_batch1/passed/{debugging,template}下
S3筛选通过的71个任务，用LLMRolloutGenerator真实调用API跑rollout，
产出格式/流程与run_llm_rollout_batch_test.py完全一致，只是任务池换成
本批次筛选通过的71个任务，输出目录单独一份，不与其他批次互相覆盖。

用法:
    python3 scripts/run_llm_rollout_sheetpedia_batch1.py --count 71 --seed 42 --concurrency 4
"""

import argparse
import json
import logging
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import LLM_ROLLOUT_CONFIG, PROJECT_ROOT
from rollout.llm_rollout_generator import LLMRolloutGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GEN_DIR = PROJECT_ROOT / "generated_tasks" / "route_b_sheetpedia_batch1" / "passed"
RUNS_DIR = PROJECT_ROOT / "trajectories" / "llm_rollout_runs"


def load_all_tasks(seed: int):
    """全量加载本批次S3筛选通过的任务，不做抽样——本批次本身就是完整任务池。"""
    debugging = sorted((GEN_DIR / "debugging").glob("*.json"))
    template = sorted((GEN_DIR / "template").glob("*.json"))
    picked = debugging + template
    random.Random(seed).shuffle(picked)
    return picked


def run_one(task_json_path: Path, out_dir: Path) -> dict:
    generator = LLMRolloutGenerator()
    record = {"task_id": task_json_path.stem, "task_json": str(task_json_path)}
    start = time.time()
    try:
        result = generator.generate(task_json_path=task_json_path, output_dir=out_dir)
        trajectory_path = Path(result["trajectory_path"])
        with open(trajectory_path, "r", encoding="utf-8") as f:
            traj = json.load(f)
        record.update(
            {
                "success": traj["rollout_success"],
                "error": traj["rollout_error"],
                "total_steps": traj["context_stats"]["total_steps"],
                "view_xlsx_calls": traj["context_stats"]["view_xlsx_calls"],
                "bash_calls": traj["context_stats"]["bash_calls"],
                "execution_errors": traj["context_stats"]["execution_errors"],
                "trajectory_path": str(trajectory_path),
            }
        )
    except Exception as e:
        record.update({"success": False, "error": f"exception: {e}"})
    record["duration_sec"] = round(time.time() - start, 1)
    logger.info(
        f"[{'OK' if record.get('success') else 'FAIL'}] {record['task_id']} "
        f"steps={record.get('total_steps')} dur={record['duration_sec']}s err={record.get('error')}"
    )
    return record


def main():
    parser = argparse.ArgumentParser(description="LLM Rollout —— sheetpedia_batch1批量跑（全量，无抽样）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（仅用于打乱任务处理顺序）")
    parser.add_argument("--concurrency", type=int, default=4, help="并发数")
    args = parser.parse_args()

    tasks = load_all_tasks(args.seed)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_name = f"{timestamp}_{LLM_ROLLOUT_CONFIG['model']}_seed{args.seed}_n{len(tasks)}_sheetpedia_batch1"
    out_dir = RUNS_DIR / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"全量加载{len(tasks)}个任务: {[t.stem for t in tasks]}")
    logger.info(f"本次轨迹输出目录: {out_dir}")

    records = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_one, t, out_dir): t for t in tasks}
        for future in as_completed(futures):
            records.append(future.result())

    succeeded = [r for r in records if r.get("success")]
    durations = [r["duration_sec"] for r in records]
    steps = [r.get("total_steps", 0) for r in records if r.get("total_steps") is not None]

    summary = {
        "model": LLM_ROLLOUT_CONFIG["model"],
        "seed": args.seed,
        "total": len(records),
        "succeeded": len(succeeded),
        "success_rate": round(len(succeeded) / len(records), 4) if records else 0.0,
        "avg_duration_sec": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "avg_total_steps": round(sum(steps) / len(steps), 1) if steps else 0.0,
        "records": records,
    }

    summary_path = out_dir / "batch_test_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info("=" * 80)
    logger.info(f"总数: {summary['total']}, 成功submit: {summary['succeeded']} ({summary['success_rate']:.1%})")
    logger.info(f"平均耗时: {summary['avg_duration_sec']}s, 平均步数: {summary['avg_total_steps']}")
    logger.info(f"摘要: {summary_path}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
