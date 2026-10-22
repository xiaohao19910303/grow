# B00 独立网页交付候选

2026-10-22。基础提交：`0039de5991b43a2337e398daf1bcd5ed0c12774b`（fetch后origin/main相同）。工作树 `codex/web-standalone-batch1`。

主目录与full-suite-repair工作树的未提交工作不导入、不覆盖。主目录原文件指纹见baseline.json；C3分支不合并，连接门禁保持关闭。新节奏R03/R04未提交代码和R05后页面不属于此候选。

| 页面 | 支持的业务边界 | 存储与验收 |
|---|---|---|
| 今日/行动 | 创建、安排、三模式执行、事实、改期/撤销、原key核对 | Grow action_plans/executions/operations与来源事件；test_action_*、daily_arrangements |
| 学习 | 课程/文章正文、笔记/练习、明确完成、生成草稿与正式发布恢复 | PG私有元数据/反馈，GitHub正式内容固定SHA；cloud/reading/study/plans测试 |
| 记录 | 自由记录、旧四问、实践/错误、决策预测、专题记录 | PG账号schema；legacy_state/reflections/behavior/errors/stocks测试 |
| 成长/搜索 | 时间线、搜索、学习回顾、周月报、知识图谱及用户确认AI报告 | 原事实/快照，模块独立分钟口径；search/timeline/checkins/knowledge/review测试 |
| 设置 | 登录/邀请、个人GitHub配置、浏览器AI配置、局部导出 | auth public schema与账号私有schema，AI凭据不进备份；accounts/auth/config测试 |

执行入口：`server/tests/run_web_regression.py`。自动发现tests目录所有Python测试（包含原遗漏的pytest函数测试）和全部顶层test_*.cjs；每个Python模块在独立进程中应用原隔离审计。网页集合测试跳过/隔离阻断/失败均为失败，不允许靠成功子集放行。

唯一另列的跨仓测试为test_action_source_http.py（Zook HTTP/PG依赖），见test-profile.json。其余闭门禁/签名/拒绝回退的本地测试保留。此边界是交付形态，不把延后连接集合记为已通过，也不重开连接写入。

历史问题初始分类：

- 首次新建等待快照、重复导航/统计入口、浮层遮挡：当前代码已有修复，回归验证，不重写。
- storage失败静默、旧值覆盖内存、局部JSON误称完整备份：已复现/源码确认，本批修复。
- 旧test_state_browser状态等待、旧课程列表DOM、旧DB配置/PRAGMA：记录为待基线复现，按日志修复后再标通过。
- App、Zook、真实账号/设备/系统通知、线上迁移/公开部署：不在本批通过范围。
