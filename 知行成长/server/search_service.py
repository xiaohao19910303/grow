"""跨模块统一搜索服务

提供跨多个模块的全文搜索能力：
- learning: 学习记录
- reflection: 反思日志
- decision: 决策记录
- prediction: 预测记录
- knowledge: 知识图谱
"""
from datetime import date, datetime
from typing import Optional

import db


# 可搜索的模块配置
SEARCHABLE_MODULES = {
    'learning': {
        'table': 'custom_records',
        'fields': ['data'],
        'date_field': 'date',
        'label': '学习记录',
    },
    'reflection': {
        'table': 'custom_records',
        'fields': ['data'],
        'date_field': 'date',
        'label': '反思日志',
    },
    'decision': {
        'table': 'decisions',
        'fields': ['title', 'context', 'options', 'reason', 'expected', 'actual'],
        'date_field': 'date',
        'label': '决策记录',
    },
    'prediction': {
        'table': 'predictions',
        'fields': ['statement', 'result', 'deviation'],
        'date_field': 'date',
        'label': '预测记录',
    },
    'knowledge': {
        'table': 'knowledge',
        'fields': ['name', 'category', 'summary', 'source'],
        'date_field': 'date',
        'label': '知识图谱',
    },
}


class SearchService:
    """统一搜索服务"""

    def __init__(self, db_path):
        self.db_path = db_path

    def search(
        self,
        query: str,
        module_types: Optional[list[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> dict:
        """执行跨模块搜索

        Args:
            query: 搜索关键词
            module_types: 模块类型列表，None 表示搜索所有模块
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            page: 页码
            page_size: 每页数量

        Returns:
            搜索结果字典
        """
        if not query or not query.strip():
            return {'results': [], 'total_count': 0, 'page': page, 'page_size': page_size}

        # 确定要搜索的模块
        modules_to_search = module_types or list(SEARCHABLE_MODULES.keys())

        all_results = []
        conn = db.connect()

        try:
            for module_type in modules_to_search:
                if module_type not in SEARCHABLE_MODULES:
                    continue

                config = SEARCHABLE_MODULES[module_type]
                results = self._search_in_module(
                    conn, module_type, config, query,
                    start_date, end_date
                )
                all_results.extend(results)

            # 按相关性/日期排序
            all_results.sort(key=lambda x: x.get('date', ''), reverse=True)

            # 分页
            total_count = len(all_results)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_results = all_results[start_idx:end_idx]

            return {
                'results': paginated_results,
                'total_count': total_count,
                'page': page,
                'page_size': page_size,
            }
        finally:
            conn.close()

    def _search_in_module(
        self,
        conn,
        module_type: str,
        config: dict,
        query: str,
        start_date: Optional[str],
        end_date: Optional[str]
    ) -> list[dict]:
        """在单个模块中搜索"""
        table = config['table']
        fields = config['fields']
        date_field = config.get('date_field')
        label = config['label']

        # 构建 WHERE 条件
        conditions = []
        params = []

        # 关键词搜索
        keyword_conditions = []
        for field in fields:
            keyword_conditions.append(f"{field} ILIKE %s")
            params.append(f"%{query}%")

        if keyword_conditions:
            conditions.append(f"({' OR '.join(keyword_conditions)})")

        # 日期范围筛选
        if start_date and date_field:
            conditions.append(f"{date_field} >= %s")
            params.append(start_date)
        if end_date and date_field:
            conditions.append(f"{date_field} <= %s")
            params.append(end_date)

        if not conditions:
            return []

        where_clause = ' AND '.join(conditions)

        # 执行查询
        sql = f"SELECT * FROM {table} WHERE {where_clause} ORDER BY {date_field} DESC LIMIT 100"

        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            return []

        # 转换为统一格式
        results = []
        for row in rows:
            row_dict = dict(row)

            # 提取标题和内容
            title = self._extract_title(row_dict, fields)
            content = self._extract_content(row_dict, fields)

            results.append({
                'id': row_dict.get('id'),
                'module': module_type,
                'module_label': label,
                'title': title,
                'content': content,
                'date': row_dict.get(date_field, ''),
                'data': row_dict,
            })

        return results

    def _extract_title(self, row: dict, fields: list[str]) -> str:
        """从行数据中提取标题"""
        # 优先使用 name, title 字段
        for field in ['name', 'title', 'statement']:
            if field in row and row[field]:
                return str(row[field])

        # 尝试从 JSON 数据中提取
        if 'data' in row and isinstance(row['data'], str):
            try:
                import json
                data = json.loads(row['data'])
                for key in ['title', 'name', 'headline']:
                    if key in data and data[key]:
                        return str(data[key])
            except Exception:
                pass

        return f"记录 {row.get('id', '')}"

    def _extract_content(self, row: dict, fields: list[str]) -> str:
        """从行数据中提取内容摘要"""
        parts = []
        for field in fields:
            if field in row and row[field]:
                value = str(row[field])
                if len(value) > 200:
                    value = value[:200] + '...'
                parts.append(value)

        return ' | '.join(parts) if parts else ''

    def get_search_stats(self) -> dict:
        """获取各模块的搜索统计信息"""
        conn = db.connect()
        try:
            stats = {}
            for module_type, config in SEARCHABLE_MODULES.items():
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
