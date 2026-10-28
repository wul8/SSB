#!/bin/bash
# 监控answer_files_batch1管线进度

OUTPUT_DIR="/mnt/hhq/data/data_pipeline/generated_tasks/route_b_answer_files_batch1"

echo "========================================"
echo "Answer Files Batch1 管线进度监控"
echo "========================================"
echo ""

# 检查生成的任务数量
if [ -d "${OUTPUT_DIR}/debugging" ]; then
    DEBUG_COUNT=$(ls ${OUTPUT_DIR}/debugging/*.json 2>/dev/null | wc -l)
    echo "Debugging任务: ${DEBUG_COUNT} 个"
fi

if [ -d "${OUTPUT_DIR}/template" ]; then
    TEMPLATE_COUNT=$(ls ${OUTPUT_DIR}/template/*.json 2>/dev/null | wc -l)
    echo "Template任务: ${TEMPLATE_COUNT} 个"
fi

echo ""

# 检查报告文件
if [ -f "${OUTPUT_DIR}/generation_summary.json" ]; then
    echo "✓ S2生成报告已生成"
fi

if [ -f "${OUTPUT_DIR}/screening_report.json" ]; then
    echo "✓ S3筛选报告已生成"
fi

if [ -f "${OUTPUT_DIR}/sort_screened_report.json" ]; then
    echo "✓ S3+分类报告已生成"
fi

echo ""
echo "========================================"
