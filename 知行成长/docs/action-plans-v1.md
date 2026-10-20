# 行动计划第一版

2026-10-18。入口为首页「我的行动计划」或「今日 → 行动计划」。本轮仅实现 Grow 网页能力，LightTick 提供联动设计。

## 使用方式

1. 新建年、月、周或日计划，选择长期／短期分类；既可独立创建，也可关联日期、时区相容的上级计划。
2. 长计划设置目标达标次数，拆出具体日行动；日行动设置标准分钟、较小起步分钟、时间和提醒。最多显式安排同周七天，不自动把未完成计划滚入次日。
3. 首页优先显示正在执行和今日待执行行动。「开始学习」进入关联课程或历史文章；「先做 5 分钟」降低开始门槛。纸质书可仅记执行。
4. 刷新后继续执行；结束时本人确认实际分钟，可保存达标、起步、部分执行或中断记录。起步不会冒充达标，行动完成不会标记课程学完，课程笔记仍可独立暂存。
5. 在计划卡片查看进度，并打开「进度复盘与 AI 建议」。选择范围、记录做得好／阻碍／下一步，关闭后保留草稿，每次保存产生历史快照。
6. AI 使用设置中的个人配置。先查看数据预览，按需勾选执行说明和已保存复盘，确认后主动生成。总结、失败状态和历史持久保存；建议仅供参考，调整需手动保存。

进度以实际执行事实计数，进度条上限 100%，额外执行仍保留；长计划完成状态由本人确认，进度数字不等同于课程掌握程度。复盘日期按执行快照的业务日期，不会因服务器时区变化而移动。

## 提醒边界

网页打开时有站内提醒；桌面通知需主动允许，22:00–08:00 免打扰并按设备去重。可延后 15 分钟。网页关闭后的提醒通过下载 `.ics` 导入设备日历；需要在日历端确认通知权限。日历是独立副本，后续改期、暂停或归档需同步调整日历，当前没有后台 Web Push 或已上线的 LightTick 原生同步。

## 数据、接口和恢复

租户 PostgreSQL 中的 `action_plans`、`action_executions`、`action_operations`、`action_reminder_claims`、`action_reviews`、`action_reports` 独立保存私人计划、执行、请求回执、提醒去重、复盘、AI 结果；首次访问做增量建表，不改旧笔记、课程或待办表，不把私人数据写到 GitHub。

私有浏览器 API 均位于 `/api/action-plans`，沿用 Cookie 登录、账号请求头、同源写保护和 no-store：

| 路径 | 用途 |
| --- | --- |
| GET / | 计划、下级汇总、当前执行和服务端时钟 |
| POST / | 新建或同周批量创建，带持久请求 key |
| POST /{id}/operations | 带 revision 和 key 的编辑、暂停、恢复、归档、目标确认、开始、结束和延后 |
| GET /records | 30 条分页执行记录 |
| GET /requests/{key} | 查询失联请求是否已提交 |
| GET /{id}/calendar.ics | 带时区和可选提醒的日历导出 |
| POST /reviews/preview | 计划子树、日期和可选内容的准确预览与快照哈希 |
| POST /reviews | 保存手动复盘及当时统计 |
| GET /reviews?plan_id=…&page=… | 20 条分页手动复盘与 AI 历史 |
| POST /reviews/generate | 显式 consent、snapshot_hash、个人 ai_config 的异步生成，202 |

请求 key 重试返回同一结果，内容变化冲突；revision 防止旧页面覆盖。一个账号同时只运行一次执行。浏览器草稿和待确认请求按账号隔离；AI 凭据仅在调用时传给后端，不进入待确认请求缓存、操作回执、报告或日志。已有 AI 设置仍按项目既有方式保存在该账号浏览器中。

统计覆盖选定范围的全部事实，模型明细最多最近 30 条；执行说明最多每条 300 字符、复盘最近五次的每个文本字段最多 400 字符，截取标记可在完整预览查看。不读取学习笔记，也不推断刷视频时长。预览后数据有变更则拒绝生成。90 秒超时；不自动重试收费调用。服务重启或超过 120 秒未结束的生成会显示失败，保留已有记录，由用户主动重试。本版按本地现有单 worker 服务运行，横向多 worker 前需把生成租约改为跨进程共享。

LightTick 原生接口唯一合同源仍为 `Zook/api-contracts/openapi/lighttick`。这些 Grow 私有接口不作为原生公共合同；统一接管前 Grow 新计划与 Zook 原任务各只有自己的唯一写入方。

## 验证

定向回归使用 localhost PostgreSQL 的一次性 schema，不读取正式账号或调用真实模型。浏览器验收服务为 `server/tests/serve_action_plans_fixture.py`，真实计划／执行／笔记／素材路由加确定性模型替身。

```sh
TEST_LEGACY_PG_DSN='host=127.0.0.1 dbname=postgres user=hao' PYTHONPATH=知行成长/server:知行成长/server/tests 知行成长/.venv/bin/python -m unittest test_action_reviews test_study_notes test_study_materials test_local_server_environment
node 知行成长/server/tests/test_action_plan_client.cjs
```

本轮验收证据与尚未验证的范围见 OpenSpec change 中的 `verification.md`。
