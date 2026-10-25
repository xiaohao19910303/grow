# 知行成长 · 个人学习与成长平台

「有思考 · 有执行 · 判断准确」的网页学习与成长平台。网页优先独立交付；App 已支持免登录记录、行动联动和已发布课程原生阅读；私人笔记、作答和显式学完通过单独授权同步。

独立安装、配置预检、备份恢复请按[网页独立部署手册](docs/deployment/standalone-web.md)。当前候选尚需以本批验收报告核对外部发布阻塞。

2026-10-24 文档口径：当前运行时为 FastAPI + PostgreSQL，正式新内容使用 GitHub，AI 按需配置；不设每日必学或连续打卡要求。代码、默认开关、当前专项验证与未验证状态见[版本与功能状态核查](docs/verification/current-state-2026-10-24/README.md)。下一步按[日常节奏 14 天使用验证计划](知行成长/docs/daily-rhythm-14-day-validation.md)收集真实案例，再确定改造切片。

## 入口导航

- [仓库结构与维护约定](docs/project-structure.md)

- [知行成长平台说明](知行成长/README.md)
- [当前版本与功能状态](docs/verification/current-state-2026-10-24/README.md)
- [D0启动检查与设置竞态修复](docs/verification/d0-startup-2026-10-24/README.md)
- [课程规划关联行动与阶段进度验收（C1/C2/C3）](docs/verification/learning-plan-actions-2026-10-25/README.md)
- [完成语义与 AI 配置引导验收（E2/E1）](docs/verification/completion-help-ai-setup-2026-10-25/README.md)
- [运行环境核验与设计样式收尾](docs/verification/runtime-design-closeout-2026-10-25/README.md)
- [日常节奏 14 天使用验证计划](知行成长/docs/daily-rhythm-14-day-validation.md)
- [内容生成与存储规则](知行成长/内容存储规则.md) — 模块目录、命名、课次、资料与索引约定
- [Grow 统一产品方案与 App 改造计划](../plan/docs/04-planning/grow-app-product-and-migration-plan-2026-10-18.md) — H5 负责规划与发布，App 负责学习、查看和日常记录，Zook 负责账户及连接
- [Grow App G0 核验与 G1 任务](../plan/docs/04-planning/grow-app-g0-2026-10-18/README.md) — 历史基线与后续任务参考，不作为本轮网页交付前置条件
- [客户端功能规划](../plan/docs/02-design/grow-client-feature-plan.md)与[迭代计划](../plan/docs/04-planning/grow-client-iteration-plan.md) — 记录、学习、行动三条路径，CF01–CF40 和 I0–I7；免登录、记录、行动与 I3 原生阅读已实现，I4 私人学习经来源回执同步，真机与发布待办

- [学习系统总览](学习系统总览.md) — 系统说明书：7 大模块 + 四层闭环
- [长期成长学习体系总规划](长期成长学习体系总规划.md) — 总纲：目标 + 路线图 + 度量系统
- `高认知能力训练规划.md` — 底层主线：12 月规划 + 三套模板
- `知识索引.md` — 知识总目录，随用随查
- [热门与深度文章](热门与深度文章/README.md) — 按需搜集热门文章与认知深度阅读，保存原文链接、摘要和阅读建议
- [A 文档收尾与 E3 稳定 ID 验收](docs/verification/a-e3-2026-10-25/README.md) — 本轮改动、隔离测试及部署边界
- [D1/D2 教练事实提醒验收](docs/verification/coach-facts-2026-10-25/README.md) — 基于已保存数据，无模型调用，复用前台提醒能力

## 快速开始

先按部署手册安装根 requirements.txt、准备 PostgreSQL 和自己的 server/.env，再运行：

```sh
cd 知行成长/server
../../.venv/bin/python deployment.py check
../../.venv/bin/python deployment.py serve --port 8756
```

## 七大模块

英文阅读 · 每日认知与通识学习 · 现代思维工具教程 · 结构化表达 · 深度写作 · 执行复盘 · 整合练习

手机原生阅读的授权、缓存和实现边界见 [接入说明](docs/grow-native-reading.md)。工程验收见 [本轮报告](../plan/docs/04-planning/grow-native-reading-2026-10-25/README.md)，真机与生产发布保留待办。
