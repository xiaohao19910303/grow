"""AI 行为分析报告 — 数据收集与 AI 分析。"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path


def collect_data_summary(db_path: Path, period_days: int = 30) -> dict:
    """收集近 N 天的数据摘要。"""
    today = date.today()
    start = today - timedelta(days=period_days - 1)
    start_str = start.isoformat()
    end_str = today.isoformat()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 打卡数据
    total_days = conn.execute(
        "SELECT COUNT(DISTINCT date) FROM checkins WHERE date >= ? AND date <= ?",
        (start_str, end_str),
    ).fetchone()[0]

    module_stats = {}
    for r in conn.execute(
        "SELECT module_id, COUNT(DISTINCT date) as days FROM checkins "
        "WHERE date >= ? AND date <= ? GROUP BY module_id",
        (start_str, end_str),
    ):
        module_stats[r["module_id"]] = r["days"]

    completion_rate = round(total_days / period_days, 2) if period_days > 0 else 0

    # 习惯数据
    habit_data = conn.execute(
        "SELECT SUM(minutes) as total, AVG(minutes) as avg FROM habits "
        "WHERE date >= ? AND date <= ?",
        (start_str, end_str),
    ).fetchone()
    total_minutes = habit_data["total"] or 0
    avg_minutes = round(habit_data["avg"] or 0)

    # 行为应用数据
    behavior_total = conn.execute(
        "SELECT COUNT(*) FROM behavior_applications WHERE date >= ? AND date <= ?",
        (start_str, end_str),
    ).fetchone()[0]

    behavior_concepts = []
    for r in conn.execute(
        "SELECT concept, COUNT(*) as cnt FROM behavior_applications "
        "WHERE date >= ? AND date <= ? GROUP BY concept ORDER BY cnt DESC LIMIT 5",
        (start_str, end_str),
    ):
        behavior_concepts.append(f"{r['concept']}({r['cnt']}次)")

    # 错误数据
    error_total = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE date >= ? AND date <= ?",
        (start_str, end_str),
    ).fetchone()[0]

    error_types = []
    for r in conn.execute(
        "SELECT error_type, COUNT(*) as cnt FROM error_records "
        "WHERE date >= ? AND date <= ? GROUP BY error_type ORDER BY cnt DESC LIMIT 5",
        (start_str, end_str),
    ):
        error_types.append(f"{r['error_type']}({r['cnt']}次)")

    error_repeat = conn.execute(
        "SELECT COUNT(*) FROM error_records WHERE date >= ? AND date <= ? AND is_repeat = 1",
        (start_str, end_str),
    ).fetchone()[0]
    error_repeat_rate = round(error_repeat / error_total, 2) if error_total > 0 else 0

    # 预测数据
    pred_total = conn.execute(
        "SELECT COUNT(*) FROM predictions WHERE date >= ? AND date <= ?",
        (start_str, end_str),
    ).fetchone()[0]

    pred_resolved = conn.execute(
        "SELECT COUNT(*) FROM predictions WHERE date >= ? AND date <= ? AND result != 'pending'",
        (start_str, end_str),
    ).fetchone()[0]

    pred_correct = conn.execute(
        "SELECT COUNT(*) FROM predictions WHERE date >= ? AND date <= ? AND result = 'correct'",
        (start_str, end_str),
    ).fetchone()[0]

    pred_accuracy = round(pred_correct / pred_resolved, 2) if pred_resolved > 0 else 0

    # 复盘数据
    review_total = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE date >= ? AND date <= ?",
        (start_str, end_str),
    ).fetchone()[0]

    conn.close()

    return {
        "period": f"近{period_days}天（{start_str} ~ {end_str}）",
        "checkins": {
            "total_days": total_days,
            "module_stats": module_stats,
            "completion_rate": completion_rate,
        },
        "habits": {
            "total_minutes": total_minutes,
            "avg_minutes_per_day": avg_minutes,
        },
        "behavior_applications": {
            "total": behavior_total,
            "top_concepts": behavior_concepts,
        },
        "errors": {
            "total": error_total,
            "top_types": error_types,
            "repeat_rate": error_repeat_rate,
        },
        "predictions": {
            "total": pred_total,
            "resolved": pred_resolved,
            "accuracy": pred_accuracy,
        },
        "reviews": {
            "total": review_total,
        },
    }


def build_prompt(data_summary: dict) -> str:
    """构建 AI prompt。"""
    data_json = json.dumps(data_summary, ensure_ascii=False, indent=2)

    return f"""你是一个个人成长教练。根据以下用户行为数据，生成一份简洁的分析报告。

**数据摘要**：
{data_json}

**要求**：
1. **行为模式总结**（2-3句）：哪些习惯在坚持，哪些在下滑？
2. **知识应用分析**（2-3句）：学到的概念应用得怎么样？有什么模式？
3. **错误模式分析**（2-3句）：哪些错误在重复？哪些在改善？
4. **预测校准**（1-2句）：预测准确度如何？是否过度自信或保守？
5. **个性化建议**（3-5条）：基于数据，给出具体可操作的改进建议。

**格式**：
- 使用 Markdown 格式
- 每个部分用 `##` 标题
- 建议用有序列表
- 总字数控制在 500-800 字
- 语气：鼓励但直接，指出问题但不批评"""


async def generate_report_content(db_path: Path, period_days: int = 30) -> tuple[str, str]:
    """生成报告内容。返回 (content, data_summary_json)。"""
    data_summary = collect_data_summary(db_path, period_days)
    data_summary_json = json.dumps(data_summary, ensure_ascii=False)
    prompt = build_prompt(data_summary)

    # 调用 AI
    try:
        from copilot.core import call_ai
        content = await call_ai(prompt)
    except Exception as e:
        content = f"# AI 分析失败\n\n无法生成报告：{e}\n\n请稍后重试。"

    return content, data_summary_json
