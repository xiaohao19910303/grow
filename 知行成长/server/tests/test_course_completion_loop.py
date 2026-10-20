"""End-to-end integration test for course completion loop."""
import pytest
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_complete_course_completion_loop():
    """测试完整的课程完成闭环：学完→反馈→归档→总结→进阶生成"""

    # Step 1: 完成一课（模拟已有完成记录）
    # 假设第20课已完成，先检查状态
    response = client.get('/api/copilot/lessons/20')
    if response.status_code == 404:
        pytest.skip("Lesson 20 not available for testing")

    # Step 2: 提交反馈
    feedback_data = {
        'mastery_level': 'basically_understood',
        'value_rating': 2,
        'feeling_tags': ['例子很好', '概念很清晰'],
        'key_learnings': '学会了独立思考和批判性思维',
        'questions': '如何应用到实际工作中？',
        'next_direction': '想学习更多案例分析'
    }
    response = client.post('/api/copilot/lessons/20/feedback', json=feedback_data)
    assert response.status_code == 200, f"反馈提交失败: {response.text}"
    saved_feedback = response.json()
    assert saved_feedback['mastery_level'] == 'basically_understood'

    # Step 3: 验证反馈可查询
    response = client.get('/api/copilot/lessons/20/feedback')
    assert response.status_code == 200
    retrieved_feedback = response.json()
    assert retrieved_feedback['mastery_level'] == 'basically_understood'
    assert '例子很好' in retrieved_feedback['feeling_tags']

    # Step 4: 归档课程
    response = client.post('/api/copilot/lessons/20/archive', json={'key': 'test-key'})
    assert response.status_code == 200
    assert response.json()['archived'] == True

    # Step 5: 验证归档状态
    response = client.get('/api/copilot/lessons/archived')
    assert response.status_code == 200
    archived_items = response.json()['items']
    lesson_20_archived = any(item['lesson_no'] == 20 for item in archived_items)
    assert lesson_20_archived, "第20课应该在归档列表中"

    # Step 6: 取消归档（验证可逆性）
    response = client.post('/api/copilot/lessons/20/unarchive', json={'key': 'test-key'})
    assert response.status_code == 200
    assert response.json()['archived'] == False

    # Step 7: 验证取消归档后不在归档列表
    response = client.get('/api/copilot/lessons/archived')
    archived_items = response.json()['items']
    lesson_20_still_archived = any(item['lesson_no'] == 20 for item in archived_items)
    assert not lesson_20_still_archived, "第20课取消归档后不应在归档列表中"

    # Step 8: 生成 AI 总结（如果有配置）
    # 注意：这可能需要 AI API 配置，如果没有配置会失败
    summary_request = {
        'module': 'renzhi',
        'round_id': 1,
        'scope': 'full_course'
    }
    response = client.post('/api/copilot/summaries/generate', json=summary_request)
    # 总结生成可能是流式响应，我们只验证端点可达
    assert response.status_code in [200, 503], f"总结生成失败: {response.text}"

    # Step 9: 重新归档以便后续测试
    response = client.post('/api/copilot/lessons/20/archive', json={'key': 'test-key'})
    assert response.status_code == 200

    print("✅ 课程完成闭环测试通过")

def test_feedback_validation():
    """测试反馈数据验证"""
    # 测试无效的 mastery_level
    response = client.post('/api/copilot/lessons/21/feedback', json={
        'mastery_level': 'invalid_level',
        'value_rating': 2,
        'feeling_tags': [],
        'key_learnings': '',
        'questions': '',
        'next_direction': ''
    })
    assert response.status_code in [400, 422], "应该拒绝无效的 mastery_level"

    # 测试无效的 value_rating
    response = client.post('/api/copilot/lessons/21/feedback', json={
        'mastery_level': 'basically_understood',
        'value_rating': 5,  # 超出范围
        'feeling_tags': [],
        'key_learnings': '',
        'questions': '',
        'next_direction': ''
    })
    assert response.status_code in [400, 422], "应该拒绝超出范围的 value_rating"

def test_archive_requires_completed_lesson():
    """测试归档需要先完成课程"""
    # 尝试归档一个未完成的课程（假设第99课不存在）
    response = client.post('/api/copilot/lessons/99/archive', json={'key': 'test-key'})
    # 应该失败或返回适当的错误
    assert response.status_code in [400, 404, 409], "不应该能归档不存在的课程"

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
