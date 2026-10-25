"""知行成长 · 云端服务端（FastAPI + PostgreSQL）

- 多用户应用，按账号隔离 PostgreSQL schema，采用带快照修订的 state 同步：前端 GET /api/data 读取状态与修订，
  PUT /api/data 在同一事务内校验修订并保存，保留既有记录ID。
- 规范化表结构便于后续做 SQL 查询 / 周月报 / 知识图谱。
- v3：扫描工作区 Markdown 生成知识图谱（knowledge 表）+ 周报/月报汇总。
- 数据库使用 Supabase PostgreSQL，支持多设备同步。
- 支持云端部署（Render.com）。
"""
import json
import os
import re
import db
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from threading import RLock
from tenancy import learning_root, shutdown_all

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from copilot.api import register as register_copilot
from copilot.core import Problem
from plans.api import register as register_plans
from reading.api import register as register_reading
from behavior.api import register as register_behavior
from errors.api import register as register_errors
from predictions.api import register as register_predictions
from behavior_report.api import register as register_behavior_report
from knowledge.api import register as register_knowledge
from reflections.api import register as register_reflections
from stocks.api import register as register_stocks
from study_materials import register as register_materials, initialize as initialize_materials
from search_api import register as register_search
from timeline_api import register as register_timeline
import asyncio
from legacy_state import load_state as read_legacy_state, save_state as write_legacy_state

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
# 运行时目录 — 用于锁文件、快照等（不再需要 SQLite 文件）
DB_PATH = Path(os.environ.get('RUNTIME_ROOT', BASE_DIR / 'runtime'))
DB_PATH.mkdir(parents=True, exist_ok=True)
LEGACY_JSON = BASE_DIR.parent / "v1-legacy" / "data.json"  # v1 归档数据（迁移源）
# 学习资料根目录 — 云端部署时使用项目内的学习资料文件夹
LEARN_ROOT = Path(os.environ.get('LEARN_ROOT', BASE_DIR.parent / '学习资料'))

DEFAULT_MODULES = [
    {"id": "fupan", "name": "执行复盘", "color": "#4F6EF7", "order": 1},
    {"id": "zhenghe", "name": "整合练习", "color": "#7C5CF0", "order": 2},
    {"id": "renzhi", "name": "每日认知与通识学习", "color": "#00A6A6", "order": 3},
    {"id": "xiezuo", "name": "深度写作", "color": "#E07B39", "order": 4},
    {"id": "biaoda", "name": "结构化表达", "color": "#D64580", "order": 5},
    {"id": "yingyu", "name": "英文阅读", "color": "#2FA84F", "order": 6},
    {"id": "siwei", "name": "现代思维工具", "color": "#6B7280", "order": 7},
    {"id": "gaorenzhi", "name": "高认知能力训练", "color": "#C0362C", "order": 8},
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY, date TEXT NOT NULL, title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS modules (
    id TEXT PRIMARY KEY, name TEXT, color TEXT, ord INTEGER
);
CREATE TABLE IF NOT EXISTS checkins (
    date TEXT, module_id TEXT, level INTEGER,
    PRIMARY KEY (date, module_id)
);
CREATE TABLE IF NOT EXISTS habits (
    date TEXT PRIMARY KEY, minutes INTEGER DEFAULT 0, note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS custom_fields (
    key TEXT PRIMARY KEY, label TEXT, type TEXT
);
CREATE TABLE IF NOT EXISTS custom_records (
    id SERIAL PRIMARY KEY, data TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    id SERIAL PRIMARY KEY,
    date TEXT, title TEXT, context TEXT, options TEXT, reason TEXT,
    expected TEXT, probability INTEGER, emotion TEXT, actual TEXT, bias TEXT
);
CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    date TEXT, statement TEXT, probability INTEGER, result TEXT, deviation TEXT
);
CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    date TEXT, thought TEXT, actual TEXT, gap TEXT, action TEXT
);
CREATE TABLE IF NOT EXISTS insights (
    id SERIAL PRIMARY KEY,
    date TEXT, insight TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS knowledge (
    id SERIAL PRIMARY KEY,
    name TEXT, category TEXT, summary TEXT, source TEXT, kind TEXT,
    date TEXT DEFAULT ''
);
"""

# 业务 state 同步涉及的表（knowledge 为扫描产物，不在其中）
TABLES = ["modules", "checkins", "habits", "custom_fields", "custom_records",
          "decisions", "predictions", "reviews", "insights"]


def get_conn():
    return db.connect()


def init_db():
    from rhythm.schema import initialize as initialize_rhythm
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        initialize_rhythm(conn)
    from legacy_schema import migrate
    migrate()
    initialize_materials()


def save_state(state: dict, *, require_revision=False):
    # Only bootstrap/internal callers may omit a revision. HTTP writes are strict.
    return write_legacy_state(get_conn, state, require_revision=require_revision)


def load_state() -> dict:
    return read_legacy_state(get_conn)


def migrate_if_empty():
    """首次启动：db 为空则导入 v1 data.json，否则用默认模块。"""
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
    conn.close()
    if n > 0:
        return
    if os.getenv('PLAN_CONTENT_BACKEND') == 'github':
        # Bootstrap the cloud pilot without the legacy SQLite full-state writer.
        # Existing cloud records are never replaced or imported from local files.
        with get_conn() as conn:
            for m in DEFAULT_MODULES:
                conn.execute('INSERT INTO modules VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING',
                             (m['id'],m['name'],m['color'],m['order']))
        return
    if LEGACY_JSON.exists():
        try:
            save_state(json.loads(LEGACY_JSON.read_text(encoding="utf-8")))
            return
        except Exception:
            pass
    save_state({"modules": DEFAULT_MODULES,
                "customFields": [{"key": "title", "label": "标题", "type": "text"},
                                 {"key": "category", "label": "分类", "type": "text"},
                                 {"key": "value", "label": "数值", "type": "number"},
                                 {"key": "date", "label": "日期", "type": "date"}]})


PENDING_SYNC_FILE = BASE_DIR / "pending_sync.json"


def import_pending_sync():
    """启动时导入 pending_sync.json（每日复盘同步脚本生成的）。
    导入成功后删除该文件，避免重复导入。
    """
    if not PENDING_SYNC_FILE.exists():
        return 0
    try:
        data = json.loads(PENDING_SYNC_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️  pending_sync.json 解析失败：{e}")
        return 0

    conn = get_conn()
    cur = conn.cursor()
    count = 0

    # 导入 reviews
    for r in data.get("reviews", []):
        cur.execute(
            "INSERT INTO reviews(date, thought, actual, gap, action) VALUES(?,?,?,?,?)",
            (r["date"], r.get("thought", ""), r.get("actual", ""),
             r.get("gap", ""), r.get("action", ""))
        )
        count += 1

    # 导入 decisions
    for d in data.get("decisions", []):
        # 检查是否已存在（同一天同标题）
        existing = cur.execute(
            "SELECT id FROM decisions WHERE date=? AND title=?",
            (d["date"], d["title"])
        ).fetchone()
        if not existing:
            cur.execute(
                "INSERT INTO decisions(date,title,context,options,reason,expected,probability,emotion,actual,bias) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (d["date"], d["title"], d.get("context", ""), d.get("options", ""),
                 d.get("reason", ""), d.get("expected", ""), d.get("probability"),
                 d.get("emotion", ""), d.get("actual", ""), d.get("bias", ""))
            )
            count += 1

    # 导入 insights
    for i in data.get("insights", []):
        existing = cur.execute(
            "SELECT id FROM insights WHERE date=? AND insight=?",
            (i["date"], i["insight"])
        ).fetchone()
        if not existing:
            cur.execute(
                "INSERT INTO insights(date, insight, source) VALUES(?,?,?)",
                (i["date"], i["insight"], i.get("source", ""))
            )
            count += 1

    # 导入 knowledge（新知识节点）
    for k in data.get("knowledge", []):
        existing = cur.execute(
            "SELECT id FROM knowledge WHERE name=? AND date=?",
            (k["name"], k.get("date", ""))
        ).fetchone()
        if not existing:
            cur.execute(
                "INSERT INTO knowledge(name,category,summary,source,kind,date) VALUES(?,?,?,?,?,?)",
                (k["name"], k.get("category", ""), k.get("summary", ""),
                 k.get("source", ""), k.get("kind", "concept"), k.get("date", ""))
            )
            count += 1

    # 导入 checkins
    for c in data.get("checkins", []):
        cur.execute(
            "INSERT INTO checkins(date, module_id, level) VALUES(?,?,?) ON CONFLICT(date,module_id) DO UPDATE SET level=excluded.level",
            (c["date"], c["module_id"], c["level"])
        )
        count += 1

    conn.commit()
    conn.close()

    # 导入成功后删除文件
    try:
        PENDING_SYNC_FILE.unlink()
    except Exception:
        pass

    print(f"✅ 从 pending_sync.json 导入了 {count} 条记录")
    return count


# ================= v3：知识图谱扫描 =================

HEADER_KEYS = {"概念", "工具", "框架", "方法", "词汇", "词汇/词组", "句式", "日期", "名称",
               "一句话解释", "详细学习位置", "中文意思", "原句例子", "适用场景", "来源事件", "可用场景"}


def parse_index(path: Path):
    """解析 知识索引.md 的表格 → 概念/工具/框架节点。"""
    nodes = []
    text = path.read_text(encoding="utf-8")
    cat = "未分类"
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            c = s[3:].strip()
            c = re.sub(r"^[一二三四五六七八九十]+[、.．]\s*", "", c)
            cat = c if c else cat
        elif s.startswith("|"):
            cells = [c.strip() for c in s.strip().strip("|").split("|")]
            cells = [c for c in cells if c != ""]
            if not cells:
                continue
            # 分隔行 |---|---|
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            name = cells[0]
            if name in HEADER_KEYS:
                continue
            summary = cells[1] if len(cells) > 1 else ""
            source = ""
            for c in cells[2:]:
                if ".md" in c or "/" in c:
                    source = c
            if not source and len(cells) > 2:
                source = cells[-1]
            nodes.append({"name": name, "category": cat, "summary": summary,
                          "source": source, "kind": "concept", "date": ""})
    return nodes


def parse_thinking_tools(directory: Path):
    """解析 现代思维工具教程 的『第N课：工具名』标题。"""
    nodes = []
    for f in sorted(directory.glob("*.md")):
        stage_name = f.stem
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^##\s*第[一二三四五六七八九十百零]+课[：:]\s*(.+)$", line.strip())
            if m:
                name = re.sub(r"[（(].*?[）)]\s*$", "", m.group(1).strip()).strip()
                nodes.append({"name": name, "category": "思维工具", "summary": stage_name,
                              "source": str(f.relative_to(learning_root(LEARN_ROOT))), "kind": "tool", "date": ""})
    return nodes


def parse_footprints():
    """解析课程/文章/练习文件名 → 学习足迹节点。"""
    nodes = []
    patterns = [
        (learning_root(LEARN_ROOT) / "每日认知与通识学习" / "每日课程", "认知课程"),
        (learning_root(LEARN_ROOT) / "英文阅读" / "每日文章", "英文阅读"),
        (learning_root(LEARN_ROOT) / "结构化表达" / "每日练习", "结构化表达"),
    ]
    for d, cat in patterns:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            name = f.stem
            mdate = re.search(r"\d{4}-\d{2}-\d{2}", name)
            date_s = mdate.group(0) if mdate else ""
            title = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name)
            title = re.sub(r"^第0*[0-9]+课-", "", title)
            title = re.sub(r"^Day\s*0*[0-9]+\s*-\s*", "", title).strip()
            if not title:
                title = name
            nodes.append({"name": title, "category": cat, "summary": "",
                          "source": str(f.relative_to(learning_root(LEARN_ROOT))), "kind": "footprint", "date": date_s})
    return nodes


def scan_markdown():
    nodes = []
    idx = learning_root(LEARN_ROOT) / "知识索引.md"
    if idx.exists():
        nodes += parse_index(idx)
    tt = learning_root(LEARN_ROOT) / "现代思维工具教程"
    if tt.exists():
        nodes += parse_thinking_tools(tt)
    nodes += parse_footprints()
    return nodes


def refresh_knowledge():
    nodes = scan_markdown()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':knowledge-write',0))")
    # Keep existing identities and imported nodes: knowledge links refer to these IDs.
    for n in nodes:
        existing = cur.execute("SELECT id FROM knowledge WHERE name=? AND COALESCE(source,'')=? AND COALESCE(kind,'')=?",
                               (n['name'], n.get('source',''), n.get('kind',''))).fetchone()
        if existing:
            continue
        cur.execute("INSERT INTO knowledge(name,category,summary,source,kind,date) VALUES(?,?,?,?,?,?)",
                    (n["name"], n["category"], n["summary"], n["source"], n["kind"], n.get("date", "")))
    conn.commit()
    conn.close()
    return len(nodes)


def load_knowledge():
    conn = get_conn()
    nodes = [dict(r) for r in conn.execute("SELECT * FROM knowledge ORDER BY category, id")]
    conn.close()
    cats = {}
    for n in nodes:
        cats[n["category"]] = cats.get(n["category"], 0) + 1
    return {"nodes": nodes, "categories": cats, "total": len(nodes)}


# ================= v3：周报/月报 =================

def _ds(d: date) -> str:
    return d.isoformat()


def current_streak():
    from growth_statistics import collect_activity
    with get_conn() as conn:
        return collect_activity(conn)['streak']


def build_report(days: int):
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not getattr(plans_store,'remote',False) and (plans_store.runtime / 'restore-pending.json').exists():
        raise RuntimeError('存在未完成的学习计划恢复，请先核对恢复日志。')
    accounts.initialize()
    init_db()
    from legacy_migrations import migrate as migrate_legacy_tables
    try:
        with get_conn() as connection:
            migrated = migrate_legacy_tables(connection)
        if migrated: print('旧表结构迁移完成：'+', '.join(migrated))
    except (Problem, db.psycopg2.Error):
        # Original records remain intact; unaffected modules and AI settings stay available.
        print('部分旧表需要人工核对迁移，原数据已保留。')
    from copilot.ai_config import remove_server_config
    with get_conn() as connection:
        remove_server_config(connection)
    migrate_if_empty()
    # 导入 pending_sync.json（每日复盘同步脚本生成的）
    import_pending_sync()
    try:
        copilot_store.initialize()
        copilot_store.startup_error = None
    except (Problem, OSError, db.psycopg2.Error) as exc:
        copilot_store.startup_error = exc if isinstance(exc,Problem) else Problem('legacy_storage','旧认知模块存储暂不可用；新学习计划可独立使用。',503)
        # Do not reset missing workspaces or fail unrelated dashboard features.
        print('学习副驾驶暂不可用，请检查旧模块存储配置。')
    try:
        plans_store.initialize()
        plans_store.startup_error = None
    except (Problem, OSError, db.psycopg2.Error) as exc:
        plans_store.startup_error = exc
        print('学习计划暂不可用，请检查内容存储、数据库配置或恢复记录。')
    try:
        reading_store.initialize()
        reading_store.startup_error = None
        reading_service.scheduler = asyncio.create_task(reading_service.schedule())
    except (Problem, OSError, db.psycopg2.Error) as exc:
        reading_store.startup_error = exc
        print('认知阅读暂不可用，请检查磁盘或恢复日志。')
    try:
        reflections_store.initialize()
        reflections_store.startup_error = None
    except (Problem, OSError, db.psycopg2.Error) as exc:
        reflections_store.startup_error = exc
        print('日常记录暂不可用，请检查磁盘或恢复日志。')
    try:
        stocks_store.initialize()
        stocks_store.startup_error = None
    except (Problem, OSError, db.psycopg2.Error) as exc:
        stocks_store.startup_error = exc
        print('股票复盘暂不可用，请检查磁盘或恢复日志。')
    try:
        behavior_store.initialize()
        behavior_store.startup_error = None
    except Exception as exc:
        behavior_store.startup_error = exc
        print(f'行为应用追踪暂不可用：{exc}')
    try:
        error_store.initialize()
        error_store.startup_error = None
    except Exception as exc:
        error_store.startup_error = exc
        print(f'重复错误追踪暂不可用：{exc}')
    try:
        behavior_report_store.initialize()
        behavior_report_store.startup_error = None
    except Exception as exc:
        behavior_report_store.startup_error = exc
        print(f'AI 行为分析报告暂不可用：{exc}')
    try:
        knowledge_graph_store.initialize()
        knowledge_graph_store.startup_error = None
    except Exception as exc:
        knowledge_graph_store.startup_error = exc
        print(f'知识图谱可视化暂不可用：{exc}')
    # 首次启动自动扫描一次知识图谱（若为空）
    conn = get_conn()
    empty = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 0
    conn.close()
    if empty:
        refresh_knowledge()
    from action_source_worker import run as run_source_delivery
    source_delivery_task = asyncio.create_task(run_source_delivery(accounts))
    try:
        yield
    finally:
        source_delivery_task.cancel()
        await asyncio.gather(source_delivery_task, return_exceptions=True)
        await shutdown_all()


app = FastAPI(title="知行成长", lifespan=lifespan)
app.state.multiuser = True

from coach_facts import register as register_coach_facts
register_coach_facts(app)

@app.middleware('http')
async def legacy_module_readiness(request: Request, call_next):
    for prefix, store in (('/api/behavior', behavior_store), ('/api/errors', error_store),
                          ('/api/behavior-report', behavior_report_store)):
        if (request.url.path == prefix or request.url.path.startswith(prefix+'/')) and store.startup_error:
            return JSONResponse({'error':'legacy_schema_migration',
                                 'message':'该旧模块的数据表尚未完成迁移，原数据保留，请先核对表结构。'},status_code=503)
    return await call_next(request)


copilot_store = register_copilot(app, LEARN_ROOT, DB_PATH)
plans_store, plans_generator = register_plans(app, LEARN_ROOT, DB_PATH)
reading_store, reading_service = register_reading(app, LEARN_ROOT, DB_PATH)
reflections_store, reflections_assistant = register_reflections(app, LEARN_ROOT, DB_PATH)
behavior_store = register_behavior(app, LEARN_ROOT, DB_PATH)
error_store = register_errors(app, LEARN_ROOT, DB_PATH)
prediction_stats = register_predictions(app, LEARN_ROOT, DB_PATH)
behavior_report_store = register_behavior_report(app, LEARN_ROOT, DB_PATH)
knowledge_graph_store = register_knowledge(app, LEARN_ROOT, DB_PATH)
stocks_store = register_stocks(app, LEARN_ROOT, DB_PATH)
from migration_api import register as register_migrations
register_migrations(app, copilot_store, LEARN_ROOT)
materials = register_materials(app, LEARN_ROOT)
from study_notes import register as register_study_notes
register_study_notes(app)
from action_plans import register as register_action_plans
register_action_plans(app)
search_service = register_search(app, DB_PATH)
timeline_service = register_timeline(app, DB_PATH)


@app.get('/api/storage-status')
def storage_status():
    return {'records': 'postgresql', 'formal_markdown': os.getenv('PLAN_CONTENT_BACKEND', 'local'),
            'ai_config': 'browser', 'requires_own_ai_config': True,
            'modules': {name: {'ready': not getattr(store, 'startup_error', None),
                               'reason': (getattr(store.startup_error, 'code', 'legacy_schema_or_storage') if getattr(store, 'startup_error', None) else None)}
                        for name, store in (('plans', plans_store), ('copilot', copilot_store),
                                            ('reading', reading_store), ('reflections', reflections_store),
                                            ('stocks', stocks_store), ('behavior', behavior_store),
                                            ('errors', error_store), ('behavior_report', behavior_report_store),
                                            ('knowledge', knowledge_graph_store))}}


@app.get("/api/health")
def health():
    return {"ok": True,
            "revision": os.getenv('RENDER_GIT_COMMIT', 'local'),
            "plan_storage": 'github' if getattr(plans_store, 'remote', False) else 'local',
            "learning_plans_ready": plans_store.startup_error is None}


@app.get("/api/data")
def get_data():
    return JSONResponse(load_state(), headers={'Cache-Control': 'no-store'})


@app.get('/api/learning-checkins')
def get_learning_checkins():
    from learning_checkins import read_checkins
    with db.connect() as conn:
        return JSONResponse(read_checkins(conn), headers={'Cache-Control': 'no-store'})


@app.put("/api/data")
async def put_data(request: Request):
    if request.headers.get('x-legacy-state-protocol') != '1':
        return JSONResponse({'code': 'client_outdated',
                             'message': '页面保存协议过旧，请先导出本地修改，再刷新页面。'}, status_code=409)
    try:
        data = await request.json()
        return save_state(data, require_revision=True)
    except Problem as exc:
        return JSONResponse({'code': exc.code, 'message': exc.message}, status_code=exc.status)
    except (ValueError, db.IntegrityError):
        return JSONResponse({'code': 'invalid', 'message': '记录格式或编号无效，未保存。'}, status_code=422)


@app.get("/api/knowledge")
def get_knowledge():
    return load_knowledge()


@app.post("/api/knowledge/scan")
def rescan_knowledge():
    n = refresh_knowledge()
    return {"ok": True, "count": n}


@app.get("/api/report")
def get_report(range: str = "week"):
    days = 7 if range == "week" else 30 if range == "month" else 7
    return build_report(days)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


_prepared_users = set()
_prepare_lock = RLock()


def prepare_user(user):
    with _prepare_lock:
        if user['id'] not in _prepared_users and not user['is_owner']:
            init_db()
            # New accounts start empty and never import the owner's files or snapshots.
            with get_conn() as conn:
                for module in DEFAULT_MODULES:
                    conn.execute('INSERT INTO modules VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING',
                                 (module['id'], module['name'], module['color'], module['order']))
            if os.getenv('PLAN_CONTENT_BACKEND', 'local') != 'github':
                learning_root(LEARN_ROOT).mkdir(parents=True, exist_ok=True)
        _prepared_users.add(user['id'])
    # Initialize in the request's worker thread, before synchronous module
    # middleware accesses these proxies on the event loop.
    for module in (plans_store, copilot_store, reading_store, reflections_store,
                   behavior_store, error_store, behavior_report_store,
                   knowledge_graph_store, stocks_store):
        module.resolve()


from accounts import install as install_accounts
accounts = install_accounts(app, STATIC_DIR, prepare_user)

# Install last so authentication and module initialization share the same limit.
from request_limit import RequestConcurrencyLimit
app.add_middleware(RequestConcurrencyLimit)
