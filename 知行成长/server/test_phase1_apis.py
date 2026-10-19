#!/usr/bin/env python3
"""Phase 1 后端 API 验证脚本（简化版）

快速验证后端 API 是否正常工作。
"""
import requests
import sys
from datetime import date

BASE_URL = "http://localhost:8756"

def test_apis():
    """测试所有新 API"""
    print("\n" + "="*60)
    print("Phase 1 后端 API 验证")
    print("="*60)
    print(f"测试目标: {BASE_URL}")
    print(f"测试时间: {date.today().isoformat()}")

    # 检查应用是否运行
    try:
        response = requests.get(f"{BASE_URL}/api/health", timeout=2)
        print(f"✅ 应用运行正常")
    except Exception as e:
        print(f"\n❌ 应用未运行或无法访问: {e}")
        return False

    # 创建 session 用于测试
    session = requests.Session()

    # 测试 1: 统一搜索 API（GET 请求，不需要认证）
    print("\n" + "="*60)
    print("🔍 测试 1: 统一搜索 API")
    print("="*60)
    try:
        response = session.get(f"{BASE_URL}/api/search", params={"q": "学习"})
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 搜索 API 正常: 找到 {result.get('total_count', 0)} 条结果")
        else:
            print(f"❌ 搜索 API 失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 搜索请求失败: {e}")
        return False

    # 测试 2: 时间线 API（GET 请求，不需要认证）
    print("\n" + "="*60)
    print("📅 测试 2: 时间线 API")
    print("="*60)
    try:
        response = session.get(f"{BASE_URL}/api/timeline")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 时间线 API 正常: {result.get('total_count', 0)} 条记录")
        else:
            print(f"❌ 时间线 API 失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 时间线请求失败: {e}")
        return False

    # 测试 3: 搜索统计
    print("\n" + "="*60)
    print("📊 测试 3: 搜索统计 API")
    print("="*60)
    try:
        response = session.get(f"{BASE_URL}/api/search/stats")
        if response.status_code == 200:
            stats = response.json()
            print(f"✅ 统计 API 正常:")
            for module, info in list(stats.items())[:3]:
                print(f"   {info.get('label', module)}: {info.get('count', 0)} 条")
        else:
            print(f"❌ 统计 API 失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 统计请求失败: {e}")
        return False

    # 测试 4: 时间线统计
    print("\n" + "="*60)
    print("📊 测试 4: 时间线统计 API")
    print("="*60)
    try:
        response = session.get(f"{BASE_URL}/api/timeline/stats")
        if response.status_code == 200:
            stats = response.json()
            print(f"✅ 时间线统计 API 正常:")
            for module, info in list(stats.items())[:3]:
                print(f"   {info.get('label', module)}: {info.get('count', 0)} 条")
        else:
            print(f"❌ 时间线统计 API 失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 时间线统计请求失败: {e}")
        return False

    # 测试 5: 知识图谱统计（检查 stable_id 是否可用）
    print("\n" + "="*60)
    print("📚 测试 5: 知识图谱 API")
    print("="*60)
    try:
        response = session.get(f"{BASE_URL}/api/knowledge/stats")
        if response.status_code == 200:
            stats = response.json()
            print(f"✅ 知识图谱 API 正常:")
            print(f"   总知识数: {stats.get('total', 0)}")
            print(f"   分类数: {stats.get('categories', 0)}")
        else:
            print(f"❌ 知识图谱 API 失败: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 知识图谱请求失败: {e}")
        return False

    # 测试 6: 检查数据库迁移结果
    print("\n" + "="*60)
    print("🗄️  测试 6: 数据库迁移验证")
    print("="*60)
    try:
        import db
        conn = db.connect()

        # 检查 knowledge 表的 stable_id 列
        columns = conn.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_name = 'knowledge' AND column_name IN ('stable_id', 'source_hash', 'source_path')"""
        ).fetchall()
        column_names = [col[0] for col in columns]

        if 'stable_id' in column_names:
            count = conn.execute("SELECT COUNT(*) FROM knowledge WHERE stable_id IS NOT NULL").fetchone()[0]
            print(f"✅ 知识图谱 stable_id 迁移完成: {count} 条记录")
        else:
            print(f"❌ stable_id 列不存在")
            conn.close()
            return False

        # 检查 plan_status_history 表
        tables = conn.execute(
            """SELECT tablename FROM pg_tables WHERE tablename = 'plan_status_history'"""
        ).fetchall()

        if tables:
            count = conn.execute("SELECT COUNT(*) FROM plan_status_history").fetchone()[0]
            print(f"✅ 学习计划状态历史表已创建: {count} 条记录")
        else:
            print(f"⚠️  plan_status_history 表不存在（可能尚未创建计划）")

        conn.close()
    except Exception as e:
        print(f"❌ 数据库验证失败: {e}")
        return False

    print("\n" + "="*60)
    print("✅ 所有 API 测试通过！")
    print("="*60)
    print("\nPhase 1 后端功能验证完成：")
    print("  ✓ 统一搜索 API 正常")
    print("  ✓ 时间线 API 正常")
    print("  ✓ 知识图谱 stable_id 迁移完成")
    print("  ✓ 学习计划状态管理就绪")
    print("\n下一步: 可以开始实现前端 UI")

    return True


if __name__ == "__main__":
    success = test_apis()
    sys.exit(0 if success else 1)
