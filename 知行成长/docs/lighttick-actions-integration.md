# Grow 行动计划联动验收（2026-10-20）

当前实现：年/月/周/日计时计划、长短期筛选、进度、开始/起步/中断、执行记录、复盘草稿与历史、提醒、五分钟连接码、同账号缓存和原请求重试。iOS 的执行结束表单也保存本机草稿。课程完成与学习笔记保持独立，AI 在网页预览并确认后生成，客户端查看历史。

后端 canonical 源：Zook `api-contracts/openapi/lighttick`；本机客户端快照固定到 `993a84ae58260e8d84007362edd24779653b8a2a`。后端最终兼容保护提交 `0ae27a4`。功能默认关闭，未部署线上，未迁移真实账号。

## 已验证

- 本地 PostgreSQL 独立数据库/schema，真实公共登录与 Grow cookie 登录；源冻结和备份、签名桥接、回执核对。
- CUA 实际操作：网页建立年→月→周→日计划；iOS 生成码，网页预览4计划后接管；iOS 开始5分钟，网页显示同一执行；iOS 保存起步5分钟；网页保存标准20分钟，iOS 随后显示完成；另一个日行动中断2分钟；iOS 保存复盘，网页历史一致。
- HTTP 独立核对：5计划、3执行一致；上级累计27分钟/1达标/1起步/1中断；复盘1条与AI历史一致；Bob测试账号无泄漏。
- Grow 18项；Zook main 合并后32项（含真实PG、契约和既有规划回归）；iOS 27项；Android 全部104项单元测试，两个平台Debug构建通过。
- 客户端合同快照校验通过。Zook行数门禁仍有8个既有文件超限，本次未增加超限文件。

## Android 本轮补验

- API 36 模拟器实际通过登录、进入行动计划、生成连接码；网页确认接管4项年/月/周/日计划。随后Android自动同步显示计划，并实测日行动五分钟起步。HTTP逐项核对网页与客户端服务端快照一致。
- 修复登录软键盘遮挡提交入口：邮箱专用键盘、“下一项”聚焦密码、“完成”提交并收起键盘，表单避让键盘，提交中禁止重复登录。已通过屏幕键盘完成登录实测。
- 隔离服务最低Android版本从1.0调整为候选包0.1，消除验收升级阻断；只改fixture，未调整生产版本门槛。Zook `53cf8d3` 已进入main，main重跑9项相关测试通过。
- Android新增控制器重建恢复执行/结束草稿、离线不可提交、重新核对后消除远端已结束执行的回归，以及提醒时区/稳定标识/改期/清晨免打扰回归；104项单元测试通过，Debug构建通过。
- 两次 `am force-stop` 后重新进入行动计划，均恢复原执行；第二次还恢复结束表单的5分钟草稿。本人确认后仅生成1条minimum记录，执行ID未变。网页目标页显示上级累计5分钟、1次起步，未误算达标。
- 修复本地/内网服务可达但Android未验证公网时提醒永远等待的问题：移除WorkManager公网连通性约束，由worker实际访问API核对最新状态，失败重试；旧任务按scheduler.version=2迁移。修复提交 `2d2e3d8`，104项测试和Debug构建再次通过。
- Android通知权限通过真实系统弹窗允许。修复后系统任务SUCCESS，NotificationManager实际登记提醒。另一个未来提醒排定后kill -9客户端，确认进程消失；临时断开8080验收转发后，由JobScheduler重新唤起进程，任务RETRY且无通知；恢复转发后自动重试SUCCESS，通知中心仅登记1条对应提醒。未绕过最新服务端状态核对。
- 后台首次派发使用 `cmd jobscheduler run -s`，保留全部约束，避开Android批量调度等待；网络恢复后的重试由系统自动运行。因此这证明进程重建、失败重试与系统通知入列，不证明精确到分钟的自然后台送达。
- 当前独立Android场景：6计划、1执行，上级累计5分钟/0达标/1起步/0中断；与上一轮iOS的27分钟分开。证据目录 `.gstack/lighttick-actions-2026-10-20/`：`android-recovered-execution.png`、`android-recovered-finish-draft.png`、`android-after-kill-reminder-proof.txt`、`android-reminder-worker-results.txt`、`android-verification.json`。

## 尚未验证与限制

Mac 再次自动锁定中断了CUA操作，已请求手动解锁。Android通知视觉截图和点击、手动复盘UI以及标准20分钟/中断路径尚未补齐；iOS通知和杀进程也尚未补验。Android执行与结束草稿杀进程恢复已经通过UI实测，系统通知入列与断网恢复已通过OS证据验证，不把这些等同于完整验收或真机省电场景。正向提醒使用独立UTC日行动，避免当前上海22–08免打扰使夜间验收误判。

iOS 本地通知在前台核对后重排，App关闭期间网页改变无法保证立即取消；Android WorkManager 送达前联网复核，受省电调度影响，不是精确闹钟。22–08免打扰。

首版仅接管计时计划；`completion_mode=content/check` 的新网页日程会明确拒绝接管并保持原数据，不能悄悄转换完成口径。

## 复验环境

隔离 Zook `http://127.0.0.1:18880`（本机8080转发供原生Debug连接），隔离Grow `http://127.0.0.1:18881`。不要把真实账号计划导入这些fixture。脚本：Zook `test/support/serve-action-link-fixture.ts`，Grow `server/tests/serve_action_link_fixture.py` 和 `verify_action_link_fixture.py`；仅允许显式localhost数据库，退出清理隔离数据。

网页截图：`/Users/hao/Documents/grow/.gstack/lighttick-actions-2026-10-20/web-client-review.png`。
