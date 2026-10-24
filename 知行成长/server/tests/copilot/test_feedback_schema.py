"""Feedback schema uses the same disposable PostgreSQL contract as the app."""
from test_legacy_cloud_schema import PostgreSQLFixture
import db
from copilot.schema import TABLES

class FeedbackSchemaContract(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        with db.connect() as connection:connection.executescript(TABLES)

    def test_copilot_feedback_table_exists(self):
        with db.connect() as connection:
            self.assertIsNotNone(connection.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='copilot_feedback'").fetchone())

    def test_copilot_feedback_table_schema(self):
        with db.connect() as connection:
            columns={row[0] for row in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='copilot_feedback'")}
        self.assertTrue({'id','module_id','round_id','lesson_no','mastery_level','value_rating','feeling_tags','key_learnings','questions','next_direction','created_at'}<=columns)
