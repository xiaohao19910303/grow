# 知识节点稳定 ID 与导入

知识图谱同时保留数字 `id` 与 UUID 格式的 `stable_id`。数字 ID 继续供已有连线引用，稳定 ID 用于跨请求查找同一节点；节点数与连线数不代表掌握程度。

## 更新规则

- 导入身份由 `source_path + name + kind` 确定。同一文件可以包含多个不同名称或类型的知识节点。
- 重复导入更新原节点；`source_hash` 是内容版本，哈希、摘要、分类等变化不会更换 ID，也不会删除已有连线。
- 名称、类型或路径改变属于另一导入身份，不自动推断为重命名或移动；需要保留身份时须先核对原节点，不能依靠内容哈希合并。
- 首次导入旧扫描节点时，按尚未绑定路径的 `name + source + kind` 精确匹配并沿用原 ID；若有多个候选，返回 409，保留全部原记录，由管理员核对。
- 来源路径只作为身份文本保存，不读取该路径的文件。不同账号的同一路径、名称和类型仍属于不同节点。

## 接口

| 请求 | 结果 |
|---|---|
| `POST /api/knowledge/upsert` | 返回 `{ok, knowledge}`，节点含数字 ID、稳定 ID、来源路径与哈希 |
| `GET /api/knowledge/by-stable-id/{stable_id}` | 返回当前账号的节点；不存在或属于其他账号时为 404 |
| `GET /api/knowledge/by-stable-id/{stable_id}/related?limit=5` | 返回 `{node, related, count}`；双向查找、节点去重，按最高关系权重降序，最多 20 个 |

导入正文必须包含字符串字段 `name, category, summary, source, kind, date, source_path, source_hash`。名称、类型、路径和哈希不能为空；不接受客户端指定 ID。非法正文返回 422，来源匹配歧义返回 409，数据库保存故障返回不含底层异常的 503。正式应用仍要求登录、同源写入标识 `X-Copilot-Request: 1` 和当前账号身份。

## 初始化与离线核验

应用启动时升级原账号；其他账号初始化时升级各自 schema。已完成旧云端迁移的账号也会补此升级，不因旧迁移已记账而跳过。迁移只添加列、约束和索引，为缺失 ID 的节点补 UUID，并设置数据库默认值，保障旧导入和扫描产生的新节点也获得 ID。

原数字 ID、已有非空稳定 ID 和连线均保留。若已有稳定 ID 重复，唯一索引创建失败会回滚该事务，需核对冲突记录，不能自动清表或更换已有身份。

管理员也可使用已配置 `DATABASE_URL` 的环境执行以下命令。显式填写实际账号 schema 名称；不是用户名。命令不读取 `.env`，请使用管理员已有的安全环境注入方式。

```sh
cd 知行成长/server
# 只读验证；成功退出码 0，失败退出码 1
../.venv/bin/python migrate_knowledge_stable_ids.py --verify --schema 实际账号schema
# 对所选 schema 增量升级，并验证；仅在确需离线升级时执行
../.venv/bin/python migrate_knowledge_stable_ids.py --schema 实际账号schema
```

解释器可替换为部署时使用的 Python。省略 `--schema` 时只操作连接的当前 schema，不会自动遍历其他账号。核验按目标 schema 检查列、唯一索引、非空约束、默认生成规则和缺失 ID；其他账号已经迁移不代表本账号已完成。

本轮仅在一次性 localhost PostgreSQL 中验收，未连接或迁移真实业务库，详见[专项验收](../../docs/verification/a-e3-2026-10-25/README.md)。
