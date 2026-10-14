#!/bin/bash
# 复用已有虚拟环境；启动不会安装或升级依赖。
set -e
cd "$(dirname "$0")"
PORT=${PORT:-8756}
HOST=127.0.0.1
if [ ! -x .venv/bin/python ]; then
  echo "缺少项目虚拟环境，请按 README.md 完成环境配置后再启动。"
  exit 1
fi
if [ "${COPILOT_LAN:-0}" = "1" ]; then
  if [ ${#COPILOT_ACCESS_TOKEN} -lt 24 ] || [ -z "${COPILOT_ALLOWED_HOSTS:-}" ]; then
    echo "局域网模式需要至少24字符的 COPILOT_ACCESS_TOKEN 和 COPILOT_ALLOWED_HOSTS。"
    exit 1
  fi
  HOST=0.0.0.0
fi
.venv/bin/python -c 'import fastapi, uvicorn' || {
  echo "现有虚拟环境缺少服务依赖，请查看 README.md。"
  exit 1
}
echo "知行成长：http://localhost:${PORT}；停止服务按 Ctrl+C"
if command -v open >/dev/null 2>&1; then
  ( sleep 1.2; open "http://localhost:${PORT}" ) >/dev/null 2>&1 &
fi
cd server
exec ../.venv/bin/python -m uvicorn app:app --host "$HOST" --port "$PORT"
