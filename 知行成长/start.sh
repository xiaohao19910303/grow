#!/bin/bash
# 知行成长 - 快速启动脚本（向后兼容）
# 推荐改用: ./manage.sh start

set -e
cd "$(dirname "$0")"

echo "提示: 推荐使用统一的管理脚本"
echo "  ./manage.sh start    # 启动服务"
echo "  ./manage.sh restart  # 重启服务"
echo "  ./manage.sh status   # 查看状态"
echo "  ./manage.sh help     # 帮助信息"
echo ""

exec ./manage.sh start
