#!/bin/bash
# 知行成长 - 服务管理脚本
# 用法: ./manage.sh [start|stop|restart|status|logs|help]

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$PROJECT_ROOT/.server.pid"
LOG_FILE="$PROJECT_ROOT/.server.log"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

log_step() {
    echo -e "${BLUE}→${NC} $1"
}

# 检查虚拟环境
check_venv() {
    if [ ! -x "$VENV_PYTHON" ]; then
        log_error "缺少项目虚拟环境"
        echo ""
        echo "请先按 README.md 完成环境配置："
        echo "  1. cd $PROJECT_ROOT"
        echo "  2. python3 -m venv .venv"
        echo "  3. source .venv/bin/activate"
        echo "  4. pip install fastapi uvicorn"
        echo "  5. pip install -r requirements-ai.txt (可选)"
        echo ""
        exit 1
    fi
}

# 检查依赖
check_deps() {
    log_step "检查服务依赖..."
    if ! "$VENV_PYTHON" -c 'import fastapi, uvicorn' 2>/dev/null; then
        log_error "虚拟环境缺少 fastapi 或 uvicorn"
        echo ""
        echo "请激活虚拟环境后安装依赖："
        echo "  source .venv/bin/activate"
        echo "  pip install fastapi uvicorn"
        echo ""
        exit 1
    fi
    log_info "依赖检查通过"
}

# 获取服务PID
get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    else
        echo ""
    fi
}

# 检查服务是否运行
is_running() {
    local pid=$1
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    return 1
}

# 启动服务
start() {
    log_step "启动知行成长服务..."

    # 检查是否已运行
    local pid=$(get_pid)
    if is_running "$pid"; then
        log_warn "服务已在运行 (PID: $pid)"
        echo "  使用 '$0 restart' 重启服务"
        echo "  使用 '$0 stop' 停止服务"
        exit 1
    fi

    # 检查环境
    check_venv
    check_deps

    # 配置
    local PORT=${PORT:-8756}
    local HOST=127.0.0.1

    # 局域网模式
    if [ "${COPILOT_LAN:-0}" = "1" ]; then
        if [ ${#COPILOT_ACCESS_TOKEN} -lt 24 ] || [ -z "${COPILOT_ALLOWED_HOSTS:-}" ]; then
            log_error "局域网模式需要至少24字符的 COPILOT_ACCESS_TOKEN 和 COPILOT_ALLOWED_HOSTS"
            exit 1
        fi
        HOST=0.0.0.0
        log_warn "局域网模式已启用，监听: 0.0.0.0:$PORT"
    fi

    # 清理旧PID文件
    rm -f "$PID_FILE"

    # 启动服务（后台运行）
    log_step "启动 uvicorn 服务..."
    cd "$PROJECT_ROOT/server"
    nohup "$VENV_PYTHON" -m uvicorn app:app --host "$HOST" --port "$PORT" \
        > "$LOG_FILE" 2>&1 &

    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"

    # 等待服务启动
    log_step "等待服务启动..."
    sleep 2

    # 检查启动结果
    if is_running "$new_pid"; then
        log_info "服务启动成功！"
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo -e "  ${GREEN}知行成长${NC} · 个人学习与成长平台"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo -e "  地址: ${BLUE}http://localhost:${PORT}${NC}"
        if [ "$HOST" = "0.0.0.0" ]; then
            echo -e "  局域网: ${BLUE}http://$(ipconfig getifaddr en0 2>/dev/null || echo '<本机IP>'):${PORT}${NC}"
        fi
        echo -e "  PID:  ${new_pid}"
        echo -e "  日志: ${LOG_FILE}"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "常用命令："
        echo "  $0 status    # 查看服务状态"
        echo "  $0 logs      # 查看实时日志"
        echo "  $0 stop      # 停止服务"
        echo "  $0 restart   # 重启服务"
        echo ""

        # 自动打开浏览器
        if command -v open >/dev/null 2>&1; then
            log_step "打开浏览器..."
            ( sleep 0.8; open "http://localhost:${PORT}" ) >/dev/null 2>&1 &
        fi
    else
        log_error "服务启动失败"
        echo "  请检查日志: $LOG_FILE"
        echo "  最近日志："
        tail -20 "$LOG_FILE" 2>/dev/null || echo "  (日志文件为空)"
        rm -f "$PID_FILE"
        exit 1
    fi
}

# 停止服务
stop() {
    log_step "停止知行成长服务..."

    local pid=$(get_pid)
    if [ -z "$pid" ]; then
        log_warn "服务未运行 (PID文件不存在)"
        rm -f "$PID_FILE"
        exit 0
    fi

    if ! is_running "$pid"; then
        log_warn "服务未运行 (PID: $pid 已失效)"
        rm -f "$PID_FILE"
        exit 0
    fi

    # 发送终止信号
    log_step "发送终止信号 (PID: $pid)..."
    kill "$pid" 2>/dev/null || true

    # 等待服务停止
    local max_wait=10
    local waited=0
    while is_running "$pid" && [ $waited -lt $max_wait ]; do
        sleep 1
        waited=$((waited + 1))
        if [ $waited -eq 5 ]; then
            log_step "等待服务优雅关闭..."
        fi
    done

    # 强制终止
    if is_running "$pid"; then
        log_warn "服务未响应，强制终止..."
        kill -9 "$pid" 2>/dev/null || true
        sleep 1
    fi

    # 清理PID文件
    rm -f "$PID_FILE"

    if ! is_running "$pid"; then
        log_info "服务已停止"
    else
        log_error "服务停止失败 (PID: $pid)"
        exit 1
    fi
}

# 重启服务
restart() {
    log_step "重启知行成长服务..."
    echo ""

    # 停止服务（如果正在运行）
    local pid=$(get_pid)
    if is_running "$pid"; then
        stop
        echo ""
    fi

    # 启动服务
    start
}

# 查看状态
status() {
    local pid=$(get_pid)

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "  ${GREEN}知行成长${NC} · 服务状态"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if is_running "$pid"; then
        echo -e "  状态: ${GREEN}● 运行中${NC}"
        echo -e "  PID:  $pid"

        # 获取端口
        local PORT=${PORT:-8756}
        echo -e "  地址: ${BLUE}http://localhost:${PORT}${NC}"

        # 检查进程信息
        local uptime=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ' || echo "未知")
        echo -e "  运行: $uptime"

        echo ""
        echo "  管理命令："
        echo "    $0 stop      # 停止服务"
        echo "    $0 restart   # 重启服务"
        echo "    $0 logs      # 查看日志"
    else
        echo -e "  状态: ${RED}● 已停止${NC}"
        if [ -n "$pid" ]; then
            echo -e "  PID:  $pid ${YELLOW}(已失效)${NC}"
        fi
        echo ""
        echo "  启动命令："
        echo "    $0 start     # 启动服务"
    fi

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# 查看日志
logs() {
    if [ ! -f "$LOG_FILE" ]; then
        log_warn "日志文件不存在: $LOG_FILE"
        exit 1
    fi

    log_info "实时日志 (Ctrl+C 退出)"
    echo ""
    tail -f "$LOG_FILE"
}

# 显示帮助
help() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "  ${GREEN}知行成长${NC} · 服务管理"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "用法: $0 <命令>"
    echo ""
    echo "命令："
    echo "  start      启动服务（后台运行）"
    echo "  stop       停止服务"
    echo "  restart    重启服务"
    echo "  status     查看服务状态"
    echo "  logs       查看实时日志"
    echo "  help       显示此帮助信息"
    echo ""
    echo "环境变量："
    echo "  PORT       服务端口 (默认: 8756)"
    echo "  COPILOT_LAN=1           启用局域网模式"
    echo "  COPILOT_ACCESS_TOKEN    访问令牌 (≥24字符)"
    echo "  COPILOT_ALLOWED_HOSTS   允许的主机 (逗号分隔)"
    echo ""
    echo "示例："
    echo "  $0 start                # 启动服务"
    echo "  $0 restart              # 重启服务"
    echo "  PORT=9000 $0 start      # 使用自定义端口"
    echo "  $0 logs                 # 查看日志"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# 主入口
case "${1:-help}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    help|-h|--help)
        help
        ;;
    *)
        log_error "未知命令: $1"
        help
        exit 1
        ;;
esac
