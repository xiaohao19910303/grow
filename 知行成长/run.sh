#!/bin/bash
# 知行成长 - 一键启动脚本
# 用法: ./run.sh [命令]
# 命令: start|stop|restart|status|logs (默认: start)

set -e
cd "$(dirname "$0")"

# 默认启动服务
COMMAND=${1:-start}

case "$COMMAND" in
    start|up|run)
        echo ""
        echo "🚀 知行成长 · 一键启动"
        echo ""
        exec ./manage.sh start
        ;;
    stop|down)
        exec ./manage.sh stop
        ;;
    restart|reload)
        exec ./manage.sh restart
        ;;
    status|ps)
        exec ./manage.sh status
        ;;
    logs|log)
        exec ./manage.sh logs
        ;;
    *)
        echo "用法: $0 [命令]"
        echo ""
        echo "命令:"
        echo "  start    启动服务 (默认)"
        echo "  stop     停止服务"
        echo "  restart  重启服务"
        echo "  status   查看状态"
        echo "  logs     查看日志"
        echo ""
        echo "示例:"
        echo "  $0           # 启动服务"
        echo "  $0 restart   # 重启服务"
        echo "  $0 status    # 查看状态"
        exit 1
        ;;
esac
