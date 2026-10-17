"""时间线聚合服务

跨模块时间线聚合，按日期排序：
- learning: 学习记录
- reflection: 反思日志
- decision: 决策记录
- prediction: 预测记录
- review: 复盘记录
- insight: 灵感记录
- knowledge: 知识图谱
"""
from datetime import date, datetime, timedelta
from typing import Optional

import db


# 时间线模块配置
TIMELINE_MODULES = {
    'learning': {
        'table': 'custom_records',
        'date_field': 'date',
        'label': '学习记录',
    },
    'reflection': {
        'table': 'custom_records',
        'date_field': 'date',
        'label': '反思日志',
    },
    'decision': {
        'table': 'decisions',
        'date_field': 'date',
        'label': '决策记录',
    },
    'prediction': {
        'table': 'predictions',
        'date_field': 'date',
        'label': '预测记录',
    },
    'review': {
        'table': 'reviews',
        'date_field': 'date',
        'label': '复盘记录',
    },
    'insight': {
        'table': 'insights',
        'date_field': 'date',
        'label': '灵感记录',
    },
    'knowledge': {
        'table': 'knowledge',
        'date_field': 'date',
        'label': '知识图谱',
    },
}


class TimelineService:
    """时间线聚合服务"""

    def __init__(self, db_path):
        self.db_path = db_path

    def get_timeline(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        module_types: Optional[list[str]] = None,
        page: int = 1,
        page_size: int = 50
    ) -> dict:
        """获取时间线数据

        Args:
            start_date: 开始日期 (YYYY-MM-DD)，默认为当月第一天
            end_date: 结束日期 (YYYY-MM-DD)，默认为今天
            module_types: 模块类型列表，None 表示包含所有模块
            page: 页码
            page_size: 每页数量

        Returns:
            时间线数据字典
        """
        # 默认日期范围：当月
        if not end_date:
            end_date = date.today().isoformat()
        if not start_date:
            start_date = date.today().replace(day=1).isoformat()

        # 确定要查询的模块
        modules_to_query = module_types or list(TIMELINE_MODULES.keys())

        all_records = []
        conn = db.connect()

        try:
            for module_type in modules_to_query:
                if module_type not in TIMELINE_MODULES:
                    continue

                config = TIMELINE_MODULES[module_type]
                records = self._get_records_from_module(
                    conn, module_type, config, start_date, end_date
                )
                all_records.extend(records)

            # 按日期排序（降序）
            all_records.sort(key=lambda x: x.get('date', ''), reverse=True)

            # 分页
            total_count = len(all_records)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_records = all_records[start_idx:end_idx]

            return {
                'records': paginated_records,
                'total_count': total_count,
                'start_date': start_date,
                'end_date': end_date,
                'page': page,
                'page_size': page_size,
            }
        finally:
            conn.close()

    def _get_records_from_module(
        self,
        conn,
        module_type: str,
        config: dict,
        start_date: str,
        end_date: str
    ) -> list[dict]:
        """从单个模块获取记录"""
        table = config['table']
        date_field = config.get('date_field')
        label = config['label']

        if not date_field:
            return []

        # 构建查询
        sql = f"""
            SELECT * FROM {table}
            WHERE {date_field} >= %s AND {date_field} <= %s
            ORDER BY {date_field} DESC
            LIMIT 200
        """

        try:
            rows = conn.execute(sql, (start_date, end_date)).fetchall()
        except Exception:
            return []

        # 转换为统一格式
        records = []
        for row in rows:
            row_dict = dict(row)
            title = self._extract_title(row_dict, module_type)
            summary = self._extract_summary(row_dict, module_type)

            records.append({
                'id': row_dict.get('id'),
                'module': module_type,
                'module_label': label,
                'title': title,
                'summary': summary,
                'date': row_dict.get(date_field, ''),
                'data': row_dict,
            })

        return records

    def _extract_title(self, row: dict, module_type: str) -> str:
        """从行数据中提取标题"""
        # 根据模块类型提取
        if module_type == 'knowledge':
            return row.get('name', '知识节点')
        elif module_type == 'decision':
            return row.get('title', '决策记录')
        elif module_type == 'prediction':
            return row.get('statement', '预测记录')
        elif module_type == 'review':
            return row.get('thought', '复盘记录')[:50]
        elif module_type == 'insight':
            return row.get('insight', '灵感记录')[:50]
        else:
            # 学习/反思记录
            if 'data' in row and isinstance(row['data'], str):
                try:
                    import json
                    data = json.loads(row['data'])
                    return data.get('title', data.get('name', f'{module_type}记录'))
                except Exception:
                    pass
            return f'{module_type}记录'

    def _extract_summary(self, row: dict, module_type: str) -> str:
        """从行数据中提取摘要"""
        if module_type == 'knowledge':
            summary = row.get('summary', '')
            if len(summary) > 100:
                summary = summary[:100] + '...'
            return summary
        elif module_type == 'decision':
            return row.get('reason', '')[:100]
        elif module_type == 'prediction':
            return f"概率: {row.get('probability', '')}%"
        elif module_type == 'review':
            return row.get('action', '')[:100]
        elif module_type == 'insight':
            return row.get('source', '')
        else:
            # 学习/反思记录
            if 'data' in row and isinstance(row['data'], str):
                try:
                    import json
                    data = json.loads(row['data'])
                    return data.get('note', data.get('summary', ''))[:100]
                except Exception:
                    pass
            return ''

    def get_timeline_stats(self) -> dict:
        """获取各模块的时间线统计信息"""
        conn = db.connect()
        try:
            stats = {}
            for module_type, config in TIMELINE_MODULES.items():
                table = config['table']
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except Exception:
                    count = 0

                stats[module_type] = {
                    'label': config['label'],
                    'count': count,
                }

            return stats
        finally:
            conn.close()
