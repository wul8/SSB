"""
W1实测脚本：2000份语料抽样测三道损耗通过率

这个脚本用于测量真实语料的可用性，决定路线B的题数承诺。

三道损耗：
1. S0重算门槛：外部链接、volatile函数、宏、损坏文件、PII
2. 有公式：纯数据表无法支撑Debugging和Template的公式类任务
3. 去重后独立lineage：同一模板在企业间流传，需要去重

输出：
- 各道损耗的通过率
- 公式密度分布
- 独立结构指纹数量
- 预估路线B可产出任务数
"""

import json
import logging
import random
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Tuple

from ingest.validators import WorkbookValidator, ValidationResult
from ingest.lineage import LineageRegistry

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class SamplingTest:
    """抽样测试"""

    def __init__(
        self,
        sample_size: int = 2000,
        corpus_dir: Path = None,
        output_dir: Path = None
    ):
        self.sample_size = sample_size
        self.corpus_dir = corpus_dir or Path("/mnt/hhq/data_pipeline/corpus")
        self.output_dir = output_dir or Path("/mnt/hhq/data_pipeline/output/w1_test")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.validator = WorkbookValidator(strict=False)

    def collect_corpus_files(self) -> List[Path]:
        """收集语料库中的所有xlsx文件"""
        logger.info(f"扫描语料库: {self.corpus_dir}")

        xlsx_files = []
        for source_dir in self.corpus_dir.iterdir():
            if source_dir.is_dir():
                files = list(source_dir.glob("**/*.xlsx"))
                logger.info(f"  {source_dir.name}: {len(files)} 个文件")
                xlsx_files.extend(files)

        logger.info(f"\n总计: {len(xlsx_files)} 个xlsx文件")
        return xlsx_files

    def sample_files(self, all_files: List[Path]) -> List[Path]:
        """随机抽样"""
        if len(all_files) <= self.sample_size:
            logger.warning(f"文件总数({len(all_files)})少于目标抽样数({self.sample_size})")
            return all_files

        sampled = random.sample(all_files, self.sample_size)
        logger.info(f"已随机抽样 {len(sampled)} 个文件")
        return sampled

    def run_test(self) -> Dict:
        """运行完整测试"""
        logger.info("=" * 80)
        logger.info("W1抽样测试：测量真实语料的三道损耗通过率")
        logger.info("=" * 80 + "\n")

        # 收集和抽样
        all_files = self.collect_corpus_files()
        if not all_files:
            logger.error("未找到任何xlsx文件！")
            return {}

        sampled_files = self.sample_files(all_files)

        # 第一道损耗：S0重算门槛
        logger.info("\n" + "=" * 80)
        logger.info("第一道损耗：S0重算门槛检查")
        logger.info("=" * 80)

        s0_results = self._test_s0_gate(sampled_files)

        # 第二道损耗：有公式
        logger.info("\n" + "=" * 80)
        logger.info("第二道损耗：公式密度检查")
        logger.info("=" * 80)

        formula_results = self._test_formula_density(s0_results["passed_files"])

        # 第三道损耗：去重后独立lineage
        logger.info("\n" + "=" * 80)
        logger.info("第三道损耗：结构指纹去重")
        logger.info("=" * 80)

        dedup_results = self._test_deduplication(formula_results["has_formula_files"])

        # 汇总结果
        summary = self._generate_summary(
            sampled_files,
            s0_results,
            formula_results,
            dedup_results
        )

        # 保存详细结果
        self._save_results(summary, s0_results, formula_results, dedup_results)

        # 打印汇总
        self._print_summary(summary)

        return summary

    def _test_s0_gate(self, files: List[Path]) -> Dict:
        """测试S0门槛"""
        results = {
            "total": len(files),
            "passed": 0,
            "passed_files": [],
            "validation_results": {},
            "failure_reasons": defaultdict(int)
        }

        for i, file_path in enumerate(files, 1):
            if i % 100 == 0:
                logger.info(f"  进度: {i}/{len(files)}")

            try:
                result = self.validator.validate(file_path)
                results["validation_results"][str(file_path)] = result

                if result.passed:
                    results["passed"] += 1
                    results["passed_files"].append(file_path)
                else:
                    # 统计失败原因
                    for error in result.errors:
                        # 简化错误分类
                        if "openpyxl" in error.lower():
                            results["failure_reasons"]["openpyxl无法读取"] += 1
                        elif "libreoffice" in error.lower():
                            results["failure_reasons"]["LibreOffice无法打开"] += 1
                        elif "重算" in error:
                            results["failure_reasons"]["重算不一致"] += 1
                        elif "外部链接" in error:
                            results["failure_reasons"]["外部链接"] += 1
                        elif "宏" in error:
                            results["failure_reasons"]["包含宏"] += 1
                        elif "pii" in error.lower():
                            results["failure_reasons"]["疑似PII"] += 1
                        else:
                            results["failure_reasons"]["其他"] += 1

            except Exception as e:
                logger.warning(f"  处理失败 {file_path.name}: {e}")
                results["failure_reasons"]["处理异常"] += 1

        pass_rate = results["passed"] / results["total"] * 100
        logger.info(f"\nS0门槛通过率: {results['passed']}/{results['total']} ({pass_rate:.1f}%)")

        logger.info("\n失败原因分布:")
        for reason, count in sorted(
            results["failure_reasons"].items(),
            key=lambda x: x[1],
            reverse=True
        ):
            logger.info(f"  {reason}: {count}")

        return results

    def _test_formula_density(self, files: List[Path]) -> Dict:
        """测试公式密度"""
        results = {
            "total": len(files),
            "has_formula": 0,
            "has_formula_files": [],
            "pure_data": 0,
            "formula_counts": [],
            "formula_density_bins": defaultdict(int)
        }

        for file_path in files:
            try:
                # 从validation_results中提取（避免重复验证）
                # 这里简化处理，实际应从缓存读取
                import openpyxl
                wb = openpyxl.load_workbook(file_path, data_only=False)

                formula_count = 0
                total_cells = 0

                for sheet in wb.sheetnames:
                    ws = wb[sheet]
                    for row in ws.iter_rows():
                        for cell in row:
                            if cell.value is not None:
                                total_cells += 1
                                if isinstance(cell.value, str) and cell.value.startswith("="):
                                    formula_count += 1

                wb.close()

                results["formula_counts"].append(formula_count)

                if formula_count > 0:
                    results["has_formula"] += 1
                    results["has_formula_files"].append(file_path)

                    # 计算密度
                    if total_cells > 0:
                        density = formula_count / total_cells
                        if density < 0.1:
                            results["formula_density_bins"]["<10%"] += 1
                        elif density < 0.3:
                            results["formula_density_bins"]["10-30%"] += 1
                        elif density < 0.5:
                            results["formula_density_bins"]["30-50%"] += 1
                        else:
                            results["formula_density_bins"][">=50%"] += 1
                else:
                    results["pure_data"] += 1

            except Exception as e:
                logger.warning(f"  公式检查失败 {file_path.name}: {e}")

        has_formula_rate = results["has_formula"] / results["total"] * 100
        logger.info(f"\n有公式文件: {results['has_formula']}/{results['total']} ({has_formula_rate:.1f}%)")
        logger.info(f"纯数据表: {results['pure_data']} ({results['pure_data']/results['total']*100:.1f}%)")

        logger.info("\n公式密度分布:")
        for bin_name, count in sorted(results["formula_density_bins"].items()):
            logger.info(f"  {bin_name}: {count}")

        return results

    def _test_deduplication(self, files: List[Path]) -> Dict:
        """测试去重后的独立结构数"""
        results = {
            "total": len(files),
            "unique_structures": 0,
            "duplicate_groups": []
        }

        # 简化去重：基于sheet名称序列
        structure_map = defaultdict(list)

        for file_path in files:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(file_path, read_only=True)
                sheet_signature = tuple(sorted(wb.sheetnames))
                wb.close()

                structure_map[sheet_signature].append(file_path)

            except Exception as e:
                logger.warning(f"  结构提取失败 {file_path.name}: {e}")

        results["unique_structures"] = len(structure_map)

        # 找出重复组
        for signature, files_list in structure_map.items():
            if len(files_list) > 1:
                results["duplicate_groups"].append({
                    "signature": signature,
                    "count": len(files_list),
                    "files": [str(f) for f in files_list[:3]]  # 只保留前3个示例
                })

        dedup_rate = results["unique_structures"] / results["total"] * 100
        logger.info(f"\n独立结构数: {results['unique_structures']}/{results['total']} ({dedup_rate:.1f}%)")
        logger.info(f"重复组数: {len(results['duplicate_groups'])}")

        if results["duplicate_groups"]:
            # 显示最大的几个重复组
            top_groups = sorted(
                results["duplicate_groups"],
                key=lambda x: x["count"],
                reverse=True
            )[:5]

            logger.info("\n最大的重复组:")
            for group in top_groups:
                logger.info(f"  {group['count']}个文件共享结构: {group['signature'][:3]}")

        return results

    def _generate_summary(
        self,
        sampled_files: List[Path],
        s0_results: Dict,
        formula_results: Dict,
        dedup_results: Dict
    ) -> Dict:
        """生成汇总报告"""
        total = len(sampled_files)

        summary = {
            "test_date": "2026-08-13",
            "sample_size": total,
            "three_stage_attrition": {
                "stage1_s0_gate": {
                    "passed": s0_results["passed"],
                    "rate": s0_results["passed"] / total,
                    "description": "通过S0重算门槛"
                },
                "stage2_has_formula": {
                    "passed": formula_results["has_formula"],
                    "rate": formula_results["has_formula"] / total,
                    "description": "有公式（非纯数据表）"
                },
                "stage3_unique_structure": {
                    "passed": dedup_results["unique_structures"],
                    "rate": dedup_results["unique_structures"] / total,
                    "description": "去重后独立结构"
                }
            },
            "combined_pass_rate": dedup_results["unique_structures"] / total,
            "projected_route_b_capacity": {
                "sheetpedia_size": 290000,
                "estimated_usable": int(290000 * dedup_results["unique_structures"] / total),
                "note": "基于Sheetpedia 29万份的预估"
            },
            "recommendation": None
        }

        # 生成建议
        usable_rate = summary["combined_pass_rate"]
        if usable_rate >= 0.15:
            summary["recommendation"] = f"通过率{usable_rate*100:.1f}%，建议路线B配额 600-700题（推荐）"
        elif usable_rate >= 0.10:
            summary["recommendation"] = f"通过率{usable_rate*100:.1f}%，建议路线B配额 400-500题（保守）"
        else:
            summary["recommendation"] = f"通过率{usable_rate*100:.1f}%偏低，建议降低路线B配额或增加专家构造比例"

        return summary

    def _save_results(self, summary, s0_results, formula_results, dedup_results):
        """保存结果到文件"""
        output_file = self.output_dir / "w1_sampling_test_results.json"

        full_results = {
            "summary": summary,
            "s0_gate": {
                "pass_rate": s0_results["passed"] / s0_results["total"],
                "failure_reasons": dict(s0_results["failure_reasons"])
            },
            "formula_density": {
                "has_formula_rate": formula_results["has_formula"] / formula_results["total"],
                "density_bins": dict(formula_results["formula_density_bins"])
            },
            "deduplication": {
                "unique_rate": dedup_results["unique_structures"] / dedup_results["total"],
                "num_duplicate_groups": len(dedup_results["duplicate_groups"])
            }
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(full_results, f, indent=2, ensure_ascii=False)

        logger.info(f"\n详细结果已保存到: {output_file}")

    def _print_summary(self, summary: Dict):
        """打印汇总报告"""
        logger.info("\n" + "=" * 80)
        logger.info("最终汇总")
        logger.info("=" * 80)

        logger.info(f"\n抽样规模: {summary['sample_size']}")
        logger.info("\n三道损耗通过率:")

        for stage_name, stage_data in summary["three_stage_attrition"].items():
            logger.info(
                f"  {stage_data['description']}: "
                f"{stage_data['passed']} ({stage_data['rate']*100:.1f}%)"
            )

        logger.info(f"\n综合通过率: {summary['combined_pass_rate']*100:.1f}%")

        logger.info("\n路线B产能预估:")
        proj = summary["projected_route_b_capacity"]
        logger.info(f"  Sheetpedia总量: {proj['sheetpedia_size']:,}")
        logger.info(f"  预估可用: {proj['estimated_usable']:,}")

        logger.info(f"\n建议: {summary['recommendation']}")


if __name__ == "__main__":
    # 运行测试
    test = SamplingTest(sample_size=2000)

    # 注意：需要先准备语料库
    corpus_ready = Path("/mnt/hhq/data_pipeline/corpus").exists()

    if not corpus_ready:
        logger.warning("\n" + "=" * 80)
        logger.warning("警告：语料库目录不存在")
        logger.warning("=" * 80)
        logger.warning("\n请先准备语料库，目录结构应为:")
        logger.warning("  corpus/")
        logger.warning("    sheetpedia/")
        logger.warning("    mimotable/")
        logger.warning("    t2r_bench/")
        logger.warning("\n运行演示模式（使用示例数据）...")

        # 演示模式：生成模拟报告
        demo_summary = {
            "test_date": "2026-08-13",
            "sample_size": 2000,
            "three_stage_attrition": {
                "stage1_s0_gate": {"passed": 1200, "rate": 0.60},
                "stage2_has_formula": {"passed": 900, "rate": 0.45},
                "stage3_unique_structure": {"passed": 400, "rate": 0.20}
            },
            "combined_pass_rate": 0.20,
            "projected_route_b_capacity": {
                "sheetpedia_size": 290000,
                "estimated_usable": 58000
            },
            "recommendation": "通过率20.0%，建议路线B配额 600-700题（推荐）"
        }

        logger.info("\n演示报告:")
        test._print_summary(demo_summary)

    else:
        # 实际运行测试
        summary = test.run_test()
