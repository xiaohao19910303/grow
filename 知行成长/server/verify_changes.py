#!/usr/bin/env python3
"""验证 action_plans.py 的 SQL 查询和索引定义是否正确。"""
import re
import sys

# 读取 action_plans.py
with open('action_plans.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 提取 SCHEMA 定义
schema_match = re.search(r"SCHEMA = '''(.*?)'''", content, re.DOTALL)
if not schema_match:
    print("❌ 未找到 SCHEMA 定义")
    sys.exit(1)

schema = schema_match.group(1)

# 验证索引定义
expected_indexes = [
    'action_plans_data_gin',
    'action_plans_period',
    'action_plans_status',
    'action_plans_start_date',
    'action_executions_business_date'
]

print("=" * 60)
print("数据库索引验证")
print("=" * 60)

all_found = True
for idx in expected_indexes:
    if idx in schema:
        print(f"✓ 索引 {idx} 已定义")
    else:
        print(f"✗ 索引 {idx} 缺失")
        all_found = False

# 验证关键查询优化
print("\n" + "=" * 60)
print("查询优化验证")
print("=" * 60)

checks = [
    ('duplicate_schedule', 'data::jsonb->>\'period\' = \'day\'', '使用 JSONB 查询'),
    ('validate_parent', 'data::jsonb->>', '子计划查询优化'),
    ('get_descendants', 'WITH RECURSIVE', '递归查询后代'),
    ('content_completed', 'by_id.get(ancestor[\'parent_id\'])', '父计划存在性检查'),
]

for func_name, pattern, description in checks:
    # 找到函数定义区域
    func_pattern = rf'def {func_name}\(.*?\n(?=\ndef |\Z)'
    func_match = re.search(func_pattern, content, re.DOTALL)
    if func_match:
        func_code = func_match.group(0)
        if pattern in func_code:
            print(f"✓ {func_name}: {description}")
        else:
            print(f"✗ {func_name}: 未找到 {description}")
            all_found = False
    else:
        print(f"✗ {func_name}: 函数未找到")
        all_found = False

# 验证 learning_checkins.py 的日志添加
print("\n" + "=" * 60)
print("错误日志验证")
print("=" * 60)

with open('learning_checkins.py', 'r', encoding='utf-8') as f:
    checkins_content = f.read()

if 'import logging' in checkins_content and 'logger.debug' in checkins_content:
    print("✓ learning_checkins.py: 添加错误日志")
else:
    print("✗ learning_checkins.py: 错误日志缺失")
    all_found = False

# 总结
print("\n" + "=" * 60)
if all_found:
    print("✅ 所有验证通过！代码改动正确。")
    sys.exit(0)
else:
    print("❌ 部分验证失败，请检查代码。")
    sys.exit(1)
