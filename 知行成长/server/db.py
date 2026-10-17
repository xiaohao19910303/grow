"""数据库抽象层 — PostgreSQL 兼容 sqlite3 接口

提供与 sqlite3 兼容的接口，使现有代码可以最少改动迁移到 PostgreSQL。
主要兼容点：
  - get_conn() 返回 psycopg2 连接，但支持 row_factory 行为（RealDictCursor）
  - SQL 占位符自动从 ? 转换为 %s
  - AUTOINCREMENT 转换为 SERIAL
"""
import os
import re
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras

# 数据库凭证仅从服务端环境变量读取。
DATABASE_URL = os.environ.get('DATABASE_URL', '')


def _translate_sql(sql):
    """将 sqlite3 风格 SQL 转换为 PostgreSQL 风格。
    - ? 占位符 → %s
    - AUTOINCREMENT → (空字符串，PostgreSQL 用 SERIAL 处理)
    """
    if sql is None:
        return None
    # 替换 ? 为 %s（但只在参数占位符位置，不在字符串内）
    # 简单处理：直接替换所有不在引号内的 ?
    result = []
    in_single_quote = False
    in_double_quote = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            result.append(ch)
        elif ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(ch)
        elif ch == '?' and not in_single_quote and not in_double_quote:
            result.append('%s')
        else:
            result.append(ch)
        i += 1
    translated = ''.join(result)
    return translated


def _translate_schema(sql):
    """转换 CREATE TABLE 语句中的 SQLite 特有语法。"""
    # Preserve auto-generated IDs for schemas still written in SQLite syntax.
    sql = re.sub(r'\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b', 'SERIAL PRIMARY KEY', sql, flags=re.IGNORECASE)
    sql = re.sub(r"datetime\('now',\s*'localtime'\)", "to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI:SS')", sql, flags=re.IGNORECASE)
    return sql


class CompatCursor:
    """兼容 sqlite3.Cursor 的 psycopg2 游标包装器。"""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        translated = _translate_sql(_translate_schema(sql)) if re.match(r'\s*CREATE\s', sql, re.I) else _translate_sql(sql)
        if params is not None:
            # psycopg2 需要 tuple 或 list
            if isinstance(params, dict):
                self._cursor.execute(translated, params)
            else:
                self._cursor.execute(translated, tuple(params))
        else:
            self._cursor.execute(translated)
        return self

    def executemany(self, sql, params_list):
        translated = _translate_sql(sql)
        self._cursor.executemany(translated, params_list)
        return self

    def executescript(self, sql):
        """执行多条 SQL 语句（兼容 sqlite3 的 executescript）。"""
        translated = _translate_schema(sql)
        translated = _translate_sql(translated)
        # PostgreSQL 不支持在同一个 execute 中运行多条语句？
        # 实际上 psycopg2 支持
        self._cursor.execute(translated)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return _make_row(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [_make_row(r) for r in rows]

    def fetchmany(self, size=None):
        if size is not None:
            rows = self._cursor.fetchmany(size)
        else:
            rows = self._cursor.fetchmany()
        return [_make_row(r) for r in rows]

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        """兼容 sqlite3 的 lastrowid。"""
        # psycopg2 在 INSERT 后需要查询
        try:
            self._cursor.execute("SELECT lastval()")
            row = self._cursor.fetchone()
            return next(iter(row.values())) if isinstance(row, dict) else (row[0] if row else None)
        except Exception:
            return None

    def close(self):
        self._cursor.close()

    def __iter__(self):
        return iter(_make_row(r) for r in self._cursor)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def _make_row(row):
    """将 psycopg2 行转换为类似 sqlite3.Row 的对象。
    支持通过索引和列名访问。
    """
    if row is None:
        return None
    if isinstance(row, dict):
        return DictRow(row)
    return TupleRow(row)


class TupleRow(tuple):
    """类似 sqlite3.Row 的行对象 — 支持索引和列名访问。"""

    def __new__(cls, values, keys=None):
        instance = super().__new__(cls, values)
        instance._keys = keys
        return instance

    def __getitem__(self, key):
        if isinstance(key, str):
            if self._keys:
                try:
                    idx = list(self._keys).index(key)
                    return super().__getitem__(idx)
                except (ValueError, IndexError):
                    raise KeyError(key)
            raise KeyError(key)
        return super().__getitem__(key)

    def keys(self):
        if self._keys:
            return list(self._keys)
        return []


class DictRow(dict):
    """字典风格的行对象。"""

    def __getitem__(self, key):
        if isinstance(key, int):
            keys = list(self.keys())
            if 0 <= key < len(keys):
                return super().__getitem__(keys[key])
            raise IndexError(key)
        return super().__getitem__(key)

    def __iter__(self):
        return iter(super().__getitem__(k) for k in self.keys())


class CompatConnection:
    """兼容 sqlite3.Connection 的 psycopg2 连接包装器。"""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        # 使用 RealDictCursor 以支持列名访问
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return CompatCursor(cursor)

    def execute(self, sql, params=None):
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def executescript(self, sql):
        cursor = self.cursor()
        cursor.executescript(sql)
        return cursor

    def executemany(self, sql, params_list):
        cursor = self.cursor()
        cursor.executemany(sql, params_list)
        return cursor

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()

    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, value):
        # sqlite3.Row 兼容性 — 忽略，因为我们已经用 RealDictCursor
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


def connect(database=None, **kwargs):
    """创建数据库连接，返回兼容 sqlite3 接口的连接对象。"""
    url = database or DATABASE_URL
    if not url:
        raise OperationalError('请在服务端配置 DATABASE_URL。')
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return CompatConnection(conn)


@contextmanager
def connection(database=None):
    """上下文管理器方式的数据库连接。"""
    conn = connect(database)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ===== 异常兼容 — 使代码中的 sqlite3.XxxError 仍然可用 =====

class Error(Exception):
    """基础数据库异常（兼容 sqlite3.Error）。"""
    pass


class IntegrityError(Error):
    """唯一约束等完整性错误（兼容 sqlite3.IntegrityError）。"""
    pass


class ProgrammingError(Error):
    """SQL 语法或逻辑错误（兼容 sqlite3.ProgrammingError）。"""
    pass


class DataError(Error):
    """数据类型错误（兼容 sqlite3.DataError）。"""
    pass


class OperationalError(Error):
    """运行时操作错误（兼容 sqlite3.OperationalError）。"""
    pass


class DatabaseError(Error):
    """数据库级别错误（兼容 sqlite3.DatabaseError）。"""
    pass


class InterfaceError(Error):
    """接口层错误（兼容 sqlite3.InterfaceError）。"""
    pass


class InternalError(Error):
    """数据库内部错误（兼容 sqlite3.InternalError）。"""
    pass


class NotSupportedError(Error):
    """不支持的操作（兼容 sqlite3.NotSupportedError）。"""
    pass


def _wrap_psycopg2_error(exc):
    """将 psycopg2 异常包装为兼容异常。"""
    if isinstance(exc, psycopg2.errors.UniqueViolation):
        return IntegrityError(str(exc))
    if isinstance(exc, psycopg2.IntegrityError):
        return IntegrityError(str(exc))
    if isinstance(exc, psycopg2.ProgrammingError):
        return ProgrammingError(str(exc))
    if isinstance(exc, psycopg2.DataError):
        return DataError(str(exc))
    if isinstance(exc, psycopg2.OperationalError):
        return OperationalError(str(exc))
    if isinstance(exc, psycopg2.DatabaseError):
        return DatabaseError(str(exc))
    if isinstance(exc, psycopg2.InterfaceError):
        return InterfaceError(str(exc))
    if isinstance(exc, psycopg2.InternalError):
        return InternalError(str(exc))
    if isinstance(exc, psycopg2.NotSupportedError):
        return NotSupportedError(str(exc))
    if isinstance(exc, psycopg2.Error):
        return Error(str(exc))
    return exc
