"""Legacy archive-format fixtures only. Never installed as an application backend."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from plans.store import Plans
from reflections.store import ReflectionsStore


class ArchiveConnection:
    @contextmanager
    def conn(self):
        connection=sqlite3.connect(self.db);connection.row_factory=sqlite3.Row
        try:
            with connection:yield connection
        finally:connection.close()


class OfflineArchivePlans(ArchiveConnection,Plans):
    def __init__(self,root,database):
        super().__init__(root,Path(database).parent/'offline-archive-runtime')
        self.db=Path(database)


class OfflineArchiveReflections(ArchiveConnection,ReflectionsStore):
    def __init__(self,root,database):
        super().__init__(root,Path(database).parent/'offline-archive-runtime')
        self.db=Path(database);self.remote=False
