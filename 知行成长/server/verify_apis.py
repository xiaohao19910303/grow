#!/usr/bin/env python3
"""Phase 1 后端 API 验证脚本

测试所有新实现的 API 端点：
1. 知识图谱 stable_id API
2. 统一搜索 API
3. 时间线 API
4. 学习计划状态管理 API
"""
import requests
import json
import sys
from datetime import date, timedelta

BASE_URL = "http://localhost:8756"

# 测试账户
TEST_USERNAME = "test_admin"
TEST_PASSWORD = "test123456"

def setup_auth():
    """设置认证 - 注册并登录"""
    print("\n🔐 设置认证...")

    # 尝试注册
    try:
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD,
            "invitation": ""
        })
        if response.status_code == 200:
            print(f"✅ 注册成功: {TEST_USERNAME}")
        elif response.status_code == 409:
            print(f"⚠️  用户已存在，尝试登录")
        else:
            print(f"⚠️  注册失败: {response.status_code}")
    except Exception as e:
        print(f"⚠️  注册请求失败: {e}")

    # 登录获取 session
    try:
        session = requests.Session()
        response = session.post(f"{BASE_URL}/api/auth/login", json={
            "username": TEST_USERNAME,
            "password": TEST_PASSWORD
        })
        if response.status_code == 200:
            print(f"✅ 登录成功")
            return session
        else:
            print(f"❌ 登录失败: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ 登录请求失败: {e}")
        return None


def test_knowledge_stable_id(session):
    """测试知识图谱 stable_id API"""
    print("\n" + "="*60)
    print("📚 测试 1: 知识图谱 stable_id API")
    print("="*60)

    # 1. 测试 upsert 创建新知识节点
    print("\n🔍 测试 1.1: 创建知识节点 (upsert)")
    test_data = {
        "name": "贝叶斯定理",
        "category": "概率论",
        "summary": "贝叶斯定理是概率论中的一个重要定理，描述了在已知先验概率的条件下，如何根据新的证据更新概率。",
        "source": "概率论教材",
        "kind": "theorem",
        "date": date.today().isoformat(),
        "source_path": "/test/bayes_theorem.md",
        "source_hash": "test_hash_" + date.today().isoformat()
    }

    try:
        response = requests.post(f"{BASE_URL}/api/knowledge/upsert", json=test_data)
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                stable_id = result['knowledge']['stable_id']
                print(f"✅ 创建成功: stable_id={stable_id[:8]}...")
            else:
                print(f"❌ 创建失败: {result}")
                return False
        else:
            print(f"❌ HTTP 错误: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 2. 测试通过 stable_id 获取
    print(f"\n🔍 测试 1.2: 通过 stable_id 获取知识节点")
    try:
        response = requests.get(f"{BASE_URL}/api/knowledge/by-stable-id/{stable_id}")
        if response.status_code == 200:
            node = response.json()
            if node['name'] == "贝叶斯定理":
                print(f"✅ 获取成功: {node['name']}")
            else:
                print(f"❌ 数据不匹配: {node}")
                return False
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 3. 测试幂等性（再次 upsert 相同数据）
    print(f"\n🔍 测试 1.3: 测试幂等导入（更新相同节点）")
    test_data['name'] = "贝叶斯定理（已更新）"
    try:
        response = requests.post(f"{BASE_URL}/api/knowledge/upsert", json=test_data)
        if response.status_code == 200:
            result = response.json()
            updated_id = result['knowledge']['stable_id']
            if updated_id == stable_id:
                print(f"✅ 幂等性验证通过: stable_id 保持不变")
            else:
                print(f"❌ 幂等性验证失败: stable_id 发生变化")
                return False
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 4. 测试获取相关知识点
    print(f"\n🔍 测试 1.4: 获取相关知识点")
    try:
        response = requests.get(f"{BASE_URL}/api/knowledge/by-stable-id/{stable_id}/related?limit=3")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 获取相关知识点: {result['count']} 个")
        else:
            print(f"⚠️  HTTP {response.status_code} (可能没有相关节点)")
    except Exception as e:
        print(f"⚠️  请求失败: {e}")

    print("\n✅ 知识图谱 stable_id API 测试通过")
    return True


def test_search_api():
    """测试统一搜索 API"""
    print("\n" + "="*60)
    print("🔍 测试 2: 统一搜索 API")
    print("="*60)

    # 1. 测试基本搜索
    print("\n🔍 测试 2.1: 基本搜索")
    try:
        response = requests.get(f"{BASE_URL}/api/search", params={"q": "概率"})
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 搜索成功: 找到 {result['total_count']} 条结果")
            if result['results']:
                print(f"   第一条: {result['results'][0]['title']}")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 2. 测试带筛选的搜索
    print("\n🔍 测试 2.2: 带模块类型筛选的搜索")
    try:
        response = requests.get(f"{BASE_URL}/api/search", params={
            "q": "学习",
            "types": "learning,knowledge",
            "page": 1,
            "page_size": 10
        })
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 筛选搜索成功: {result['total_count']} 条结果")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 3. 测试日期范围筛选
    print("\n🔍 测试 2.3: 带日期范围的搜索")
    try:
        start_date = (date.today() - timedelta(days=30)).isoformat()
        end_date = date.today().isoformat()
        response = requests.get(f"{BASE_URL}/api/search", params={
            "q": "决策",
            "start_date": start_date,
            "end_date": end_date
        })
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 日期筛选成功: {result['total_count']} 条结果")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 4. 测试搜索统计
    print("\n🔍 测试 2.4: 获取搜索统计")
    try:
        response = requests.get(f"{BASE_URL}/api/search/stats")
        if response.status_code == 200:
            stats = response.json()
            print(f"✅ 统计信息:")
            for module, info in stats.items():
                print(f"   {info['label']}: {info['count']} 条")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 5. 测试空关键词（应该返回 400）
    print("\n🔍 测试 2.5: 空关键词验证")
    try:
        response = requests.get(f"{BASE_URL}/api/search", params={"q": ""})
        if response.status_code == 400:
            print(f"✅ 正确返回 400 错误")
        else:
            print(f"❌ 应该返回 400，实际返回 {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    print("\n✅ 统一搜索 API 测试通过")
    return True


def test_timeline_api():
    """测试时间线 API"""
    print("\n" + "="*60)
    print("📅 测试 3: 时间线 API")
    print("="*60)

    # 1. 测试基本时间线
    print("\n🔍 测试 3.1: 获取时间线（默认参数）")
    try:
        response = requests.get(f"{BASE_URL}/api/timeline")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 时间线获取成功: {result['total_count']} 条记录")
            if result['records']:
                print(f"   第一条: {result['records'][0]['title']}")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 2. 测试带日期范围的时间线
    print("\n🔍 测试 3.2: 带日期范围的时间线")
    try:
        start_date = (date.today() - timedelta(days=7)).isoformat()
        end_date = date.today().isoformat()
        response = requests.get(f"{BASE_URL}/api/timeline", params={
            "start_date": start_date,
            "end_date": end_date
        })
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 日期筛选成功: {result['total_count']} 条记录")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 3. 测试带模块类型筛选的时间线
    print("\n🔍 测试 3.3: 带模块类型筛选的时间线")
    try:
        response = requests.get(f"{BASE_URL}/api/timeline", params={
            "types": "learning,reflection,decision"
        })
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 类型筛选成功: {result['total_count']} 条记录")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 4. 测试分页
    print("\n🔍 测试 3.4: 时间线分页")
    try:
        response = requests.get(f"{BASE_URL}/api/timeline", params={
            "page": 1,
            "page_size": 5
        })
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 分页成功: 第 {result['page']} 页，每页 {result['page_size']} 条")
            print(f"   返回 {len(result['records'])} 条记录")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 5. 测试时间线统计
    print("\n🔍 测试 3.5: 获取时间线统计")
    try:
        response = requests.get(f"{BASE_URL}/api/timeline/stats")
        if response.status_code == 200:
            stats = response.json()
            print(f"✅ 统计信息:")
            for module, info in stats.items():
                print(f"   {info['label']}: {info['count']} 条")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    print("\n✅ 时间线 API 测试通过")
    return True


def test_plan_status_api():
    """测试学习计划状态管理 API"""
    print("\n" + "="*60)
    print("📋 测试 4: 学习计划状态管理 API")
    print("="*60)

    # 首先获取一个计划 ID
    print("\n🔍 准备: 获取学习计划列表")
    try:
        response = requests.get(f"{BASE_URL}/api/plans")
        if response.status_code == 200:
            result = response.json()
            plans = result.get('plans', [])
            if not plans:
                print("⚠️  没有学习计划，跳过状态管理测试")
                print("   提示: 请先创建一个学习计划")
                return True
            plan_id = plans[0]['id']
            print(f"✅ 使用计划: {plan_id}")
        else:
            print(f"❌ 获取计划列表失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 1. 测试暂停计划
    print(f"\n🔍 测试 4.1: 暂停计划 ({plan_id})")
    try:
        response = requests.post(
            f"{BASE_URL}/api/plans/{plan_id}/pause",
            json={"data": {"key": "test_pause", "reason": "测试暂停"}},
            headers={"x-copilot-request": "1"}
        )
        if response.status_code == 200:
            print(f"✅ 暂停成功")
        elif response.status_code == 422 and "已处于暂停状态" in response.text:
            print(f"⚠️  计划已处于暂停状态")
        else:
            print(f"❌ HTTP 错误: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 2. 测试获取状态历史
    print(f"\n🔍 测试 4.2: 获取状态历史")
    try:
        response = requests.get(f"{BASE_URL}/api/plans/{plan_id}/status-history")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 状态历史: {len(result['history'])} 条记录")
            for record in result['history'][:3]:
                print(f"   {record['from_status']} → {record['to_status']} @ {record['changed_at'][:10]}")
        else:
            print(f"❌ HTTP 错误: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 3. 测试恢复计划
    print(f"\n🔍 测试 4.3: 恢复计划")
    try:
        response = requests.post(
            f"{BASE_URL}/api/plans/{plan_id}/resume",
            json={"data": {"key": "test_resume", "reason": "测试恢复"}},
            headers={"x-copilot-request": "1"}
        )
        if response.status_code == 200:
            print(f"✅ 恢复成功")
        elif response.status_code == 422 and "只能恢复已暂停的计划" in response.text:
            print(f"⚠️  计划不是暂停状态")
        else:
            print(f"❌ HTTP 错误: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 4. 测试归档计划
    print(f"\n🔍 测试 4.4: 归档计划")
    try:
        response = requests.post(
            f"{BASE_URL}/api/plans/{plan_id}/archive",
            json={"data": {"key": "test_archive", "reason": "测试归档"}},
            headers={"x-copilot-request": "1"}
        )
        if response.status_code == 200:
            print(f"✅ 归档成功")
        elif response.status_code == 422 and "已处于归档状态" in response.text:
            print(f"⚠️  计划已处于归档状态")
        else:
            print(f"❌ HTTP 错误: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    # 5. 测试再次归档（应该失败）
    print(f"\n🔍 测试 4.5: 重复归档验证（应该失败）")
    try:
        response = requests.post(
            f"{BASE_URL}/api/plans/{plan_id}/archive",
            json={"data": {"key": "test_archive2", "reason": "重复归档"}},
            headers={"x-copilot-request": "1"}
        )
        if response.status_code == 422:
            print(f"✅ 正确拒绝重复归档")
        else:
            print(f"❌ 应该返回 422，实际返回 {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False

    print("\n✅ 学习计划状态管理 API 测试通过")
    return True


def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("Phase 1 后端 API 验证")
    print("="*60)
    print(f"测试目标: {BASE_URL}")
    print(f"测试时间: {date.today().isoformat()}")

    # 检查应用是否运行
    try:
        response = requests.get(f"{BASE_URL}/api/storage-status", timeout=2)
        print(f"✅ 应用运行正常")
    except Exception as e:
        print(f"\n❌ 应用未运行或无法访问: {e}")
        print(f"\n请先启动应用:")
        print(f"  cd /Users/hao/Documents/grow/知行成长/server")
        print(f"  python3 app.py")
        sys.exit(1)

    # 运行所有测试
    results = {}
    results['知识图谱 stable_id'] = test_knowledge_stable_id()
    results['统一搜索'] = test_search_api()
    results['时间线'] = test_timeline_api()
    results['学习计划状态'] = test_plan_status_api()

    # 输出总结
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)

    all_passed = True
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{status} - {name}")
        if not passed:
            all_passed = False

    print("\n" + "="*60)
    if all_passed:
        print("🎉 所有测试通过！")
        print("="*60)
        print("\n下一步:")
        print("1. 可以开始实现前端 UI")
        print("2. 或者继续使用其他功能")
        sys.exit(0)
    else:
        print("⚠️  部分测试失败")
        print("="*60)
        print("\n请检查失败的测试并修复问题")
        sys.exit(1)


if __name__ == "__main__":
    main()
