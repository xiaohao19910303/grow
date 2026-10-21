"""Timeline and search share the same saved-record sources and dates."""
from datetime import datetime
from zoneinfo import ZoneInfo
from search_service import SEARCHABLE_MODULES, collect_records

TIMELINE_MODULES = SEARCHABLE_MODULES


class TimelineService:
    def __init__(self, db_path):
        self.db_path = db_path

    def get_timeline(self, start_date=None, end_date=None, module_types=None, page=1, page_size=50):
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        end_date = end_date or today.isoformat()
        start_date = start_date or today.replace(day=1).isoformat()
        result = collect_records(module_types, start_date=start_date, end_date=end_date, page=page, page_size=page_size)
        warnings = result['warnings']
        return {'records': result['records'], 'total_count': result['total_count'],
                'start_date': start_date, 'end_date': end_date, 'page': page, 'page_size': page_size,
                'partial': bool(warnings), 'warnings': warnings}

    def get_timeline_stats(self, start_date=None, end_date=None, module_types=None):
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        start_date = start_date or today.replace(day=1).isoformat()
        end_date = end_date or today.isoformat()
        result = collect_records(module_types, start_date=start_date, end_date=end_date, stats_only=True)
        warnings = result['warnings']
        stats = {module: {'label': config['label'], 'count': result['counts'][module]}
                 for module, config in TIMELINE_MODULES.items()}
        return {**stats, 'by_module': stats, 'total_records': result['total_count'],
                'active_days': result['active_days'],
                'partial': bool(warnings), 'warnings': warnings}
