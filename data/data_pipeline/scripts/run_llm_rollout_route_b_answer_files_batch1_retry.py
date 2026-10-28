#!/usr/bin/env python3
"""
LLM Rollout for route_b_answer_files_batch1 - 重试失败的任务

从上一次rollout的summary中提取失败的任务，重新跑rollout。
"""

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import LLM_ROLLOUT_CONFIG, PROJECT_ROOT
from rollout.llm_rollout_generator import LLMRolloutGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PREV_SUMMARY = PROJECT_ROOT / "trajectories" / "llm_rollout_runs" / "route_b_answer_files_batch1_20260904_164020_deepseek-v4-pro" / "rollout_summary.json"
RUNS_DIR = PROJECT_ROOT / "trajectories" / "llm_rollout_runs"


def load_failed_tasks():
    """从上次的summary中加载失败任务的路径"""
    with open(PREV_SUMMARY, 'r') as f:
        data = json.load(f)

    failed_tasks = [Path(r['task_json']) for r in data['records'] if not r['success']]
    logger.info(f"从 {PREV_SUMMARY.name} 加载了 {len(failed_tasks)} 个失败任务")
    return failed_tasks


def run_one(task_json_path: Path, out_dir: Path) -> dict:
    """运行单个任务的rollout"""
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
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_name = f"route_b_answer_files_batch1_retry_{timestamp}_{LLM_ROLLOUT_CONFIG['model']}"
    out_dir = RUNS_DIR / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = load_failed_tasks()
    logger.info(f"开始重试 {len(tasks)} 个失败任务")
    logger.info(f"模型: {LLM_ROLLOUT_CONFIG['model']}, max_turns: {LLM_ROLLOUT_CONFIG['max_turns']}")
    logger.info(f"输出目录: {out_dir}")

    records = []
    concurrency = 10
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(run_one, t, out_dir): t for t in tasks}
        for future in as_completed(futures):
            records.append(future.result())

    succeeded = [r for r in records if r.get("success")]
    durations = [r["duration_sec"] for r in records]
    steps = [r.get("total_steps", 0) for r in records if r.get("total_steps") is not None]

    summary = {
        "batch_name": "route_b_answer_files_batch1_retry",
        "model": LLM_ROLLOUT_CONFIG["model"],
        "max_turns": LLM_ROLLOUT_CONFIG["max_turns"],
        "concurrency": concurrency,
        "total": len(records),
        "succeeded": len(succeeded),
        "success_rate": round(len(succeeded) / len(records), 4) if records else 0.0,
        "avg_duration_sec": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "avg_total_steps": round(sum(steps) / len(steps), 1) if steps else 0.0,
        "records": records,
    }

    summary_path = out_dir / "rollout_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info("=" * 80)
    logger.info(f"总数: {summary['total']}, 成功submit: {summary['succeeded']} ({summary['success_rate']:.1%})")
    logger.info(f"平均耗时: {summary['avg_duration_sec']}s, 平均步数: {summary['avg_total_steps']}")
    logger.info(f"摘要: {summary_path}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
