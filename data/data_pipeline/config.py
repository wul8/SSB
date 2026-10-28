"""
SpreadsheetBench 2 数据生产管线 - 项目配置

此配置记录了2026-08-13确认的MVP决策和关键参数。
"""

from pathlib import Path
from typing import Dict, List

# ============================================================================
# 项目路径
# ============================================================================

PROJECT_ROOT = Path(__file__).parent
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
CORPUS_DIR = PROJECT_ROOT / "corpus"
OUTPUT_DIR = PROJECT_ROOT / "output"

# 官方评测包路径（需要根据实际位置调整）
OFFICIAL_EVAL_DIR = Path("/mnt/hhq/visualization_scoring_package_92_b")

# ============================================================================
# MVP配置（2026-08-13确认）
# ============================================================================

MVP_CONFIG = {
    "total_tasks": 1200,  # 包含Visualization (140题)
    "expert_budget": {
        "blind_solve": 200,  # L3/L4 + 10%抽检
        "route": "L3_L4_plus_10pct"
    },
    "route_b_quota": 650,  # 600-700题，取中间值
    "include_visualization": True,  # 已纳入MVP
    "preference_data": "store_only"  # 只留存hard negative不使用
}

# 任务配比
TASK_DISTRIBUTION = {
    "Debugging": {
        "count": 460,
        "percentage": 0.38,
        "difficulty": {"L1": 0.20, "L2": 0.30, "L3": 0.35, "L4": 0.15}
    },
    "Financial_Model": {
        "count": 385,
        "percentage": 0.32,
        "difficulty": {"L1": 0.20, "L2": 0.30, "L3": 0.35, "L4": 0.15}
    },
    "Template": {
        "count": 215,
        "percentage": 0.18,
        "difficulty": {"L1": 0.20, "L2": 0.30, "L3": 0.35, "L4": 0.15}
    },
    "Visualization": {
        "count": 140,
        "percentage": 0.12,
        "difficulty": {"L1": 0.20, "L2": 0.30, "L3": 0.35, "L4": 0.15}
    }
}

# 路线分工
ROUTE_ASSIGNMENT = {
    "Debugging": "B",  # 路线B近乎免费
    "Template": "B",   # 路线B主力
    "Financial_Model": "A",  # 路线A专家构造
    "Visualization": "A"  # 路线A专家构造
}

# ============================================================================
# 官方评分参数（从evaluation.py提取）
# ============================================================================

OFFICIAL_SCORING = {
    "numerical_tolerance": 0.01,  # 1%相对误差
    "regression_threshold": 0.998,  # regression_accuracy >= 0.998 归一为1.0
    "placeholder_equivalents": [
        "#DIV/0!", "#N/A", "N/A", "NA", "N.M.", "—", "-"
    ],
    "formula_normalization": {
        "remove_dollar": True,
        "uppercase": True,
        "normalize_equal_plus": True  # =+ → =
    },
    "compare_modes": {
        "value": "default",
        "formula": "path_contains_Embedded",
        "color": "path_contains_Color"
    },
    "visualization_rubric": {
        "use_criteria": True,  # 使用criteria字段而非answer_position
        "pass_threshold": 0.7,  # score > 0.7 → accuracy = 1.0
        "rubric_categories": {
            "data_correctness": 0.65,  # 主要弱项
            "spec_compliance": 0.33,
            "preservation": 0.007
        }
    }
}

# ============================================================================
# Scaffold约束（必须逐字复刻）
# ============================================================================

SCAFFOLD_CONFIG = {
    "system_prompt": "You are a helpful Spreadsheet Automation Engineer that interacts with a computer shell to solve data tasks. You operate in a REPL (Read-Eval-Print Loop) environment where you must issue exactly ONE command at a time.",

    "tools": ["bash", "view_xlsx", "submit"],

    "max_turns": 50,
    "max_observation_length": 10000,
    "execution_timeout": 60,
    "total_execution_timeout": 1800,

    "input_path_pattern": "/mnt/spreadsheet_data/spreadsheet/{family}/{id}_input.xlsx",
    "output_path_pattern": "/mnt/spreadsheet_output/{id}_output.xlsx",

    "blocklist": [
        "vim", "vi", "nano", "less", "tail -f", "make",
        "python", "python3", "bash"  # 作为独立命令被拦，需用heredoc或重定向
    ],

    "observation_format": {
        "header": "Loading workbook: {path}\n\nSheet: {sheet_name}\nData range: '{sheet_name}'!{range}\nRows: {start} to {end} (total: {count})\nColumns: {col_start} to {col_end}\n\n",
        "row_format": "Row {i}: {cells}",  # cells是Python list字符串表示
        "null_repr": "None",
        "formula_repr": "原文字符串"
    }
}

# ============================================================================
# S0 资产入库门槛
# ============================================================================

S0_GATE = {
    "openpyxl_readable": True,
    "libreoffice_openable": True,
    "recalc_consistent": True,  # 两次重算结果一致
    "no_external_links": True,
    "no_volatile_functions": ["NOW", "TODAY", "RAND", "RANDBETWEEN", "INDIRECT"],
    "no_pii": True,
    "no_macros": True,
    "no_unresolved_errors": True  # golden内无未解释的#REF!/#VALUE!等
}

# ============================================================================
# S1 结构解析配置
# ============================================================================

PARSE_CONFIG = {
    "formula_graph": {
        "r1c1_normalize": True,
        "clustering_threshold": 0.95  # R1C1归一化后的相似度
    },
    "style_map": {
        "track_merged_cells": True,
        "track_named_ranges": True,
        "color_extraction": "rgb_hex"
    },
    "invariants": {
        "auto_detect": [
            "balance_sheet_balance",
            "three_statement_tie",
            "sum_equals_total",
            "ratio_consistency"
        ],
        "default_tolerance": 0.01
    }
}

# ============================================================================
# S2 任务生成配置
# ============================================================================

# Debugging十类错误
DEBUGGING_ERROR_TYPES = [
    "Double Counting",
    "Embedded Hardcodes",
    "Errors",
    "Inconsistent Color",
    "Incorrect Average",
    "Cross-Sheet References",
    "Incorrect index-match",
    "Incorrect Sign",
    "Relative vs Absolute References",
    "Unit Mismatch"
]

# 错误数分布
ERROR_COUNT_DISTRIBUTION = {
    1: 0.20,      # 单根因
    "2-3": 0.50,  # 2-3个错误
    "4-8": 0.30   # 4-8个（含无关噪声）
}

# ============================================================================
# S3 任务体检配置
# ============================================================================

SCREENING_CONFIG = {
    "unique_solution": {
        "num_models": 3,  # 三个独立强模型
        "max_repair_rounds": 2,
        "convergence_threshold": 0.99  # 三份产出一致的阈值
    },
    "deduplication": {
        "methods": [
            "lineage",
            "sheet_names_sequence",
            "formula_ast_fingerprint",
            "dependency_graph_fingerprint",
            "row_labels_minhash",
            "instruction_embedding"
        ],
        "similarity_threshold": 0.85
    },
    "contamination": {
        "official_dataset_size": 321,
        "same_methods_as_dedup": True,
        "action": "remove_entire_lineage"  # 命中则整族剔除
    },
    "strong_model_trial": {
        "filter_too_easy": True,  # 全对的送人工复核
        "filter_too_hard": True   # 全错的送人工复核
    }
}

# ============================================================================
# S4 轨迹生成配置
# ============================================================================

TRAJECTORY_GENERATION = {
    "sources": {
        "rollout": 0.90,  # 主力
        "recovery_inject": 0.10
    },
    "recovery_types": [
        "sheet_name_typo",
        "output_path_wrong",
        "libreoffice_timeout",
        "forgot_save",
        "chart_export_fail",
        "xml_malformed",
        "range_out_of_bounds"
    ],
    "golden_leak_keywords": ["golden", "answer", r"target\.xlsx"],
    "prune_ineffective_steps": True  # 裁掉未被后续引用的inspect步骤
}

# ============================================================================
# S4 LLM Rollout配置（TRAJECTORY_GENERATION.sources.rollout的实现）
#
# 走自建中转endpoint（Anthropic Messages API兼容），key通过环境变量
# ROLLOUT_LLM_API_KEY传入，不要写进这个文件或提交进版本控制。
# ============================================================================

LLM_ROLLOUT_CONFIG = {
    "model": "deepseek-v4-pro",
    "api_key_env_var": "ROLLOUT_LLM_API_KEY",  # 中转endpoint的key，不是真实ANTHROPIC_API_KEY
    "base_url": "http://115.120.120.64:8082",
    # 不直接复用SCAFFOLD_CONFIG["max_turns"]=50——那是官方scaffold的硬约束，
    # 改了会影响oracle轨迹的scaffold对齐；这里是deepseek-v4-pro自己响应慢、
    # 常在50轮内耗光却没submit，单独放宽到100轮
    "max_turns": 100,
    "execution_timeout": SCAFFOLD_CONFIG["execution_timeout"],
    "total_execution_timeout": SCAFFOLD_CONFIG["total_execution_timeout"],
    "max_tokens": 16384,  # 4096会被reasoning_effort=max的思考内容耗尽导致截断，见批量测试排查
    "temperature": 1,
    "reasoning_effort": "max",
}

# ============================================================================
# S5 轨迹判决配置
# ============================================================================

VERIFICATION_CONFIG = {
    "recalculation": {
        "engine": "libreoffice",
        "headless": True,
        "timeout": 60
    },
    "official_scorer": {
        "reuse_evaluation_py": True,
        "comparison_functions": "exact_copy"  # 复用官方比较函数
    },
    "strict_verifier": {
        "check_protected_cells": True,
        "check_formula_family_consistency": True,
        "check_invariants": True,
        "check_excel_errors": True,
        "check_style_preservation": True
    },
    "positive_sample_criteria": {
        "official_accuracy": 1.0,
        "strict_verifier": "all_green"
    },
    "visualization_verification": {
        "tier1_linux": {
            "method": "openpyxl_chart_xml",
            "coverage": 0.70,  # ~70%的criteria可通过chart XML判断
            "checks": [
                "series_data_ranges",
                "series_values",
                "axis_settings",
                "chart_title",
                "legend_position",
                "data_labels"
            ]
        },
        "tier2_windows": {
            "method": "excel_com_vlm",
            "coverage": 0.15,  # ~15%视觉criteria
            "usage": "calibration_spot_check",  # 校准和抽检，非逐样本依赖
            "checks": [
                "visual_formatting",
                "color_schemes",
                "layout_aesthetics"
            ],
            "vlm_judge_threshold": 0.7
        },
        "note": "Windows/Excel降级为校准设备，非持续基础设施"
    }
}

# ============================================================================
# S6 样本装配配置
# ============================================================================

ASSEMBLY_CONFIG = {
    "max_samples_per_task": 2,  # 最短的 + 一条含恢复片段的
    "context_budget": {
        "min_tokens": 32000,
        "max_tokens": 48000
    },
    "curriculum": {
        "stage1": ["L1", "L2"],  # 先打稳流程
        "stage2": ["L3", "L4"]   # 再提难度
    },
    "split_strategy": {
        "by": ["source_lineage_id", "template_family", "company", "error_recipe"],
        "no_cross_split": True
    },
    "shadow_eval_set": {
        "size": 400,  # 300-500题
        "unseen_combinations": True  # 未见公司/模板/行业/错误配方组合
    }
}

# ============================================================================
# 语料来源配置
# ============================================================================

CORPUS_SOURCES = {
    "sheetpedia": {
        "estimated_size": 290000,
        "source": "企业邮件归档 + 在线论坛",
        "license_check": "required_per_file",
        "contamination_risk": "high"  # 与SpreadsheetBench V1同源
    },
    "mimotable": {
        "size": 428,
        "domains": 7,
        "use_for": "environment_and_difficulty_scheme",  # 取环境与难度分级，不取任务
        "note": "答案是文本不是工作簿"
    },
    "t2r_bench": {
        "domains": 19,
        "use_for": "domain_coverage_supplement"
    }
}

# W1实测目标：2000份抽样测三道损耗
W1_SAMPLING_TEST = {
    "sample_size": 2000,
    "measure": [
        "s0_recalc_pass_rate",
        "has_formulas_rate",
        "unique_lineages_after_dedup"
    ],
    "决策依据": "根据实测通过率决定路线B的题数承诺"
}

# ============================================================================
# 验收指标
# ============================================================================

ACCEPTANCE_METRICS = {
    "data_side": {
        "task_screening_pass_rate": ">= 0.40",
        "expert_agreement_rate": ">= 0.95",
        "effective_step_ratio_median": "> rollout_baseline",
        "golden_leak_detected": 0,
        "contamination_hits": 0
    },
    "model_side": {
        "primary": "accuracy_modification_gap_reduction",  # 北极星
        "secondary": [
            "target_recall",
            "target_precision",
            "protected_violation_rate",
            "complete_repair_rate",
            "submit_before_verify_rate"
        ]
    }
}

# ============================================================================
# 风险与应对
# ============================================================================

RISKS = {
    "fm_golden_bottleneck": {
        "severity": "high",
        "mitigation": "W2并行启动专家招募；宁减题数不减golden质量"
    },
    "oracle_thought_mismatch": {
        "severity": "high",
        "mitigation": "强制一致性校验；只看observation能否解释动作"
    },
    "scaffold_version_drift": {
        "severity": "medium",
        "mitigation": "样本带scaffold@commit；变更走重装配流程"
    },
    "route_b_recalc_rate_lower_than_expected": {
        "severity": "high",
        "mitigation": "W1先实测2000份抽样，再定路线B题数承诺"
    },
    "learning_scorer_tolerance": {
        "severity": "medium",
        "mitigation": "内部verifier严于官方；此类样本在S5直接判废"
    }
}
