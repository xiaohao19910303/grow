"""Private rhythm bootstrap and handoff data-preservation guard."""
import db

from .schema import initialize


def has_data(connection):
    from .schema import BUSINESS_TABLES
    for table in BUSINESS_TABLES:
        if (connection.execute('SELECT to_regclass(?)', (table,)).fetchone()[0] is not None
                and connection.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone()):
            return True
    return False


class RhythmStore:
    def initialize(self):
        # db.connect selects the trusted current_user schema. No fallback to
        # another account or to SQLite, and no default preference/event writes.
        with db.connect() as connection:
            return initialize(connection)
