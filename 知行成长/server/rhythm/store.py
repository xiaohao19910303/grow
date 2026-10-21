"""R02 storage bootstrap; business CRUD and event ingestion belong to later tasks."""
import db

from .schema import initialize


class RhythmStore:
    def initialize(self):
        # db.connect selects the trusted current_user schema. No fallback to
        # another account or to SQLite, and no default preference/event writes.
        with db.connect() as connection:
            return initialize(connection)
