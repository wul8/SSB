#!/usr/bin/env python3
"""
Route B 端到端跑通脚本

串起 S2(生成) -> S3(筛选，含真实污染扫描) -> S4(oracle轨迹 + 真实执行produce output.xlsx)
-> S5(验证) 全流程，使用真实工作簿(files_demo + seed_workbooks抽样)，
产出项目级持久化产物，替代此前散落在/tmp/的一次性测试脚本。

用法:
    python scripts/run_route_b_e2e.py
    python scripts/run_route_b_e2e.py --seed-sample-count 15 --seed 42

输出:
    generated_tasks/route_b_e2e/{debugging,template}/*.json + *_input.xlsx + *_golden.xlsx
    generated_tasks/route_b_e2e/screening_report.json
    trajectories/route_b_e2e/{task_id}/{task.json,input.xlsx,golden.xlsx,output.xlsx}
    trajectories/route_b_e2e/verification_report.json
    trajectories/route_b_e2e/e2e_summary.json
"""

import argparse
import json
import logging
import random
import shutil
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DEBUGGING_ERROR_TYPES, PROJECT_ROOT
from generate.transform.debugging_generator import DebuggingGenerator
from generate.transform.template_generator import TemplateGenerator
from screen.task_screener import TaskScreener
from screen.unique_solution_validator import UniqueSolutionValidator
from screen.contamination_scanner import ContaminationScanner
from rollout.llm_rollout_generator import LLMRolloutGenerator
from rollout.golden_leak_detector import GoldenLeakDetector
from rollout.scaffold_aligner import ScaffoldAligner
from rollout.trajectory_executor import TrajectoryExecutor
from verify.trajectory_verifier import TrajectoryVerifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

FILES_DEMO_DIR = Path("/mnt/hhq/data/files_demo")
SEED_WORKBOOKS_DIR = PROJECT_ROOT / "corpus" / "seed_workbooks"
OFFICIAL_DATASET_PATH = Path(
    "/mnt/hhq/Benchmark/SpreadsheetBench-2-505b/data/spreadsheetbench-v2"
)

GEN_DIR = PROJECT_ROOT / "generated_tasks" / "route_b_e2e"
TRAJ_DIR = PROJECT_ROOT / "trajectories" / "route_b_e2e"


def collect_source_workbooks(seed_sample_count: int, seed: int) -> List[Path]:
    """files_demo全量 + seed_workbooks随机抽样"""
    demo_files = sorted(FILES_DEMO_DIR.glob("*.xlsx"))

    seed_files = sorted(SEED_WORKBOOKS_DIR.glob("*.xlsx"))
    rng = random.Random(seed)
    if seed_sample_count < len(seed_files):
        seed_files = rng.sample(seed_files, seed_sample_count)

    sources = demo_files + seed_files
    logger.info(
        f"收集源工作簿: files_demo={len(demo_files)}, seed_workbooks抽样={len(seed_files)}, "
        f"合计={len(sources)}"
    )
    return sources


def generate_tasks(sources: List[Path], seed: int) -> Dict[str, List[Path]]:
    """为每个源工作簿生成1个Debugging任务 + (若有公式)1个Template任务"""
    debugging_dir = GEN_DIR / "debugging"
    template_dir = GEN_DIR / "template"
    debugging_dir.mkdir(parents=True, exist_ok=True)
    template_dir.mkdir(parents=True, exist_ok=True)

    debugging_gen = DebuggingGenerator(seed=seed)
    template_gen = TemplateGenerator(seed=seed)

    task_jsons = {"debugging": [], "template": []}
    gen_errors = []

    for src in sources:
        error_type = random.choice(DEBUGGING_ERROR_TYPES)
        try:
            task = debugging_gen.generate(
                golden_path=src, output_dir=debugging_dir, error_type=error_type
            )
            json_path = debugging_dir / f"{task.task_id}.json"
            debugging_gen.export_task_json(task, json_path)
            task_jsons["debugging"].append(json_path)
        except Exception as e:
            gen_errors.append(f"debugging/{src.name}: {e}")
            logger.warning(f"  ✗ Debugging生成失败 {src.name}: {e}")

        try:
            task = template_gen.generate(golden_path=src, output_dir=template_dir)
            json_path = template_dir / f"{task.task_id}.json"
            template_gen.export_task_json(task, json_path)
            task_jsons["template"].append(json_path)
        except Exception as e:
            gen_errors.append(f"template/{src.name}: {e}")
            logger.warning(f"  ✗ Template生成失败 {src.name}: {e}")

    logger.info(
        f"生成完成: Debugging={len(task_jsons['debugging'])}, "
        f"Template={len(task_jsons['template'])}, 失败={len(gen_errors)}"
    )
    return task_jsons, gen_errors


def screen_tasks(task_jsons: Dict[str, List[Path]]) -> Dict:
    """S3: 唯一解 + 真实污染扫描 + 难度校验"""
    unique_validator = UniqueSolutionValidator()

    contamination_scanner = None
    if OFFICIAL_DATASET_PATH.exists():
        logger.info(f"加载污染扫描器(真实官方数据集): {OFFICIAL_DATASET_PATH}")
        contamination_scanner = ContaminationScanner(str(OFFICIAL_DATASET_PATH))
    else:
        logger.warning(f"官方数据集路径不存在，跳过污染检查: {OFFICIAL_DATASET_PATH}")

    screener = TaskScreener(
        contamination_scanner=contamination_scanner,
        unique_solution_validator=unique_validator,
    )

    all_task_jsons = task_jsons["debugging"] + task_jsons["template"]
    results = []
    passed_paths = []

    for task_json_path in all_task_jsons:
        try:
            result = screener.screen_task(
                task_json_path,
                check_unique_solution=True,
                check_contamination=contamination_scanner is not None,
                check_difficulty=True,
            )
            results.append(asdict(result))
            if result.passed:
                passed_paths.append(task_json_path)
        except Exception as e:
            logger.error(f"筛选异常 {task_json_path.name}: {e}")
            results.append(
                {"task_id": task_json_path.stem, "passed": False, "issues": [f"screen_exception: {e}"]}
            )

    report = {
        "total": len(all_task_jsons),
        "passed": len(passed_paths),
        "pass_rate": round(len(passed_paths) / len(all_task_jsons), 4) if all_task_jsons else 0.0,
        "contamination_checked": contamination_scanner is not None,
        "results": results,
    }

    report_path = GEN_DIR / "screening_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"筛选报告: {report_path} ({report['passed']}/{report['total']}通过)")

    return report, passed_paths


def build_trajectory_and_verify(
    task_json_path: Path, executor: TrajectoryExecutor, verifier: TrajectoryVerifier
) -> Dict:
    """S4(展开+真实执行) + S5(验证) 单个任务"""
    with open(task_json_path, "r", encoding="utf-8") as f:
        task = json.load(f)
    task_id = task["task_id"]

    record = {"task_id": task_id, "stage": None, "error": None}

    task_dir = TRAJ_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    try:
        # S4a: LLM rollout(真实多轮tool-use，产出轨迹JSON)
        record["stage"] = "llm_rollout"
        generator = LLMRolloutGenerator()
        rollout_result = generator.generate(task_json_path=task_json_path, output_dir=task_dir, sample_id="trajectory")
        trajectory_path = Path(rollout_result["trajectory_path"])
        record["trajectory_steps"] = rollout_result["total_steps"]

        # Golden泄漏 + scaffold对齐检查(记录，不阻塞)
        leak_report = GoldenLeakDetector().generate_report(GoldenLeakDetector().detect(trajectory_path))
        align_report = ScaffoldAligner().generate_report(ScaffoldAligner().check(trajectory_path))
        record["golden_leak_passed"] = leak_report["passed"]
        record["scaffold_align_passed"] = align_report["passed"]

        # S4b: 真正执行轨迹里的bash步骤，产出output.xlsx
        record["stage"] = "trajectory_execute"
        output_path = task_dir / "output.xlsx"
        exec_result = executor.execute(
            trajectory_path=trajectory_path,
            input_path=Path(task["input_path"]),
            output_path=output_path,
        )
        record["execution_success"] = exec_result.success
        record["execution_steps"] = f"{exec_result.steps_executed}/{exec_result.steps_total}"

        if not exec_result.success:
            record["error"] = f"trajectory execution failed: {exec_result.error}"
            return record

        # 组装S5验证所需的task_dir: task.json + input.xlsx + golden.xlsx + output.xlsx
        record["stage"] = "assemble"
        shutil.copy2(task_json_path, task_dir / "task.json")
        shutil.copy2(task["input_path"], task_dir / "input.xlsx")
        shutil.copy2(task["golden_path"], task_dir / "golden.xlsx")

        # S5: 验证
        record["stage"] = "verify"
        verification = verifier.verify(str(task_dir))
        record["verification"] = asdict(verification)
        record["stage"] = "done"

    except Exception as e:
        record["error"] = f"[{record['stage']}] {e}"
        logger.error(f"任务{task_id}处理失败: {record['error']}")

    return record


def main():
    parser = argparse.ArgumentParser(description="Route B 端到端跑通")
    parser.add_argument("--seed-sample-count", type=int, default=15, help="从seed_workbooks抽样数量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    random.seed(args.seed)

    GEN_DIR.mkdir(parents=True, exist_ok=True)
    TRAJ_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 80)
    logger.info("Route B 端到端跑通")
    logger.info("=" * 80)

    # Step 1: 收集源工作簿
    sources = collect_source_workbooks(args.seed_sample_count, args.seed)

    # Step 2: S2 生成任务
    logger.info("\n" + "=" * 80)
    logger.info("Step 2: S2 任务生成")
    logger.info("=" * 80)
    task_jsons, gen_errors = generate_tasks(sources, args.seed)

    # Step 3: S3 筛选(含真实污染扫描)
    logger.info("\n" + "=" * 80)
    logger.info("Step 3: S3 任务筛选")
    logger.info("=" * 80)
    screening_report, passed_paths = screen_tasks(task_jsons)

    # Step 4/5: S4轨迹生成+真实执行 -> S5验证
    logger.info("\n" + "=" * 80)
    logger.info(f"Step 4/5: S4轨迹执行 + S5验证 ({len(passed_paths)}个通过筛选的任务)")
    logger.info("=" * 80)

    executor = TrajectoryExecutor()
    verifier = TrajectoryVerifier()

    trajectory_records = []
    for idx, task_json_path in enumerate(passed_paths, 1):
        logger.info(f"[{idx}/{len(passed_paths)}] {task_json_path.stem}")
        record = build_trajectory_and_verify(task_json_path, executor, verifier)
        trajectory_records.append(record)

    # 汇总
    execution_success = sum(1 for r in trajectory_records if r.get("execution_success"))
    verified = [r for r in trajectory_records if r.get("verification")]
    approved = sum(1 for r in verified if r["verification"]["approved"])

    rejection_breakdown = Counter()
    for r in verified:
        for reason in r["verification"]["rejection_reasons"]:
            rejection_breakdown[reason] += 1

    verification_report = {
        "total_generated": len(task_jsons["debugging"]) + len(task_jsons["template"]),
        "generation_errors": len(gen_errors),
        "total_screened": screening_report["total"],
        "screening_passed": screening_report["passed"],
        "trajectory_execution_attempted": len(trajectory_records),
        "trajectory_execution_success": execution_success,
        "s5_verified": len(verified),
        "s5_approved": approved,
        "s5_approval_rate": round(approved / len(verified), 4) if verified else 0.0,
        "rejection_breakdown": dict(rejection_breakdown),
        "records": trajectory_records,
    }

    report_path = TRAJ_DIR / "verification_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(verification_report, f, indent=2, ensure_ascii=False)

    summary = {k: v for k, v in verification_report.items() if k != "records"}
    summary_path = TRAJ_DIR / "e2e_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info("\n" + "=" * 80)
    logger.info("Route B 端到端跑通 - 最终统计")
    logger.info("=" * 80)
    logger.info(f"生成任务: {summary['total_generated']} (失败{summary['generation_errors']})")
    logger.info(f"S3筛选通过: {summary['screening_passed']}/{summary['total_screened']}")
    logger.info(
        f"轨迹执行成功: {summary['trajectory_execution_success']}/{summary['trajectory_execution_attempted']}"
    )
    logger.info(f"S5批准: {summary['s5_approved']}/{summary['s5_verified']} "
                f"({summary['s5_approval_rate']:.1%})")
    if rejection_breakdown:
        logger.info("拒绝原因分布:")
        for reason, count in rejection_breakdown.most_common():
            logger.info(f"  {reason}: {count}")
    logger.info(f"\n完整报告: {report_path}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
