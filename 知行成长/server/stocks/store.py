"""股票复盘记录存储：独立模块，追踪股票操作和复盘思考。"""
import json
import sqlite3
import uuid
from contextlib import contextmanager, closing
from pathlib import Path
from datetime import datetime

from copilot.core import digest, encoded, fail, now


TABLES = '''
CREATE TABLE IF NOT EXISTS stock_records (
    id TEXT PRIMARY KEY, data TEXT NOT NULL);
'''


class StockStore:
    def __init__(self, root, db):
        self.root = Path(root).absolute()
        self.db = Path(db)
        self.runtime = self.db.parent / '.plans'
        self.startup_error = None

    @contextmanager
    def conn(self):
        with closing(sqlite3.connect(self.db, timeout=20)) as c:
            c.row_factory = sqlite3.Row
            with c:
                yield c

    def initialize(self):
        with self.conn() as c:
            c.executescript(TABLES)

    def list_records(self, status=None):
        """List all stock records, optionally filtered by status."""
        with self.conn() as c:
            rows = c.execute('SELECT data FROM stock_records').fetchall()
        records = [json.loads(r[0]) for r in rows]
        if status:
            records = [r for r in records if r.get('outcome') == status]
        records.sort(key=lambda r: r.get('date', ''), reverse=True)
        return records

    def get_record(self, record_id):
        """Get a single stock record by ID."""
        with self.conn() as c:
            row = c.execute('SELECT data FROM stock_records WHERE id=?', (record_id,)).fetchone()
        if not row:
            fail('not_found', '记录不存在。', 404)
        return json.loads(row[0])

    def create_record(self, data):
        """Create a new stock record."""
        record_id = 'stock-' + uuid.uuid4().hex[:16]
        record = {
            'id': record_id,
            'stock_code': data.get('stock_code', '').strip(),
            'stock_name': data.get('stock_name', '').strip(),
            'action': data.get('action', 'buy'),  # buy/sell/hold
            'date': data.get('date', now()[:10]),
            'price': float(data.get('price', 0)),
            'quantity': int(data.get('quantity', 0)) if data.get('quantity') else None,
            'rationale': data.get('rationale', '').strip(),
            'target_price': float(data.get('target_price', 0)) if data.get('target_price') else None,
            'stop_loss': float(data.get('stop_loss', 0)) if data.get('stop_loss') else None,
            'confidence': float(data.get('confidence', 0)) if data.get('confidence') else None,
            'outcome': 'pending',  # pending/success/failure
            'actual_price': None,
            'result_date': None,
            'profit_loss': None,
            'retrospective': None,
            'tags': data.get('tags') or [],
            'created_at': now(),
            'updated_at': now(),
        }
        with self.conn() as c:
            c.execute('INSERT INTO stock_records VALUES (?,?)', (record_id, encoded(record)))
        return record

    def update_record(self, record_id, data):
        """Update a stock record."""
        record = self.get_record(record_id)
        record.update({
            'stock_code': data.get('stock_code', record['stock_code']).strip(),
            'stock_name': data.get('stock_name', record['stock_name']).strip(),
            'action': data.get('action', record['action']),
            'date': data.get('date', record['date']),
            'price': float(data.get('price', record['price'])),
            'quantity': int(data.get('quantity', 0)) if data.get('quantity') else record.get('quantity'),
            'rationale': data.get('rationale', record['rationale']).strip(),
            'target_price': float(data.get('target_price', 0)) if data.get('target_price') else record.get('target_price'),
            'stop_loss': float(data.get('stop_loss', 0)) if data.get('stop_loss') else record.get('stop_loss'),
            'confidence': float(data.get('confidence', 0)) if data.get('confidence') else record.get('confidence'),
            'tags': data.get('tags', record.get('tags', [])),
            'updated_at': now(),
        })
        with self.conn() as c:
            c.execute('UPDATE stock_records SET data=? WHERE id=?', (encoded(record), record_id))
        return record

    def update_outcome(self, record_id, data):
        """Update the outcome and retrospective of a stock record."""
        record = self.get_record(record_id)
        record.update({
            'outcome': data.get('outcome', record['outcome']),
            'actual_price': float(data.get('actual_price', 0)) if data.get('actual_price') else None,
            'result_date': data.get('result_date', now()[:10]),
            'retrospective': data.get('retrospective'),
            'updated_at': now(),
        })
        # Calculate profit/loss if applicable
        if record.get('actual_price') and record.get('price') and record.get('quantity'):
            if record['action'] == 'buy':
                record['profit_loss'] = (record['actual_price'] - record['price']) * record['quantity']
            elif record['action'] == 'sell':
                record['profit_loss'] = (record['price'] - record['actual_price']) * record['quantity']
        with self.conn() as c:
            c.execute('UPDATE stock_records SET data=? WHERE id=?', (encoded(record), record_id))
        return record

    def delete_record(self, record_id):
        """Delete a stock record."""
        with self.conn() as c:
            c.execute('DELETE FROM stock_records WHERE id=?', (record_id,))
        return {'deleted': True}

    def get_statistics(self):
        """Get statistics about stock records."""
        records = self.list_records()
        total = len(records)
        completed = [r for r in records if r.get('outcome') in ('success', 'failure')]
        successes = [r for r in completed if r.get('outcome') == 'success']
        success_rate = len(successes) / len(completed) if completed else 0
        total_profit = sum(r.get('profit_loss', 0) or 0 for r in completed)
        return {
            'total': total,
            'completed': len(completed),
            'pending': total - len(completed),
            'successes': len(successes),
            'failures': len(completed) - len(successes),
            'success_rate': round(success_rate, 2),
            'total_profit_loss': total_profit,
        }
