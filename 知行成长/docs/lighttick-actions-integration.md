# Grow 行动计划联动验收（2026-10-20）

当前实现：年/月/周/日计时计划、长短期筛选、进度、开始/起步/中断、执行记录、复盘草稿与历史、提醒、五分钟连接码、同账号缓存和原请求重试。iOS 的执行结束表单也保存本机草稿。课程完成与学习笔记保持独立，AI 在网页预览并确认后生成，客户端查看历史。

后端 canonical 源：Zook `api-contracts/openapi/lighttick`；本机客户端快照固定到 `993a84ae58260e8d84007362edd24779653b8a2a`。后端最终兼容保护提交 `0ae27a4`。功能默认关闭，未部署线上，未迁移真实账号。

## 已验证

- 本地 PostgreSQL 独立数据库/schema，真实公共登录与 Grow cookie 登录；源冻结和备份、签名桥接、回执核对。
- CUA 实际操作：网页建立年→月→周→日计划；iOS 生成码，网页预览4计划后接管；iOS 开始5分钟，网页显示同一执行；iOS 保存起步5分钟；网页保存标准20分钟，iOS 随后显示完成；另一个日行动中断2分钟；iOS 保存复盘，网页历史一致。
- HTTP 独立核对：5计划、3执行一致；上级累计27分钟/1达标/1起步/1中断；复盘1条与AI历史一致；Bob测试账号无泄漏。
- Grow 18项；Zook main 合并后32项（含真实PG、契约和既有规划回归）；iOS 27项；Android 全部102项单元测试，两个平台Debug构建通过。
- 客户端合同快照校验通过。Zook行数门禁仍有8个既有文件超限，本次未增加超限文件。

## 尚未验证与限制

Mac 锁定中断了 CUA 操作。Android 模拟器已安装QA包，但尚无完整UI联动验收；系统通知真实送达、点击和两端杀进程恢复仍需解锁后补验。单元测试已覆盖待确认请求重启恢复、账号隔离、提醒筛选与免打扰，不把这些等同真机后台送达。

iOS 本地通知在前台核对后重排，App关闭期间网页改变无法保证立即取消；Android WorkManager 送达前联网复核，受省电调度影响，不是精确闹钟。22–08免打扰。

首版仅接管计时计划；`completion_mode=content/check` 的新网页日程会明确拒绝接管并保持原数据，不能悄悄转换完成口径。

## 复验环境

隔离 Zook `http://127.0.0.1:18880`（本机8080转发供原生Debug连接），隔离Grow `http://127.0.0.1:18881`。不要把真实账号计划导入这些fixture。脚本：Zook `test/support/serve-action-link-fixture.ts`，Grow `server/tests/serve_action_link_fixture.py` 和 `verify_action_link_fixture.py`；仅允许显式localhost数据库，退出清理隔离数据。

网页截图：`/Users/hao/Documents/grow/.gstack/lighttick-actions-2026-10-20/web-client-review.png`。
