# S0-S2-S3 Pipeline 快速开始

## 一键执行完整流程

```bash
python3 scripts/run_s0_s2_s3_pipeline.py <源Excel路径> <批次名>
```

## 示例

```bash
# 处理新的Excel文件
python3 scripts/run_s0_s2_s3_pipeline.py /data/new_sheets/ sheetpedia_batch3

# 指定随机种子
python3 scripts/run_s0_s2_s3_pipeline.py /data/excel/ batch4 --seed 100

# 跳过污染检测（官方数据集路径不可用时）
python3 scripts/run_s0_s2_s3_pipeline.py corpus/test/ test1 --skip-contamination
```

## 输出

- **corpus/{batch_name}/** - 入库的源Excel
- **generated_tasks/route_b_{batch_name}/passed/** - 通过筛选的任务（S4输入）
- **generated_tasks/route_b_{batch_name}/rejected/** - 未通过筛选的任务

## 流程说明

1. **S0语料入库**: 复制Excel到corpus目录
2. **S2任务生成**: Debugging任务（10类错误注入）+ Template任务（公式保留）
3. **S3筛选验证**: 唯一解检查 + 污染扫描 + 难度校验
4. **S3+物理分类**: 自动打包到passed/rejected/

## 已验证批次

| 批次名 | 源文件数 | 生成任务数 | S3通过率 | 备注 |
|--------|---------|-----------|---------|------|
| route_b_sheetpedia_batch1 | 57 | 104 | 68.3% (71/104) | 真实财务建模工作簿，公式密集 |
| route_b_mimotable_batch1 | 199 | 533 | 24.4% (130/533) | 大量纯数据表（无公式），75%因无唯一解被拒 |

**通过率差异说明**：
- Sheetpedia语料适合Route B工作流（公式密集，Template任务有约束）
- Mimotable语料不适合（60%+纯数据表，Template任务无约束）
- 建议对Mimotable类语料只生成Debugging任务或预筛选有公式的源文件

## 下一步

```bash
# S4: LLM Rollout轨迹生成（真实推理轨迹，需API）
export ROLLOUT_LLM_API_KEY="sk-..."
python3 scripts/run_llm_rollout_batch_test.py --count 15 --seed 42

# S5: 轨迹验证 + 分类打包
python3 scripts/sort_verified_trajectories.py trajectories/llm_rollout_runs/<run_dir>
```

## 详细文档

- **管线集成指南**: `docs/PIPELINE_INTEGRATION_GUIDE.md` - **S0→S6全流程架构图与衔接说明**
- **完整使用指南**: `docs/S0_S2_S3_PIPELINE_USAGE.md`
- **Route B概览**: `docs/ROUTE_B_LLM_ROLLOUT_GUIDE.md`
- **LLM Rollout工作流**: `docs/LLM_ROLLOUT_BATCH_WORKFLOW.md`
- **S3筛选报告**: `docs/S3_SCREENING_REPORT.md`
- **S5轨迹验证**: `docs/S5_TRAJECTORY_VERIFICATION.md`
- **项目状态**: `docs/PROJECT_STATUS.md`
