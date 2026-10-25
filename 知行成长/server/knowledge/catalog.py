"""Persist scanned nodes while preserving existing knowledge identities and links.

Connections are supplied by the caller so account scope remains request-local.
"""


def refresh_knowledge(nodes, get_conn):
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


def load_knowledge(get_conn):
    conn = get_conn()
    nodes = [dict(r) for r in conn.execute("SELECT * FROM knowledge ORDER BY category, id")]
    conn.close()
    cats = {}
    for n in nodes:
        cats[n["category"]] = cats.get(n["category"], 0) + 1
    return {"nodes": nodes, "categories": cats, "total": len(nodes)}
