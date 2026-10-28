#!/usr/bin/env python3
"""
LLM Rollout 失败任务重跑脚本

从一次批量跑的batch_test_summary.json里挑出success=false的任务，用当前
config.py里的LLM_ROLLOUT_CONFIG（通常是刚调大过max_turns之后）重新rollout，
原地覆盖同一个run_dir下的轨迹json/verify_bundle，并把结果合并回summary。

用法:
    python3 scripts/rerun_llm_rollout_failed.py \
        trajectories/llm_rollout_runs/20260828_153039_deepseek-v4-pro_seed42_n200 \
        --concurrency 5
"""

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from run_llm_rollout_batch_test import run_one  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="重跑一次批量rollout中失败的任务")
    parser.add_argument("run_dir", type=Path, help="之前那次批量的输出目录")
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()

    summary_path = args.run_dir / "batch_test_summary.json"
    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    failed = [r for r in summary["records"] if not r.get("success")]
    logger.info(f"待重跑失败任务: {len(failed)}个")
    if not failed:
        logger.info("没有失败任务，无需重跑")
        return

    tasks = [Path(r["task_json"]) for r in failed]
    by_task_id = {r["task_id"]: r for r in summary["records"]}

    new_records = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_one, t, args.run_dir): t for t in tasks}
        for future in as_completed(futures):
            new_records.append(future.result())

    for r in new_records:
        by_task_id[r["task_id"]] = r

    merged_records = list(by_task_id.values())
    succeeded = [r for r in merged_records if r.get("success")]
    durations = [r["duration_sec"] for r in merged_records]
    steps = [r.get("total_steps", 0) for r in merged_records if r.get("total_steps") is not None]

    summary.update(
        {
            "total": len(merged_records),
            "succeeded": len(succeeded),
            "success_rate": round(len(succeeded) / len(merged_records), 4) if merged_records else 0.0,
            "avg_duration_sec": round(sum(durations) / len(durations), 1) if durations else 0.0,
            "avg_total_steps": round(sum(steps) / len(steps), 1) if steps else 0.0,
            "records": merged_records,
        }
    )
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    newly_succeeded = [r for r in new_records if r.get("success")]
    logger.info("=" * 80)
    logger.info(f"重跑{len(new_records)}个失败任务, 新成功submit: {len(newly_succeeded)}")
    logger.info(f"合并后总数: {summary['total']}, 成功submit: {summary['succeeded']} ({summary['success_rate']:.1%})")
    logger.info(f"摘要: {summary_path}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
