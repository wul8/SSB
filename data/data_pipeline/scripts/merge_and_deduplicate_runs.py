#!/usr/bin/env python3
"""合并多个运行批次的轨迹文件并去重"""

import sys
from pathlib import Path
import json
import shutil
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import PROJECT_ROOT

# 源目录列表
SOURCE_DIRS = [
    "trajectories/llm_rollout_runs/route_b_enron_batch1_20260904_093355_deepseek-v4-pro",
    "trajectories/llm_rollout_runs/route_b_enron_batch1_20260904_143207_deepseek-v4-pro",
    "trajectories/llm_rollout_runs/route_b_enron_batch1_20260904_162509_deepseek-v4-pro",
    "trajectories/llm_rollout_runs/route_b_enron_batch1_retry_20260907_142138_deepseek-v4-pro",
]

def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "trajectories" / "llm_rollout_runs" / f"route_b_enron_batch1_merged_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"输出目录: {output_dir}")
    print(f"开始合并和去重...")

    # 用于去重：task_id -> (source_dir, file_path, trajectory_data)
    task_trajectories = {}

    # 遍历所有源目录
    for source_dir_rel in SOURCE_DIRS:
        source_dir = PROJECT_ROOT / source_dir_rel
        if not source_dir.exists():
            print(f"警告: 目录不存在，跳过: {source_dir}")
            continue

        print(f"\n处理目录: {source_dir.name}")

        # 收集所有json文件（排除summary）
        json_files = [f for f in source_dir.glob("*.json") if f.name != "rollout_summary.json"]
        print(f"  找到 {len(json_files)} 个轨迹文件")

        for json_file in json_files:
            try:
                with open(json_file, "r") as f:
                    trajectory = json.load(f)

                task_id = trajectory.get("task_id") or trajectory.get("sample_id")
                if not task_id:
                    print(f"  警告: 无法获取task_id: {json_file.name}")
                    continue

                # 去重策略：保留第一个遇到的版本（按目录顺序）
                if task_id not in task_trajectories:
                    task_trajectories[task_id] = (source_dir.name, json_file, trajectory)
                    print(f"  ✓ {task_id}")
                else:
                    existing_source = task_trajectories[task_id][0]
                    print(f"  ⊗ {task_id} (已存在于 {existing_source})")

            except Exception as e:
                print(f"  ✗ 读取失败 {json_file.name}: {e}")

    print(f"\n{'='*80}")
    print(f"去重后共有 {len(task_trajectories)} 个唯一任务")
    print(f"{'='*80}")

    # 复制文件到输出目录
    print(f"\n复制文件到输出目录...")
    success_count = 0
    fail_count = 0

    for task_id, (source_name, source_file, trajectory) in task_trajectories.items():
        try:
            # 复制主轨迹文件
            dest_file = output_dir / source_file.name
            shutil.copy2(source_file, dest_file)

            # 检查是否有对应的verify_bundle目录
            verify_bundle_name = source_file.stem + "__verify_bundle"
            verify_bundle_src = source_file.parent / verify_bundle_name

            if verify_bundle_src.exists() and verify_bundle_src.is_dir():
                verify_bundle_dest = output_dir / verify_bundle_name
                shutil.copytree(verify_bundle_src, verify_bundle_dest, dirs_exist_ok=True)
                print(f"  ✓ {task_id} (含verify_bundle)")
            else:
                print(f"  ✓ {task_id}")

            # 统计成功/失败
            rollout_success = trajectory.get("rollout_success", False)
            answer_submitted = trajectory.get("answer_submitted", False)

            if rollout_success or answer_submitted:
                success_count += 1
            else:
                fail_count += 1

        except Exception as e:
            print(f"  ✗ 复制失败 {task_id}: {e}")

    # 生成汇总文件
    print(f"\n生成汇总文件...")
    total = success_count + fail_count
    summary = {
        "batch_name": "route_b_enron_batch1_merged",
        "model": "deepseek-v4-pro",
        "source_dirs": SOURCE_DIRS,
        "merged_at": timestamp,
        "total": total,
        "succeeded": success_count,
        "failed": fail_count,
        "success_rate": success_count / total if total > 0 else 0,
    }

    summary_file = output_dir / "rollout_summary.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"合并完成！")
    print(f"  输出目录: {output_dir}")
    print(f"  总任务数: {total}")
    print(f"  成功: {success_count} ({success_count/total*100:.1f}%)")
    print(f"  失败: {fail_count} ({fail_count/total*100:.1f}%)")
    print(f"  汇总文件: {summary_file}")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
