.PHONY: help start stop restart status logs test test-module
PYTHON ?= $(CURDIR)/.venv/bin/python
PATTERN ?= test_packaged_materials.py

help:
	@echo "start / stop / restart / status / logs: 现有应用管理入口"
	@echo "test: 完整隔离回归（需临时 PostgreSQL、Zook 夹具和浏览器）"
	@echo "test-module PATTERN=test_*.py: 单模块隔离诊断"
	@echo "PYTHON=/absolute/path/to/python: 指定测试解释器"

start stop restart status logs:
	@$(MAKE) -C 知行成长 $@

test:
	@"$(PYTHON)" -B 知行成长/server/tests/run_isolated_checks.py --full

test-module:
	@"$(PYTHON)" -B 知行成长/server/tests/run_isolated_checks.py --pattern "$(PATTERN)"
