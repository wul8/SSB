"""
S0入库：将 /mnt/hhq/data/sheetpedia 里的新Excel跑S0门槛检查，
通过的文件登记lineage并复制到 corpus/ 下的新文件夹。

跟collect_seed_workbooks.py的区别：这里不做FM领域质量打分（那是路线A专用），
只跑S0门槛（config.py里S0_GATE定义的8项检查，strict模式），
用于给路线B攒可用语料。

用法:
    python3 scripts/ingest_sheetpedia_batch.py \
        --source-dir /mnt/hhq/data/sheetpedia \
        --family-name sheetpedia_batch1 \
        --target-dir corpus/sheetpedia_batch1
"""

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import shutil

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import PROJECT_ROOT
from ingest.lineage import LineageRegistry
from ingest.validators import WorkbookValidator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class IngestedFileRecord:
    file_name: str
    file_path: str
    lineage_id: str
    formula_count: int
    sheet_count: int
    checks: dict
    warnings: List[str]
    imported_at: str


def main():
    parser = argparse.ArgumentParser(description="S0入库：sheetpedia新文件批次")
    parser.add_argument("--source-dir", type=Path, required=True, help="待入库的xlsx目录")
    parser.add_argument("--family-name", type=str, required=True, help="lineage family_name")
    parser.add_argument("--target-dir", type=Path, required=True,
                         help="入库目标目录（corpus下新文件夹，相对或绝对路径）")
    parser.add_argument("--source-type", type=str, default="sheetpedia_realworld",
                         help="lineage source_type标注")
    args = parser.parse_args()

    target_dir = args.target_dir if args.target_dir.is_absolute() else PROJECT_ROOT / args.target_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    registry_path = PROJECT_ROOT / "ingest" / "lineage_registry.json"
    registry = LineageRegistry(registry_path)
    validator = WorkbookValidator(strict=True)

    xlsx_files = sorted(args.source_dir.glob("*.xlsx"))
    logger.info(f"扫描到 {len(xlsx_files)} 个候选文件: {args.source_dir}")

    imported: List[IngestedFileRecord] = []
    rejected = []
    failure_reason_counts = {}

    for i, file_path in enumerate(xlsx_files, 1):
        logger.info(f"[{i}/{len(xlsx_files)}] 校验 {file_path.name} ...")
        try:
            result = validator.validate(file_path)
        except Exception as e:
            logger.warning(f"  异常: {e}")
            rejected.append({"file_name": file_path.name, "reason": f"验证异常: {e}"})
            failure_reason_counts["验证异常"] = failure_reason_counts.get("验证异常", 0) + 1
            continue

        if not result.passed:
            logger.info(f"  ✗ 未通过S0: {result.errors}")
            rejected.append({
                "file_name": file_path.name,
                "reason": "; ".join(result.errors) if result.errors else "未知原因",
            })
            for err in (result.errors or ["未知原因"]):
                key = err.split(":")[0]
                failure_reason_counts[key] = failure_reason_counts.get(key, 0) + 1
            continue

        # 通过S0，登记lineage并复制文件
        lineage_id = registry.register(
            file_path=file_path,
            family_name=args.family_name,
            source_type=args.source_type,
            license="Unknown",
            notes="ingested via ingest_sheetpedia_batch.py",
        )

        target_path = target_dir / f"{lineage_id}.xlsx"
        shutil.copy2(file_path, target_path)

        record = IngestedFileRecord(
            file_name=file_path.name,
            file_path=str(target_path),
            lineage_id=lineage_id,
            formula_count=result.metadata.get("formula_count", 0),
            sheet_count=result.metadata.get("num_sheets", 0),
            checks=result.checks,
            warnings=result.warnings,
            imported_at=datetime.now().isoformat(),
        )
        imported.append(record)
        logger.info(f"  ✓ 入库: {lineage_id}")

    metadata_path = target_dir / "ingest_metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in imported], f, indent=2, ensure_ascii=False)

    rejected_path = target_dir / "rejected.json"
    with open(rejected_path, "w", encoding="utf-8") as f:
        json.dump(rejected, f, indent=2, ensure_ascii=False)

    logger.info("=" * 80)
    logger.info(f"总候选: {len(xlsx_files)}")
    logger.info(f"入库通过: {len(imported)}")
    logger.info(f"未通过: {len(rejected)}")
    logger.info("失败原因分布:")
    for reason, count in sorted(failure_reason_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {reason}: {count}")
    logger.info(f"入库目录: {target_dir}")
    logger.info(f"元数据: {metadata_path}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
