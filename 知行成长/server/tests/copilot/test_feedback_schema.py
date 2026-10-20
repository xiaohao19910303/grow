import pytest
import db

def test_copilot_feedback_table_exists():
    """验证 copilot_feedback 表已创建"""
    with db.connect() as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='copilot_feedback'").fetchone()
        assert row is not None, "copilot_feedback 表不存在"

def test_copilot_feedback_table_schema():
    """验证表结构包含所有必需字段"""
    with db.connect() as conn:
        columns = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(copilot_feedback)")}
        assert 'id' in columns
        assert 'module_id' in columns
        assert 'round_id' in columns
        assert 'lesson_no' in columns
        assert 'mastery_level' in columns
        assert 'value_rating' in columns
        assert 'feeling_tags' in columns
        assert 'key_learnings' in columns
        assert 'questions' in columns
        assert 'next_direction' in columns
        assert 'created_at' in columns
