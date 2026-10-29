## Context
已批准会话中的整体实施方案。Python/FastAPI、PostgreSQL JSON 文档与原生 JS，现有执行事实和请求回执是唯一事实源。
## Goals / Non-Goals
Goals: 独立目标与短期计划、结果/投入分离、柔性安排、周规划、AI 草案闭环。
Non-Goals: 自动部署、跨端合同升级、自动完成、自动滚动积压、自动付费重试。
## Decisions
- 复用 action_plans 存储与 ID；entity_type 区分 goal/plan/action，period 增加 custom。旧记录在读取时确定性补类型，旧年目标默认使用固定次数口径。
- 工作区 version 1 与行动完成 schema 2 独立；新增写语义需 X-Grow-Workspace-Version: 1。
- 单一直接上级、无环、同账号/时区，周期越界只提示。目标可无周期；行动可关联上级且无日期。
- 结果标准及更新历史保存在实体 JSON；周规划与 AI 草案独立表。幂等、revision 与事务保证采用/安排不产生重复或半完成树。
- 目标最终完成须本人确认；投入与内容完成沿用原合同。AI 只输出校验草案，不操作工具，凭据不持久化。
- 目标/周期主视图、桌面侧边详情与窄屏全宽详情、统一创建、上下文草稿与返回状态。
## Risks / Trade-offs
旧客户端不理解新增字段 → 能力声明及兼容默认；既有跨端接管 → 沿用写入保护，不向远端转发工作区扩展。
## Migration Plan
增量建表，旧行不批量重写，保留全部 ID/事实；备份覆盖新增表，个人导出增量覆盖。按功能切片验收，不自动部署。
## Open Questions
无；按会话批准方案实施。
