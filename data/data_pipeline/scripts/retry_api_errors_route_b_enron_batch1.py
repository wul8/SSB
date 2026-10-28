#!/usr/bin/env python3
"""重试route_b_enron_batch1中API错误的任务"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import PROJECT_ROOT
from rollout.llm_rollout_generator import LLMRolloutGenerator
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 从之前的summary中提取API错误的任务
API_ERROR_TASKS = [
    "090_090_native_000%2F3.856086.JLPFOPG0F4BPEFELS5NZXITPCEGADPMUA.1_template_5272",
    "113_113_native_000%2F3.608919.KWHEWURXOW1YYTGFLG4UPEYFNPXWNO03B.1_embedded_hardcodes_3442",
    "114_114_native_000%2F3.397462.GG51BQVHFLRWZUYFB23NDBPBPABZOBMJA.5_relative_vs_absolute_references_3088",
    "185_171_native_000%2F3.838964.LYZAHIZF31IWI0KDUKF3EM5GLKYH15PTB.1_template_2124",
    "107_107_native_000%2F3.659576.AIXD0I0MUYLID35GRCVSTYYV0URFHU4YB.1_incorrect_average_6464",
    "184_169_native_000%2F3.215915.PBVPSKNRY5IKM035ENIQN3TSCPVGZOCJA.1_cross-sheet_references_6529",
    "114_114_native_000%2F3.397462.GG51BQVHFLRWZUYFB23NDBPBPABZOBMJA.5_template_6974",
    "134_134_darron_c_giron_002_1_1_1.pst.143_template_4114",
    "030_030_kevin_hyatt_000_1_1.pst.20_template_7916",
    "127_127_native_000%2F3.681387.OSUCK3YZZ2AEHSNV3YTOP0BAUXL1QCERB.1_template_9785",
    "065_065_native_000%2F3.473691.CTWZJVY0QYOQMJV1COG3Q02Z1I3UHJTUB.1_template_4981",
    "148_148_native_000%2F3.659575.MG2OC1GX53URCTS3WXSPNEPX11N4FZ1FA.1_template_1757",
    "072_072_native_000%2F3.555534.NRU3IBHC0XHWV0U01IBX3U2ZD2BDGC1GB.1_template_4006",
    "001_001_native_003%2F3.349924.HJNYPWWU3PUVGTITH4NO2OZ54AXSHEY5B.2_double_counting_4657",
    "123_123_native_000%2F3.306479.LC2JADU1A5PC4LSX2FQSIPVHQVUFPU4QB.1_template_6728",
    "071_071_native_000%2F3.554747.FJBMW0GBODIS4PTH4KYHKL21JPW4BCHTA.1_template_2790",
    "123_123_native_000%2F3.306479.LC2JADU1A5PC4LSX2FQSIPVHQVUFPU4QB.1_errors_7745",
    "065_065_native_000%2F3.473691.CTWZJVY0QYOQMJV1COG3Q02Z1I3UHJTUB.1_embedded_hardcodes_8953",
    "023_023_native_000%2F3.400087.JHS21UTD2AT1YVAYI0KCYX2CVLJDAN1SB.1_template_6313",
    "177_139_richard_sanders_001_1_1_1.pst.0_template_2375",
    "087_087_native_000%2F3.815725.DTW4IFJT2Q3S0H3ERX3LO5NH5I5WYYW5B.2_template_4853",
    "176_136_native_000%2F3.837360.D0Z4JQEVGFRJ2YB0GH3SPHH3DQSPLTHGA.1_template_8657",
]

GEN_DIR = PROJECT_ROOT / "generated_tasks" / "route_b_enron_batch1" / "passed"

def find_task_json(task_id: str) -> Path:
    """根据task_id查找对应的json文件"""
    for subdir in ["debugging", "template"]:
        task_path = GEN_DIR / subdir / f"{task_id}.json"
        if task_path.exists():
            return task_path
    raise FileNotFoundError(f"Task {task_id} not found in {GEN_DIR}")

def process_one_task(task_id: str, generator: LLMRolloutGenerator, output_dir: Path):
    """处理单个任务"""
    try:
        task_json_path = find_task_json(task_id)
        logger.info(f"Processing {task_id}")
        result = generator.generate(
            task_json_path=str(task_json_path),
            output_dir=output_dir,
            sample_id=task_id
        )

        # generate返回: {"trajectory_path": ..., "total_steps": ...}
        # 需要读取trajectory文件判断是否成功
        trajectory_path = result.get("trajectory_path")
        if trajectory_path and Path(trajectory_path).exists():
            with open(trajectory_path, "r") as f:
                trajectory = json.load(f)

            answer_submitted = trajectory.get("answer_submitted", False)
            if answer_submitted:
                logger.info(f"[OK] {task_id} steps={result.get('total_steps', 0)}")
                return {"success": True, "task_id": task_id, "result": result}
            else:
                error = trajectory.get("error_message", "no answer submitted")
                logger.info(f"[FAIL] {task_id} err={error}")
                return {"success": False, "task_id": task_id, "error": error}
        else:
            logger.info(f"[FAIL] {task_id} err=no trajectory file")
            return {"success": False, "task_id": task_id, "error": "no trajectory file"}
    except Exception as e:
        logger.error(f"[FAIL] {task_id} exception: {e}")
        return {"success": False, "error": str(e), "task_id": task_id}

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"route_b_enron_batch1_retry_{timestamp}_deepseek-v4-pro"

    generator = LLMRolloutGenerator(
        model="deepseek-v4-pro"
    )
    generator.output_dir = PROJECT_ROOT / "trajectories" / "llm_rollout_runs" / run_name
    generator.output_dir.mkdir(parents=True, exist_ok=True)
    generator.max_turns = 100

    logger.info(f"Starting retry for {len(API_ERROR_TASKS)} API error tasks")
    logger.info(f"Run name: {run_name}")

    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_task = {
            executor.submit(process_one_task, task_id, generator, generator.output_dir): task_id
            for task_id in API_ERROR_TASKS
        }

        for future in as_completed(future_to_task):
            task_id = future_to_task[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logger.error(f"Task {task_id} generated exception: {e}")
                results.append({"success": False, "error": str(e), "task_id": task_id})

    # 汇总统计
    succeeded = sum(1 for r in results if r.get("success"))
    logger.info("=" * 80)
    logger.info(f"总数: {len(results)}, 成功submit: {succeeded} ({succeeded/len(results)*100:.1f}%)")

    # 保存summary
    summary_path = generator.output_dir / "rollout_summary.json"
    summary_data = {
        "batch_name": "route_b_enron_batch1_retry",
        "model": "deepseek-v4-pro",
        "max_turns": 100,
        "concurrency": 5,
        "total": len(results),
        "succeeded": succeeded,
        "success_rate": succeeded / len(results),
        "records": results
    }

    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)

    logger.info(f"摘要: {summary_path}")
    logger.info("=" * 80)

if __name__ == "__main__":
    main()
