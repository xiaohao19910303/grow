.PHONY: help start stop restart status logs test clean

# 知行成长 - Makefile 快捷命令

help:
	@./manage.sh help

# 启动服务
start:
	@./manage.sh start

# 停止服务
stop:
	@./manage.sh stop

# 重启服务
restart:
	@./manage.sh restart

# 查看状态
status:
	@./manage.sh status

# 查看日志
logs:
	@./manage.sh logs

# 测试服务
test:
	@echo "运行测试..."
	@cd server && ../.venv/bin/python -m pytest tests/ -v

# 清理临时文件
clean:
	@echo "清理临时文件..."
	@rm -f .server.pid .server.log
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true

# 快捷别名
up: start
down: stop
reload: restart
ps: status
log: logs
