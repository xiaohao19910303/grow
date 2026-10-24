"""Course feedback schema on the disposable PostgreSQL course backend."""
from cloud_fixtures import CloudFixture


class FeedbackSchemaTests(CloudFixture):
    def setUp(self):
        super().setUp()
        self.store = self.new_course()
        self.store.initialize()

    def test_copilot_feedback_table_exists(self):
        with self.store.conn() as connection:
            row = connection.execute('''
                SELECT table_name FROM information_schema.tables
                WHERE table_schema=current_schema() AND table_name='copilot_feedback'
            ''').fetchone()
        self.assertIsNotNone(row, 'copilot_feedback 表不存在')
        self.assertEqual(row[0], 'copilot_feedback')

    def test_copilot_feedback_table_schema(self):
        with self.store.conn() as connection:
            columns = {row['column_name']: row['data_type'] for row in connection.execute('''
                SELECT column_name,data_type FROM information_schema.columns
                WHERE table_schema=current_schema() AND table_name='copilot_feedback'
            ''').fetchall()}
        self.assertEqual(columns, {
            'id': 'integer',
            'module_id': 'text',
            'round_id': 'integer',
            'lesson_no': 'integer',
            'mastery_level': 'text',
            'value_rating': 'integer',
            'feeling_tags': 'text',
            'key_learnings': 'text',
            'questions': 'text',
            'next_direction': 'text',
            'created_at': 'text',
        })
