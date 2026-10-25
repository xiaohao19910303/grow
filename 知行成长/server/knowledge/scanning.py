"""Parse learning Markdown into knowledge nodes without database or app dependencies.

The caller supplies the already resolved account learning root.
"""
import re
from pathlib import Path


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


def parse_thinking_tools(directory: Path, root: Path):
    """解析 现代思维工具教程 的『第N课：工具名』标题。"""
    nodes = []
    for f in sorted(directory.glob("*.md")):
        stage_name = f.stem
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^##\s*第[一二三四五六七八九十百零]+课[：:]\s*(.+)$", line.strip())
            if m:
                name = re.sub(r"[（(].*?[）)]\s*$", "", m.group(1).strip()).strip()
                nodes.append({"name": name, "category": "思维工具", "summary": stage_name,
                              "source": str(f.relative_to(root)), "kind": "tool", "date": ""})
    return nodes


def parse_footprints(root: Path):
    """解析课程/文章/练习文件名 → 学习足迹节点。"""
    nodes = []
    patterns = [
        (root / "每日认知与通识学习" / "每日课程", "认知课程"),
        (root / "英文阅读" / "每日文章", "英文阅读"),
        (root / "结构化表达" / "每日练习", "结构化表达"),
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
                          "source": str(f.relative_to(root)), "kind": "footprint", "date": date_s})
    return nodes


def scan_markdown(root: Path):
    nodes = []
    idx = root / "知识索引.md"
    if idx.exists():
        nodes += parse_index(idx)
    tt = root / "现代思维工具教程"
    if tt.exists():
        nodes += parse_thinking_tools(tt, root)
    nodes += parse_footprints(root)
    return nodes
