"""Read-only coach facts. No model, jobs, notification claims or schema writes."""
from datetime import date, timedelta
import json

import db
import growth_statistics as growth
from fastapi import APIRouter, HTTPException, Response
from tenancy import current_user

COURSE_GAP_DAYS = 14
PREDICTION_MINIMUM = 5


def fact(kind, message, basis, source, start, end, **evidence):
    return dict(kind=kind, message=message, basis=basis, source=source,
                start=str(start), end=str(end), evidence=evidence)


def course_gap(conn, tables, today):
    """A completion-confirmation date is evidence, not proof of absent reviews."""
    candidates = []
    if 'study_learning_records' in tables:
        for row in conn.execute('SELECT module_id,filename,topic,completed_at FROM study_learning_records'):
            candidates.append((('study', row['module_id'], row['filename']), row['topic'], row['completed_at'], '英文／表达学完确认'))
    if 'copilot_learning_records' in tables:
        columns = {r[0] for r in conn.execute("""SELECT column_name FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name='copilot_learning_records'""")}
        archived = ' AND COALESCE(archived,0)=0' if 'archived' in columns else ''
        for row in conn.execute("SELECT module_id,round_id,lesson_no,completed_at FROM copilot_learning_records WHERE module_id='renzhi'" + archived):
            candidates.append((('renzhi', row['round_id'], row['lesson_no']),
                               f'认知课程第{row["lesson_no"]}课（第{row["round_id"]}轮）', row['completed_at'], '认知课程学完确认'))
    if {'learning_plans', 'learning_lessons', 'learning_feedback'} <= tables:
        rows = conn.execute("""SELECT f.plan_id,f.lesson_no,f.data AS feedback,l.data AS lesson,p.data AS plan
            FROM learning_feedback f JOIN learning_lessons l ON l.plan_id=f.plan_id AND l.lesson_no=f.lesson_no
            JOIN learning_plans p ON p.id=f.plan_id""")
        for row in rows:
            feedback, lesson, plan = (json.loads(row[k]) for k in ('feedback', 'lesson', 'plan'))
            if feedback.get('state') == 'completed' and plan.get('status', 'active') == 'active':
                candidates.append((('plan', row['plan_id'], row['lesson_no']),
                                   lesson.get('topic') or f'计划第{row["lesson_no"]}课', feedback.get('date'), '学习计划课程反馈'))
    latest = {}
    for identity, title, stamp, source in candidates:
        day = growth._local_day(stamp)
        if not day or day > str(today):
            continue
        if identity not in latest or day > latest[identity][1]:
            latest[identity] = (title, day, source)
    eligible = [(title, day, source) for title, day, source in latest.values()
                if (today - date.fromisoformat(day)).days >= COURSE_GAP_DAYS]
    if not eligible:
        return None
    title, day, source = min(eligible, key=lambda item: (item[1], item[0]))
    gap = (today - date.fromisoformat(day)).days
    return fact('course_gap', f'“{title}”最近的学完确认记录在 {day}，距今 {gap} 天，可以按需回看。',
                '阈值为14天；学完确认记录不能证明你此后没有复习，也不代表遗忘程度。',
                source, day, today, gap_days=gap, threshold_days=COURSE_GAP_DAYS, title=title)


def project(conn, today):
    start = today - timedelta(days=6)
    activity = growth.collect_activity(conn, str(start), str(today), today=today)
    days = [today - timedelta(days=i) for i in (3, 2, 1)]
    counts = [len(activity['checkins'].get(str(day), {})) for day in days]
    if counts[0] > counts[1] > counts[2] > 0:
        return fact('record_decrease', f'前三个完整日的学习分类记录依次为 {counts[0]}、{counts[1]}、{counts[2]} 项。',
                    '同一分类每日只计一次，包含进展与学完记录；数量变化不代表实际学习投入或能力下滑。今天尚未结束，不参与比较。',
                    '学习完成足迹与手工分类记录', days[0], days[-1], dates=list(map(str, days)), counts=counts, threshold_days=3)
    tables = {row[0] for row in conn.execute('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
    old_course = course_gap(conn, tables, today)
    if old_course:
        return old_course
    week = today - timedelta(days=today.weekday())
    resolved = []
    if 'predictions' in tables:
        for row in conn.execute("SELECT date,result,probability FROM predictions WHERE result IN ('correct','incorrect')"):
            day = growth._local_day(row['date'])
            probability = row['probability']
            if day and str(week) <= day <= str(today) and probability is not None and 0 <= probability <= 100:
                resolved.append(row['result'])
    if len(resolved) >= PREDICTION_MINIMUM:
        correct = resolved.count('correct')
        accuracy = round(correct * 100 / len(resolved))
        return fact('predictions', f'本周录入且已核对的 {len(resolved)} 条有效预测中，{correct} 条正确，准确率 {accuracy}%。',
                    '至少5条已核对样本才展示；待核对、未知结果及无效概率不计入。准确率不是概率校准或长期判断能力的结论。',
                    '预测记录', week, today, resolved=len(resolved), correct=correct, accuracy_percent=accuracy, minimum_sample=PREDICTION_MINIMUM)
    if activity['streak'] >= 2:
        active_today = str(today) in activity['checkins'] or any(
            growth._local_day(r['date']) == str(today) and ((r['minutes'] or 0) > 0 or (r['note'] or '').strip())
            for r in conn.execute('SELECT date,minutes,note FROM habits'))
        end = today if active_today else today - timedelta(days=1)
        return fact('streak', f'截至 {end}，学习分类或习惯补记已连续有记录 {activity["streak"]} 天。',
                    '学习分类与习惯补记按日期合并；连续记录不是学习能力评价，也不是必须维持的打卡要求。',
                    '学习足迹、手工分类与习惯补记', end - timedelta(days=activity['streak'] - 1), end, streak=activity['streak'])
    count = activity['active_days']
    return fact('activity' if count else 'empty',
                f'最近7天有 {count} 天学习分类或习惯补记记录。' if count else '最近7天暂无学习分类或习惯补记记录，可按需选择下一步。',
                '同一天多来源只计一天，不合计可能重叠的时长；未记录不代表没有学习。',
                '学习足迹、手工分类与习惯补记', start, today, active_days=count, window_days=7)


def snapshot():
    today = growth.shanghai_today()
    with db.connect() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        result = project(conn, today)
    user = current_user.get()
    return dict(date=str(today), timezone='Asia/Shanghai', uses_model=False,
                account_id=user['id'] if user else None, fact=result)


def register(app):
    router = APIRouter()

    @router.get('/api/coach-facts')
    def read(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        try:
            return snapshot()
        except (db.psycopg2.Error, db.Error, ValueError, KeyError, TypeError):
            raise HTTPException(503, '教练事实暂未读取，请稍后重试。', headers={'Cache-Control':'no-store'}) from None

    app.include_router(router)
