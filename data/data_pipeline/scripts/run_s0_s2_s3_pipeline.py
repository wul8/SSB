#!/usr/bin/env python3
"""
Route B S0→S2→S3完整管线脚本

一键执行从语料入库到筛选打包的完整流程：
- S0: 复制源Excel到corpus/{batch_name}/
- S2: 生成Debugging + Template任务
- S3: 唯一解验证 + 污染扫描 + 难度校验
- S3+: 物理分类打包到passed/rejected/

用法:
    python3 scripts/run_s0_s2_s3_pipeline.py /path/to/excel_files batch_name
    python3 scripts/run_s0_s2_s3_pipeline.py /data/new_sheets/ sheetpedia_batch2 --seed 42
    python3 scripts/run_s0_s2_s3_pipeline.py corpus/mimotable_batch2/ mimotable_batch2 --skip-contamination

输出:
    corpus/{batch_name}/*.xlsx
    generated_tasks/route_b_{batch_name}/passed/{debugging,template}/
    generated_tasks/route_b_{batch_name}/rejected/{debugging,template}/
"""

import argparse
import json
import logging
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import PROJECT_ROOT
from run_route_b_e2e import generate_tasks, screen_tasks

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def s0_collect_corpus(source_path: Path, batch_name: str) -> int:
    """S0: 语料入库 - 复制源Excel到corpus目录"""
    corpus_dir = PROJECT_ROOT / "corpus" / batch_name
    corpus_dir.mkdir(parents=True, exist_ok=True)

    if source_path.is_dir():
        # 支持 .xlsx 和 .xls 两种格式
        sources = sorted(list(source_path.glob("*.xlsx")) + list(source_path.glob("*.xls")))
    elif source_path.is_file() and source_path.suffix in [".xlsx", ".xls"]:
        sources = [source_path]
    else:
        sources = []

    copied = 0
    for src in sources:
        dst = corpus_dir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
            copied += 1
        else:
            logger.debug(f"跳过已存在: {src.name}")

    total_files = len(list(corpus_dir.glob("*.xlsx"))) + len(list(corpus_dir.glob("*.xls")))
    logger.info(f"S0完成: {copied}个新文件 → {corpus_dir}/ (总计{total_files}个)")
    return total_files


def s2_generate_tasks(batch_name: str, seed: int) -> dict:
    """S2: 任务生成 - Debugging + Template"""
    import run_route_b_e2e as e2e_mod

    corpus_dir = PROJECT_ROOT / "corpus" / batch_name
    gen_dir = PROJECT_ROOT / "generated_tasks" / f"route_b_{batch_name}"

    # Monkeypatch重定向输出目录
    e2e_mod.GEN_DIR = gen_dir
    gen_dir.mkdir(parents=True, exist_ok=True)

    # 支持 .xlsx 和 .xls 两种格式
    sources = sorted(list(corpus_dir.glob("*.xlsx")) + list(corpus_dir.glob("*.xls")))
    logger.info(f"S2开始: {len(sources)}个源工作簿")

    random.seed(seed)
    task_jsons, gen_errors = generate_tasks(sources, seed)

    summary = {
        "sources_total": len(sources),
        "debugging_generated": len(task_jsons["debugging"]),
        "template_generated": len(task_jsons["template"]),
        "generation_errors": len(gen_errors),
        "errors": gen_errors,
    }

    summary_path = gen_dir / "generation_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info(f"S2完成: Debugging={summary['debugging_generated']}, Template={summary['template_generated']}, 失败={summary['generation_errors']}")
    return summary


def s3_screen_and_sort(batch_name: str, skip_contamination: bool = False) -> dict:
    """S3: 筛选验证 + S3+: 物理分类打包"""
    import run_route_b_e2e as e2e_mod
    from scripts.sort_screened_tasks import sort_screened_tasks

    gen_dir = PROJECT_ROOT / "generated_tasks" / f"route_b_{batch_name}"
    e2e_mod.GEN_DIR = gen_dir

    # 临时修改OFFICIAL_DATASET_PATH以支持跳过污染检测
    original_dataset_path = e2e_mod.OFFICIAL_DATASET_PATH
    if skip_contamination:
        logger.warning("跳过污染检测（用户指定--skip-contamination）")
        e2e_mod.OFFICIAL_DATASET_PATH = Path("/nonexistent_path_to_skip_contamination")

    debugging_jsons = sorted((gen_dir / "debugging").glob("*.json"))
    template_jsons = sorted((gen_dir / "template").glob("*.json"))
    task_jsons = {"debugging": debugging_jsons, "template": template_jsons}

    logger.info(f"S3开始: Debugging={len(debugging_jsons)}, Template={len(template_jsons)}")

    # S3筛选
    screen_report, passed_paths = screen_tasks(task_jsons)

    # 恢复原始路径
    e2e_mod.OFFICIAL_DATASET_PATH = original_dataset_path

    logger.info(f"S3筛选: {screen_report['passed']}/{screen_report['total']} 通过 ({screen_report['pass_rate']:.1%})")

    # S3+ 物理分类打包
    logger.info("S3+开始: 物理分类打包...")
    sort_report = sort_screened_tasks(gen_dir, copy=False)

    logger.info(f"S3+完成: passed={sort_report['passed']}, rejected={sort_report['rejected']}, missing={len(sort_report['missing'])}")

    return {
        "screening": screen_report,
        "sorting": sort_report,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Route B完整管线: S0语料入库 → S2任务生成 → S3筛选验证 → 物理分类打包",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/run_s0_s2_s3_pipeline.py /data/new_excel/ sheetpedia_batch2
  python3 scripts/run_s0_s2_s3_pipeline.py corpus/test/ test_batch1 --seed 100
  python3 scripts/run_s0_s2_s3_pipeline.py /data/mimo/ mimotable_batch2 --skip-contamination
        """
    )
    parser.add_argument("source_path", type=str, help="源Excel文件路径（目录或单个文件）")
    parser.add_argument("batch_name", type=str, help="批次名称（如sheetpedia_batch2）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子（默认42）")
    parser.add_argument("--skip-contamination", action="store_true", help="跳过污染检测")
    args = parser.parse_args()

    source_path = Path(args.source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"源路径不存在: {source_path}")

    logger.info("=" * 80)
    logger.info(f"Route B S0→S2→S3 Pipeline: {args.batch_name}")
    logger.info("=" * 80)

    # S0: 语料入库
    corpus_count = s0_collect_corpus(source_path, args.batch_name)

    # S2: 任务生成
    gen_summary = s2_generate_tasks(args.batch_name, args.seed)

    # S3: 筛选 + 分类
    s3_reports = s3_screen_and_sort(args.batch_name, args.skip_contamination)

    # 最终汇报
    logger.info("=" * 80)
    logger.info("Pipeline完成")
    logger.info("=" * 80)
    logger.info(f"S0语料入库: {corpus_count}个Excel → corpus/{args.batch_name}/")
    logger.info(f"S2任务生成: {gen_summary['debugging_generated']}个Debugging + {gen_summary['template_generated']}个Template")
    logger.info(f"S3筛选验证: {s3_reports['screening']['passed']}个通过 ({s3_reports['screening']['pass_rate']:.1%}) / {s3_reports['screening']['total'] - s3_reports['screening']['passed']}个拒绝")
    logger.info(f"物理分类完成:")
    logger.info(f"  - passed/{{debugging,template}}/  : {s3_reports['sorting']['passed']}个")
    logger.info(f"  - rejected/{{debugging,template}}/: {s3_reports['sorting']['rejected']}个")

    gen_dir = PROJECT_ROOT / "generated_tasks" / f"route_b_{args.batch_name}"
    logger.info(f"\n输出目录: {gen_dir}/")
    logger.info(f"  - passed/     : S4轨迹展开输入")
    logger.info(f"  - rejected/   : 筛选未通过任务")
    logger.info(f"  - screening_report.json : S3筛选详情")
    logger.info(f"  - sort_screened_report.json : 物理分类统计")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
