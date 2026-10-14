"""每日复盘 → Dashboard 自动同步脚本

功能：
  扫描 执行复盘/ 目录下的每日复盘 md 文件，
  提取关键信息（决策、结果、改进、洞察、新概念），
  生成一个 pending_sync.json 文件，
  Dashboard 后端启动时自动导入这个文件。

为什么不直接写 SQLite？
  外部磁盘（HFS+）有时会有 SQLite disk I/O 问题。
  用 JSON 文件中转更稳妥，也方便检查。

用法：
  cd 学习仪表盘/server
  python sync_reviews.py           # 扫描并生成 pending_sync.json
  python sync_reviews.py --force   # 强制重新扫描所有文件
  python sync_reviews.py --dry-run # 只打印要做什么，不生成文件
"""
import re
import json
import sys
import argparse
from pathlib import Path
from datetime import date

BASE_DIR = Path(__file__).resolve().parent
PENDING_FILE = BASE_DIR / "pending_sync.json"
LEARN_ROOT = BASE_DIR.parent.parent  # /Volumes/Xiaohao/学习
REVIEWS_DIR = LEARN_ROOT / "执行复盘"

FUPAN_MODULE_ID = "fupan"


def parse_review_file(filepath: Path) -> dict:
    """解析一个每日复盘 md 文件，提取关键信息。"""
    text = filepath.read_text(encoding="utf-8")
    result = {
        "date": "",
        "thought": "",
        "actual": "",
        "gap": "",
        "action": "",
        "decision_title": "",
        "decision_reason": "",
        "insight": "",
        "new_concept": "",
        "concept_explain": "",
    }

    # 提取日期：从文件名
    filename_date = re.match(r"(\d{4}-\d{2}-\d{2})", filepath.stem)
    if filename_date:
        result["date"] = filename_date.group(1)
    else:
        m = re.search(r"\*\*日期[：:]\*\*\s*(\d{4}-\d{2}-\d{2})", text)
        if m:
            result["date"] = m.group(1)

    # 按 ## 标题分块提取
    sections = {}
    current_heading = None
    current_lines = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_heading:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_heading:
        sections[current_heading] = "\n".join(current_lines).strip()

    for heading, content in sections.items():
        if "决策" in heading and "重要" in heading:
            m = re.search(r"决策[：:]\s*(.+?)(?:\n|$)", content)
            if m:
                result["decision_title"] = m.group(1).strip()
            m = re.search(r"依据[：:]\s*(.+?)(?:\n|$)", content)
            if m:
                result["decision_reason"] = m.group(1).strip()
            if not result["thought"]:
                result["thought"] = result["decision_title"]

        elif "结果" in heading:
            m = re.search(r"实际结果[：:]\s*(.+?)(?:\n|$)", content)
            if m:
                result["actual"] = m.group(1).strip()
            m = re.search(r"差异原因[：:]\s*(.+?)(?:\n|$)", content)
            if m:
                result["gap"] = m.group(1).strip()

        elif "重来" in heading or "调整" in heading or "改进" in heading:
            m = re.search(r"下次改进[：:]\s*(.+?)(?:\n|$)", content)
            if m:
                result["action"] = m.group(1).strip()

        elif "不错" in heading or "小成就" in heading or "做得好" in heading:
            m = re.search(r"小成就[：:]\s*(.+?)(?:\n|$)", content)
            if m:
                result["insight"] = m.group(1).strip()

        elif "概念" in heading or "新方法" in heading or "学到" in heading:
            m = re.search(r"概念[：:]\s*(.+?)(?:\n|$)", content)
            if m:
                result["new_concept"] = m.group(1).strip()
            m = re.search(r"解释[：:]\s*(.+?)(?:\n|$)", content)
            if m:
                result["concept_explain"] = m.group(1).strip()

    return result


def main():
    parser = argparse.ArgumentParser(description="每日复盘 → Dashboard 自动同步")
    parser.add_argument("--force", action="store_true", help="强制重新扫描所有文件")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不生成文件")
    args = parser.parse_args()

    if not REVIEWS_DIR.exists():
        print(f"❌ 目录不存在：{REVIEWS_DIR}")
        sys.exit(1)

    review_files = []
    for f in sorted(REVIEWS_DIR.glob("*.md")):
        if f.name in ("每日复盘模板.md", "README.md", "复盘记录.md"):
            continue
        if re.match(r"^\d{4}-\d{2}-\d{2}\.md$", f.name):
            review_files.append(f)

    if not review_files:
        print("📭 没有找到每日复盘文件。")
        print(f"   请在 {REVIEWS_DIR} 下创建以日期命名的复盘文件")
        return

    print(f"🔍 找到 {len(review_files)} 个复盘文件")
    print()

    # 收集所有同步数据
    sync_data = {
        "reviews": [],
        "decisions": [],
        "insights": [],
        "knowledge": [],
        "checkins": [],
    }

    for filepath in review_files:
        data = parse_review_file(filepath)
        if not data["date"]:
            print(f"  ⚠️  跳过 {filepath.name}：无法识别日期")
            continue

        date_str = data["date"]
        print(f"  📅 {date_str}: {data['decision_title'][:30]}...")

        # reviews
        if data["thought"] or data["actual"] or data["action"]:
            sync_data["reviews"].append({
                "date": date_str,
                "thought": data["thought"],
                "actual": data["actual"],
                "gap": data["gap"],
                "action": data["action"],
            })

        # decisions
        if data["decision_title"]:
            sync_data["decisions"].append({
                "date": date_str,
                "title": data["decision_title"],
                "context": "",
                "options": "",
                "reason": data["decision_reason"],
                "expected": "",
                "probability": None,
                "emotion": "",
                "actual": data["actual"],
                "bias": "",
            })

        # insights
        if data["insight"]:
            sync_data["insights"].append({
                "date": date_str,
                "insight": data["insight"],
                "source": "每日复盘",
            })

        # knowledge
        if data["new_concept"]:
            sync_data["knowledge"].append({
                "name": data["new_concept"],
                "category": "每日认知",
                "summary": data["concept_explain"],
                "source": f"执行复盘/{filepath.name}",
                "kind": "concept",
                "date": date_str,
            })

        # checkins: 执行复盘模块打卡
        sync_data["checkins"].append({
            "date": date_str,
            "module_id": FUPAN_MODULE_ID,
            "level": 1,
        })

    print()
    print(f"📊 统计：")
    print(f"   复盘记录: {len(sync_data['reviews'])} 条")
    print(f"   决策日志: {len(sync_data['decisions'])} 条")
    print(f"   个人洞察: {len(sync_data['insights'])} 条")
    print(f"   知识节点: {len(sync_data['knowledge'])} 个")
    print(f"   打卡记录: {len(sync_data['checkins'])} 条")

    if args.dry_run:
        print()
        print("（dry-run 模式，不生成文件）")
        return

    # 写入 pending_sync.json
    PENDING_FILE.write_text(
        json.dumps(sync_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print()
    print(f"✅ 已生成同步文件：{PENDING_FILE.name}")
    print()
    print("📌 下一步：")
    print("   1. 重启 Dashboard 服务（./start.sh）")
    print("   2. 服务启动时会自动导入 pending_sync.json")
    print("   3. 导入成功后，这个文件可以删掉")


if __name__ == "__main__":
    main()
