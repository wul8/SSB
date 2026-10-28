#!/usr/bin/env python3
"""对合并数据集运行S5验证并分类打包"""

import sys
from pathlib import Path
import json
import shutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import PROJECT_ROOT
from verify.trajectory_verifier import TrajectoryVerifier

# 合并后的目录
MERGED_DIR = PROJECT_ROOT / "trajectories" / "llm_rollout_runs" / "route_b_enron_batch1_merged_20260907_162148"

def verify_one_bundle(verifier: TrajectoryVerifier, bundle_dir: Path, index: int, total: int):
    """验证单个bundle"""
    task_id = bundle_dir.name.replace("__verify_bundle", "")
    print(f"[{index}/{total}] 验证 {task_id}")

    try:
        result = verifier.verify(str(bundle_dir))
        passed = result.get("passed", False)
        score = result.get("score", 0.0)

        if passed:
            print(f"  ✓ PASS (score={score})")
        else:
            print(f"  ✗ FAIL (score={score})")

        return {
            "task_id": task_id,
            "passed": passed,
            "score": score,
            "details": result
        }
    except Exception as e:
        print(f"  ✗ 验证失败: {e}")
        return {
            "task_id": task_id,
            "passed": False,
            "score": 0.0,
            "error": str(e)
        }

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"开始S5验证: {MERGED_DIR.name}")
    print("="*80)

    # 创建验证器
    verifier = TrajectoryVerifier()

    # 收集所有verify_bundle目录
    verify_bundles = sorted(MERGED_DIR.glob("*__verify_bundle"))
    print(f"找到 {len(verify_bundles)} 个verify_bundle目录\n")

    if len(verify_bundles) == 0:
        print("错误: 没有找到verify_bundle目录")
        return

    # 并发验证所有bundles
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(verify_one_bundle, verifier, bundle_dir, i, len(verify_bundles)): bundle_dir
            for i, bundle_dir in enumerate(verify_bundles, 1)
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    # 统计结果
    passed_results = [r for r in results if r["passed"]]
    failed_results = [r for r in results if not r["passed"]]

    passed = len(passed_results)
    failed = len(failed_results)
    total = len(results)

    print(f"\n{'='*80}")
    print(f"验证完成！")
    print(f"  总数: {total}")
    print(f"  通过: {passed} ({passed/total*100:.1f}%)")
    print(f"  失败: {failed} ({failed/total*100:.1f}%)")
    print(f"{'='*80}\n")

    # 保存验证结果
    results_file = MERGED_DIR / f"s5_verification_results_{timestamp}.json"
    verification_summary = {
        "batch_name": "route_b_enron_batch1_merged",
        "verified_at": timestamp,
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": passed / total if total > 0 else 0,
        "results": results
    }

    with open(results_file, "w") as f:
        json.dump(verification_summary, f, indent=2, ensure_ascii=False)

    print(f"验证结果已保存: {results_file}\n")

    # 创建分类打包目录
    output_base = PROJECT_ROOT / "trajectories" / "llm_rollout_runs" / f"route_b_enron_batch1_s5_classified_{timestamp}"
    passed_dir = output_base / "passed"
    failed_dir = output_base / "failed"

    passed_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    print("开始分类打包...")

    # 分类复制文件
    for result in results:
        task_id = result["task_id"]
        passed = result["passed"]

        # 确定目标目录
        target_dir = passed_dir if passed else failed_dir

        # 复制轨迹文件
        trajectory_file = MERGED_DIR / f"{task_id}.json"
        if trajectory_file.exists():
            shutil.copy2(trajectory_file, target_dir / trajectory_file.name)

        # 复制verify_bundle目录
        bundle_dir = MERGED_DIR / f"{task_id}__verify_bundle"
        if bundle_dir.exists():
            shutil.copytree(bundle_dir, target_dir / bundle_dir.name, dirs_exist_ok=True)

    print(f"  ✓ 通过: {passed}个任务 -> {passed_dir}")
    print(f"  ✗ 失败: {failed}个任务 -> {failed_dir}")

    # 复制汇总文件
    shutil.copy2(results_file, output_base / "s5_verification_results.json")

    # 生成分类汇总
    classification_summary = {
        "batch_name": "route_b_enron_batch1_s5_classified",
        "classified_at": timestamp,
        "source_dir": str(MERGED_DIR),
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": passed / total if total > 0 else 0,
        "passed_dir": str(passed_dir),
        "failed_dir": str(failed_dir),
    }

    with open(output_base / "classification_summary.json", "w") as f:
        json.dump(classification_summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"分类打包完成！")
    print(f"  输出目录: {output_base}")
    print(f"  通过: {passed}个 -> passed/")
    print(f"  失败: {failed}个 -> failed/")
    print(f"  汇总: classification_summary.json")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
