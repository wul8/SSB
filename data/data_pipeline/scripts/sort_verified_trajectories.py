#!/usr/bin/env python3
"""
S5验证后分类打包脚本

对<run_dir>下所有*__verify_bundle跑TrajectoryVerifier.verify()，然后把
verify_bundle及其对应的轨迹json按approved/rejected分别挪进两个子目录，
让S6装配阶段能直接从approved/取正样本，不用每次重新扫描判断哪些通过了。

用法:
    python3 scripts/sort_verified_trajectories.py trajectories/llm_rollout_runs/<run_dir>
    python3 scripts/sort_verified_trajectories.py <run_dir> --copy  # 复制而非移动，保留原文件
"""

import argparse
import json
import logging
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from verify.trajectory_verifier import TrajectoryVerifier, VerificationResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _error_result(task_id: str, exc: Exception) -> VerificationResult:
    """verify()抛异常时构造一个REJECTED结果，避免单个坏样本拖垮整批"""
    return VerificationResult(
        task_id=task_id,
        approved=False,
        rejection_reasons=[f"verify() raised {type(exc).__name__}: {exc}"],
        accuracy=0.0,
        modification_accuracy=0.0,
        regression_accuracy=0.0,
        recalculated=False,
        protected_violation=0,
        formula_family_consistent=False,
        invariants_failed=[],
        excel_errors=0,
        style_preserved=False,
    )


def _transfer(src: Path, dst: Path, copy: bool) -> None:
    if copy:
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    else:
        shutil.move(str(src), str(dst))


def sort_trajectories(run_dir: Path, copy: bool = False) -> dict:
    verifier = TrajectoryVerifier()
    bundles = sorted(run_dir.glob("*__verify_bundle"))
    if not bundles:
        raise FileNotFoundError(f"{run_dir}下没有找到*__verify_bundle目录")

    approved_dir = run_dir / "approved"
    rejected_dir = run_dir / "rejected"
    approved_dir.mkdir(exist_ok=True)
    rejected_dir.mkdir(exist_ok=True)

    results = {}
    approved_count = 0

    for bundle in bundles:
        try:
            result = verifier.verify(str(bundle))
        except Exception as e:
            logger.error(f"verify()异常 {bundle.name}: {e}")
            result = _error_result(bundle.name, e)
        results[result.task_id] = asdict(result)
        target_dir = approved_dir if result.approved else rejected_dir
        approved_count += int(result.approved)

        _transfer(bundle, target_dir / bundle.name, copy)

        # 轨迹json与bundle同目录、同名去掉__verify_bundle后缀
        sample_id = bundle.name.removesuffix("__verify_bundle")
        traj_json = run_dir / f"{sample_id}.json"
        if traj_json.exists():
            _transfer(traj_json, target_dir / traj_json.name, copy)

        logger.info(f"{'✓' if result.approved else '✗'} {bundle.name} -> {target_dir.name}/")

    report = {
        "total": len(results),
        "approved": approved_count,
        "rejected": len(results) - approved_count,
        "approval_rate": approved_count / len(results) if results else 0.0,
        "results": results,
    }
    report_path = run_dir / "verification_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    logger.info("=" * 60)
    logger.info(f"总计: {approved_count}/{len(results)} APPROVED -> {approved_dir}")
    logger.info(f"其余{len(results) - approved_count}条 -> {rejected_dir}")
    logger.info(f"报告: {report_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="S5验证后按approved/rejected分类打包轨迹")
    parser.add_argument("run_dir", type=str, help="包含*__verify_bundle的轨迹输出目录")
    parser.add_argument("--copy", action="store_true", help="复制而非移动（默认移动，保持输出目录整洁）")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        raise FileNotFoundError(f"目录不存在: {run_dir}")

    sort_trajectories(run_dir, copy=args.copy)


if __name__ == "__main__":
    main()
