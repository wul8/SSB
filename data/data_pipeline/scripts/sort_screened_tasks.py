#!/usr/bin/env python3
"""
S3筛选后分类打包脚本

对某个generated_tasks/route_b_<batch>/目录下已经跑完screen_tasks()产出的
screening_report.json，按每个task的passed字段把对应的task.json +
{task_id}_input.xlsx + {task_id}_golden.xlsx 三件套物理挪到passed/或rejected/
子目录（各自保留debugging/template两个分类），让S4阶段能直接从passed/取任务，
不用每次重新读screening_report.json做二次筛选。

跟S5那步的sort_verified_trajectories.py是同一个思路，只是作用对象是S3筛选
产出而不是S5验证产出。

用法:
    python3 scripts/sort_screened_tasks.py generated_tasks/route_b_sheetpedia_batch1
    python3 scripts/sort_screened_tasks.py generated_tasks/route_b_mimotable_batch1 --copy
"""

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _transfer(src: Path, dst: Path, copy: bool) -> None:
    if copy:
        shutil.copy2(src, dst)
    else:
        shutil.move(str(src), str(dst))


def _find_task_type_dir(gen_dir: Path, task_id: str) -> str:
    if (gen_dir / "debugging" / f"{task_id}.json").exists():
        return "debugging"
    if (gen_dir / "template" / f"{task_id}.json").exists():
        return "template"
    raise FileNotFoundError(f"{task_id}.json 在debugging/和template/下都没找到")


def sort_screened_tasks(gen_dir: Path, copy: bool = False) -> dict:
    report_path = gen_dir / "screening_report.json"
    if not report_path.exists():
        raise FileNotFoundError(f"{report_path} 不存在，先跑S3筛选生成screening_report.json")

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    passed_dir = gen_dir / "passed"
    rejected_dir = gen_dir / "rejected"
    for base in (passed_dir, rejected_dir):
        (base / "debugging").mkdir(parents=True, exist_ok=True)
        (base / "template").mkdir(parents=True, exist_ok=True)

    moved = {"passed": 0, "rejected": 0}
    missing = []

    for result in report["results"]:
        task_id = result["task_id"]
        try:
            task_type = _find_task_type_dir(gen_dir, task_id)
        except FileNotFoundError as e:
            missing.append(f"{task_id}: {e}")
            continue

        src_dir = gen_dir / task_type
        target_base = passed_dir if result.get("passed") else rejected_dir
        target_dir = target_base / task_type

        for suffix, fname in [
            ("", f"{task_id}.json"),
            ("_input", f"{task_id}_input.xlsx"),
            ("_golden", f"{task_id}_golden.xlsx"),
        ]:
            src = src_dir / fname
            if src.exists():
                _transfer(src, target_dir / fname, copy)

        moved["passed" if result.get("passed") else "rejected"] += 1
        logger.info(f"{'✓' if result.get('passed') else '✗'} {task_id} -> {target_dir}/")

    # debugging/、template/目录里此时只剩生成失败(没进screening_report)的残留文件，不动它们
    summary = {
        "total": len(report["results"]),
        "passed": moved["passed"],
        "rejected": moved["rejected"],
        "missing": missing,
    }
    summary_path = gen_dir / "sort_screened_report.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info(f"总计: {moved['passed']}个 -> {passed_dir}/, {moved['rejected']}个 -> {rejected_dir}/")
    if missing:
        logger.warning(f"未找到源文件: {len(missing)}个")
    logger.info(f"报告: {summary_path}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="S3筛选后按passed/rejected分类打包任务")
    parser.add_argument("gen_dir", type=str, help="包含screening_report.json的generated_tasks子目录")
    parser.add_argument("--copy", action="store_true", help="复制而非移动（默认移动，保持输出目录整洁）")
    args = parser.parse_args()

    gen_dir = Path(args.gen_dir)
    if not gen_dir.exists():
        raise FileNotFoundError(f"目录不存在: {gen_dir}")

    sort_screened_tasks(gen_dir, copy=args.copy)


if __name__ == "__main__":
    main()
