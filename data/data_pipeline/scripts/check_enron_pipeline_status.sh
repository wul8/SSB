#!/bin/bash
# 检查Enron batch1管线状态并显示结果

GEN_DIR="/mnt/hhq/data/data_pipeline/generated_tasks/route_b_enron_batch1"

echo "========================================"
echo "Enron Batch1 管线状态检查"
echo "========================================"
echo ""

# 检查任务生成数量
DEBUG_COUNT=$(ls ${GEN_DIR}/debugging/*.json 2>/dev/null | wc -l)
TEMPLATE_COUNT=$(ls ${GEN_DIR}/template/*.json 2>/dev/null | wc -l)

echo "已生成任务:"
echo "  - Debugging: ${DEBUG_COUNT} 个"
echo "  - Template: ${TEMPLATE_COUNT} 个"
echo ""

# 检查S2生成报告
if [ -f "${GEN_DIR}/generation_summary.json" ]; then
    echo "✓ S2生成报告已生成:"
    echo "  ${GEN_DIR}/generation_summary.json"
    echo ""
fi

# 检查S3筛选报告
if [ -f "${GEN_DIR}/screening_report.json" ]; then
    echo "✓ S3筛选报告已生成:"
    echo "  ${GEN_DIR}/screening_report.json"
    cat "${GEN_DIR}/screening_report.json" | python3 -m json.tool | head -30
    echo ""
fi

# 检查S3+分类报告
if [ -f "${GEN_DIR}/sort_screened_report.json" ]; then
    echo "✓ S3+分类报告已生成:"
    echo "  ${GEN_DIR}/sort_screened_report.json"
    cat "${GEN_DIR}/sort_screened_report.json" | python3 -m json.tool
    echo ""
fi

# 检查passed/rejected目录
if [ -d "${GEN_DIR}/passed" ]; then
    PASSED_DEBUG=$(find ${GEN_DIR}/passed/debugging -name "*.json" 2>/dev/null | wc -l)
    PASSED_TEMPLATE=$(find ${GEN_DIR}/passed/template -name "*.json" 2>/dev/null | wc -l)
    echo "✓ Passed任务:"
    echo "  - Debugging: ${PASSED_DEBUG} 个"
    echo "  - Template: ${PASSED_TEMPLATE} 个"
    echo ""
fi

if [ -d "${GEN_DIR}/rejected" ]; then
    REJECTED_DEBUG=$(find ${GEN_DIR}/rejected/debugging -name "*.json" 2>/dev/null | wc -l)
    REJECTED_TEMPLATE=$(find ${GEN_DIR}/rejected/template -name "*.json" 2>/dev/null | wc -l)
    echo "✓ Rejected任务:"
    echo "  - Debugging: ${REJECTED_DEBUG} 个"
    echo "  - Template: ${REJECTED_TEMPLATE} 个"
    echo ""
fi

echo "========================================"
