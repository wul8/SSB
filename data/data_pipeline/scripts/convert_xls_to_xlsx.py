#!/usr/bin/env python3
"""
将 .xls 文件批量转换为 .xlsx 格式

使用 LibreOffice 进行转换，保持公式和格式完整性
"""

import argparse
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def convert_xls_to_xlsx(xls_path: Path, output_dir: Path) -> tuple[bool, str]:
    """使用LibreOffice将单个.xls文件转换为.xlsx"""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        # LibreOffice命令行转换
        cmd = [
            "soffice",
            "--headless",
            "--convert-to", "xlsx",
            "--outdir", str(output_dir),
            str(xls_path)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            # 生成的输出文件名
            xlsx_name = xls_path.stem + ".xlsx"
            xlsx_path = output_dir / xlsx_name

            if xlsx_path.exists():
                return True, str(xlsx_path)
            else:
                return False, f"转换完成但找不到输出文件: {xlsx_name}"
        else:
            return False, f"LibreOffice错误: {result.stderr[:200]}"

    except subprocess.TimeoutExpired:
        return False, "转换超时"
    except Exception as e:
        return False, f"异常: {str(e)}"


def main():
    parser = argparse.ArgumentParser(description="批量将.xls文件转换为.xlsx格式")
    parser.add_argument("input_dir", type=str, help="输入目录（包含.xls文件）")
    parser.add_argument("output_dir", type=str, help="输出目录（生成.xlsx文件）")
    parser.add_argument("--workers", type=int, default=4, help="并发转换线程数（默认4）")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        logger.error(f"输入目录不存在: {input_dir}")
        sys.exit(1)

    xls_files = sorted(input_dir.glob("*.xls"))
    logger.info(f"找到 {len(xls_files)} 个 .xls 文件")

    if len(xls_files) == 0:
        logger.warning("没有找到需要转换的文件")
        sys.exit(0)

    output_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0
    failed_count = 0
    failed_files = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(convert_xls_to_xlsx, xls_file, output_dir): xls_file
            for xls_file in xls_files
        }

        for i, future in enumerate(as_completed(futures), 1):
            xls_file = futures[future]
            try:
                success, message = future.result()
                if success:
                    success_count += 1
                    if i % 10 == 0:
                        logger.info(f"进度: {i}/{len(xls_files)} - 成功: {success_count}, 失败: {failed_count}")
                else:
                    failed_count += 1
                    failed_files.append((xls_file.name, message))
                    logger.warning(f"✗ {xls_file.name}: {message}")
            except Exception as e:
                failed_count += 1
                failed_files.append((xls_file.name, str(e)))
                logger.error(f"✗ {xls_file.name}: {e}")

    logger.info("=" * 80)
    logger.info("转换完成")
    logger.info("=" * 80)
    logger.info(f"总计: {len(xls_files)} 个文件")
    logger.info(f"成功: {success_count} 个")
    logger.info(f"失败: {failed_count} 个")

    if failed_files:
        logger.info("\n失败文件列表:")
        for filename, error in failed_files[:10]:
            logger.info(f"  - {filename}: {error}")
        if len(failed_files) > 10:
            logger.info(f"  ... 还有 {len(failed_files) - 10} 个失败")

    logger.info(f"\n输出目录: {output_dir}/")


if __name__ == "__main__":
    main()
