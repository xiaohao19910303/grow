"""Read-only week/month report assembly using the shared growth statistics.

No application import: the caller supplies its account-scoped connection factory.
"""
from datetime import date, timedelta


def _ds(d: date) -> str:
    return d.isoformat()


def current_streak(get_conn):
    from growth_statistics import collect_activity
    with get_conn() as conn:
        return collect_activity(conn)['streak']


def build_report(days: int, get_conn):
    from growth_statistics import collect_activity, count_reflections, shanghai_today
    end = shanghai_today()
    start = end - timedelta(days=days - 1)
    dates = [_ds(start + timedelta(i)) for i in range(days)]
    with get_conn() as conn:
        facts = collect_activity(conn, dates[0], dates[-1], today=end)
        mods = [dict(r) for r in conn.execute("SELECT id,name,color,ord FROM modules ORDER BY ord")]
        known = {m['id'] for m in mods}
        mods.extend(m for m in facts['modules'] if m['id'] not in known)
        comp = []
        for m in mods:
            done = facts['module_stats'].get(m['id'], 0)
            comp.append({"name": m["name"], "color": m["color"], "days": done,
                         "pct": round(done / days * 100)})
        def cnt(table):
            return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE date>=? AND date<=?",
                                (dates[0], dates[-1])).fetchone()[0]
        return {
            "range": "week" if days == 7 else "month",
            "start": dates[0], "end": dates[-1], "days": days,
            "active_days": facts['active_days'],
            "total_minutes": facts['total_minutes'],
            "avg_minutes": round(facts['total_minutes'] / days),
            "duration_sources": facts['duration_sources'],
            "modules": comp,
            "decisions": cnt("decisions"),
            "predictions": cnt("predictions"),
            "reviews": count_reflections(conn, dates[0], dates[-1]),
            "insights": cnt("insights"),
            "knowledge_count": conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0],
            "streak": facts['streak'],
        }
