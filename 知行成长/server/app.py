"""知行成长 · 云端服务端（FastAPI + PostgreSQL）

- 单用户应用，采用带快照修订的 state 同步：前端 GET /api/data 读取状态与修订，
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

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


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
            "INSERT OR REPLACE INTO reviews(date, thought, actual, gap, action) VALUES(?,?,?,?,?)",
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
            "INSERT OR REPLACE INTO checkins(date, module_id, level) VALUES(?,?,?)",
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
                              "source": str(f.relative_to(LEARN_ROOT)), "kind": "tool", "date": ""})
    return nodes


def parse_footprints():
    """解析课程/文章/练习文件名 → 学习足迹节点。"""
    nodes = []
    patterns = [
        (LEARN_ROOT / "每日认知与通识学习" / "每日课程", "认知课程"),
        (LEARN_ROOT / "英文阅读" / "每日文章", "英文阅读"),
        (LEARN_ROOT / "结构化表达" / "每日练习", "结构化表达"),
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
                          "source": str(f.relative_to(LEARN_ROOT)), "kind": "footprint", "date": date_s})
    return nodes


def scan_markdown():
    nodes = []
    idx = LEARN_ROOT / "知识索引.md"
    if idx.exists():
        nodes += parse_index(idx)
    tt = LEARN_ROOT / "现代思维工具教程"
    if tt.exists():
        nodes += parse_thinking_tools(tt)
    nodes += parse_footprints()
    return nodes


def refresh_knowledge():
    nodes = scan_markdown()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM knowledge")
    for n in nodes:
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
    conn = get_conn()
    dates = set()
    for r in conn.execute("SELECT DISTINCT date FROM checkins"):
        dates.add(r["date"])
    for r in conn.execute("SELECT date, minutes, note FROM habits"):
        if (r["minutes"] and r["minutes"] > 0) or (r["note"] and r["note"].strip()):
            dates.add(r["date"])
    conn.close()
    today = date.today()
    d = today
    if _ds(d) not in dates:
        d -= timedelta(days=1)
    streak = 0
    while _ds(d) in dates:
        streak += 1
        d -= timedelta(days=1)
    return streak


def build_report(days: int):
    start = date.today() - timedelta(days=days - 1)
    dates = [_ds(start + timedelta(i)) for i in range(days)]
    conn = get_conn()
    mods = [dict(r) for r in conn.execute("SELECT id,name,color,ord FROM modules ORDER BY ord")]
    active = set()
    total_minutes = 0
    for d in dates:
        if conn.execute("SELECT COUNT(*) FROM checkins WHERE date=?", (d,)).fetchone()[0] > 0:
            active.add(d)
        h = conn.execute("SELECT minutes,note FROM habits WHERE date=?", (d,)).fetchone()
        if h and ((h["minutes"] or 0) > 0 or (h["note"] and h["note"].strip())):
            active.add(d)
            total_minutes += h["minutes"] or 0
    comp = []
    for m in mods:
        done = conn.execute("SELECT COUNT(*) FROM checkins WHERE module_id=? AND date>=? AND date<=? AND level>0",
                            (m["id"], dates[0], dates[-1])).fetchone()[0]
        comp.append({"name": m["name"], "color": m["color"], "days": done,
                     "pct": round(done / days * 100)})
    def cnt(table):
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE date>=? AND date<=?",
                            (dates[0], dates[-1])).fetchone()[0]
    result = {
        "range": "week" if days == 7 else "month",
        "start": dates[0], "end": dates[-1], "days": days,
        "active_days": len(active),
        "total_minutes": total_minutes,
        "avg_minutes": round(total_minutes / days),
        "modules": comp,
        "decisions": cnt("decisions"),
        "predictions": cnt("predictions"),
        "reviews": cnt("reviews"),
        "insights": cnt("insights"),
        "knowledge_count": conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0],
        "streak": current_streak(),
    }
    conn.close()
    return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not getattr(plans_store,'remote',False) and (plans_store.runtime / 'restore-pending.json').exists():
        raise RuntimeError('存在未完成的学习计划恢复，请先核对恢复日志。')
    init_db()
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
    try:
        yield
    finally:
        await plans_generator.shutdown()
        await reading_service.shutdown()


app = FastAPI(title="知行成长", lifespan=lifespan)

# 添加 CORS 中间件（允许跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/data")
def get_data():
    return JSONResponse(load_state(), headers={'Cache-Control': 'no-store'})


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


# Only expose lesson folders, never arbitrary workspace files.
STUDY_MODULES = {
    "yingyu": ("英文阅读", "每日文章", "35 分钟"),
    "biaoda": ("结构化表达", "每日练习", "15 分钟"),
}


def study_files(module):
    if module not in STUDY_MODULES:
        raise HTTPException(404, "未找到学习模块")
    name, folder, _ = STUDY_MODULES[module]
    directory = (LEARN_ROOT / name / folder).resolve()
    return [p for p in sorted(directory.glob("*.md"))
            if p.is_file() and p.resolve().is_relative_to(directory)
            and p.resolve().is_relative_to(LEARN_ROOT.resolve())]


@app.get("/api/study-materials")
def study_materials():
    modules = []
    for module, (name, _, duration) in STUDY_MODULES.items():
        record = LEARN_ROOT / name / "学习记录.md"
        record_text = record.read_text(encoding="utf-8") if record.exists() else ""
        lessons = []
        for path in study_files(module):
            body = path.read_text(encoding="utf-8")
            title = re.search(r"^#\s+(.+)", body, re.M)
            day = re.search(r"Day\s*(\d+)", path.stem, re.I)
            stamp = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
            if not stamp:
                stamp = re.search(r"日期[：:]\s*(\d{4}-\d{2}-\d{2})", body.replace("**", ""))
            # English has an explicit completion column. Expression has no
            # lesson-level completion contract, so never infer it from a check-in.
            status = "待本人反馈"
            if module == "yingyu" and day:
                rows = []
                for line in record_text.splitlines():
                    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                    if len(cells) >= 3 and re.fullmatch(r"Day\s*0*" + str(int(day[1])), cells[1], re.I):
                        rows.append(cells)
                if len(rows) == 1:
                    status = rows[0][2] or status
            completed = status.startswith(("已完成", "已学习")) or status in ("完成", "✅", "[x]", "[X]")
            lessons.append({"filename": path.name, "topic": title[1] if title else path.stem,
                            "date": stamp[1] if stamp else "", "learning_label": status,
                            "learning_state": "completed" if completed else "unknown"})
        modules.append({"id": module, "name": name, "duration": duration, "lessons": lessons})
    return {"modules": modules}


@app.get("/api/study-materials/{module}/{filename}")
def study_material(module: str, filename: str):
    path = next((p for p in study_files(module) if p.name == filename), None)
    if path is None:
        raise HTTPException(404, "未找到课程")
    return {"content": path.read_text(encoding="utf-8")}


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
