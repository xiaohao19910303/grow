#!/bin/bash
# Phase 1 后端功能验证脚本

set -e

echo "=========================================="
echo "Phase 1 后端功能验证"
echo "=========================================="
echo ""

cd "$(dirname "$0")"

# 检查是否在正确的目录
if [ ! -f "app.py" ]; then
    echo "❌ 错误: 请在 server 目录下运行此脚本"
    exit 1
fi

echo "📍 当前目录: $(pwd)"
echo ""

# 1. 检查数据库连接
echo "🔍 步骤 1/5: 检查数据库连接..."
python3 -c "import db; conn = db.connect(); print('✅ 数据库连接成功'); conn.close()" || {
    echo "❌ 数据库连接失败，请检查 DATABASE_URL 环境变量"
    exit 1
}
echo ""

# 2. 执行知识图谱 ID 迁移
echo "🔍 步骤 2/5: 执行知识图谱 ID 迁移..."
if python3 migrate_knowledge_stable_ids.py --verify 2>&1 | grep -q "验证通过"; then
    echo "✅ 知识图谱迁移已完成"
else
    echo "⚠️  知识图谱未迁移，开始执行迁移..."
    python3 migrate_knowledge_stable_ids.py
fi
echo ""

# 3. 执行学习计划状态迁移
echo "🔍 步骤 3/5: 执行学习计划状态迁移..."
if python3 migrate_plan_status.py --verify 2>&1 | grep -q "验证通过"; then
    echo "✅ 学习计划状态迁移已完成"
else
    echo "⚠️  学习计划状态未迁移，开始执行迁移..."
    python3 migrate_plan_status.py
fi
echo ""

# 4. 检查 Python 依赖
echo "🔍 步骤 4/5: 检查 Python 依赖..."
python3 -c "import fastapi; import psycopg2; print('✅ 依赖检查通过')" || {
    echo "❌ 依赖检查失败"
    exit 1
}
echo ""

# 5. 启动应用（如果未运行）
echo "🔍 步骤 5/5: 检查应用状态..."
if lsof -i :8756 > /dev/null 2>&1; then
    echo "✅ 应用已在运行 (端口 8756)"
else
    echo "⚠️  应用未运行，请手动启动:"
    echo "   python3 app.py"
fi
echo ""

echo "=========================================="
echo "✅ 验证准备完成！"
echo "=========================================="
echo ""
echo "下一步:"
echo "1. 确保应用在运行 (python3 app.py)"
echo "2. 运行 API 测试: python3 verify_apis.py"
echo ""
