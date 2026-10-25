# D1/D2 教练事实提醒专项验收

日期：2026-10-25。实施基线：`bca92aa`；实现提交：`d756cb2`。范围：无模型调用的 D1/D2，复用既有前台提醒；不包含 D3 自动 AI 报告、生产部署或真实业务库操作。

## 交付内容

- `GET /api/coach-facts` 读取当前账号已保存数据，使用 PostgreSQL 一致性只读事务，包含来源、范围、样本／阈值与判断边界。
- 今日及成长总览自动展示同一条事实；前三完整日分类记录减少、14天课程确认间隔、至少5条本周有效预测、连续及近7天活动事实／空态，优先级固定。
- 前台复用现有行动提醒刷新循环，5分钟限频与并发去重，跨日／确认保存后更新；有到时行动时让位，支持按账号当天收起与跨标签页同步，无新推送、定时器、权限请求或数据库表。
- 无记录、样本不足、数据库异常及账号变化不产生假事实。正文通过文本节点展示，不返回私人笔记，也不在浏览器缓存事实正文。
- 辅助事实请求不阻塞课程完成反馈；保存记录与事实读取故障分别处理。

用户规则与边界见[使用说明](../../../知行成长/docs/coach-fact-reminders.md)，实现规格及任务见[OpenSpec](../../../openspec/changes/coach-fact-reminders/design.md)。

## 验收结果

结论：**D1/D2 本地实现及专项验收通过。65 项 Python 用例通过（含10条真实 Chrome 流程），0失败、0跳过；另有7组 JavaScript 检查通过。**

| 验收组 | Python用例 | 结果 |
|---|---:|---|
| 教练事实 API／PG | 15 | 空态、阈值、样本、未来／无效日期、时区、课程状态、规则优先级、无模型、只读及错误脱敏通过 |
| 登录账号集成 | 20 | 原有账号回归及新增事实隔离、匿名拒绝、旧账号页拒绝、无 AI 配置读取通过 |
| 行动计划 | 10 | 原行动与提醒语义回归通过 |
| 成长统计 | 8 | 原统计和独立时长口径通过 |
| 节奏提醒 | 2 | 原默认开关、时间与跨客户端认领通过 |
| 新增真实 Chrome | 3 | 自动展示、同一事实导航、阈值、重试、收起、行动优先、键盘及320／768／1024／1440布局通过 |
| 既有导航 Chrome | 1 | 导航与原页面路径回归通过 |
| 既有节奏 Chrome | 6 | 设置、行动、总结、恢复、课程／文章回执及移动端回归通过 |
| 合计 | **65** | **全部通过，无跳过** |

- 7组 JS 包括 coach_facts_client、learning_completion_sync、navigation_layout、action_plan_client、action_p0_client、completion_producers、rhythm_client。新增覆盖限频／并发、文本安全、收起／跨日／账号变更、禁用存储、普通自动保存不逐次读库，以及慢事实请求不阻塞完成反馈。
- [逐模块结果](evidence/results.json)、[执行元数据](evidence/metadata.json)和 `evidence/modules/` 内的最终日志为通过证据。重复复验不重复累计用例数。
- 先保留[功能失败复现](evidence/backend-red.log)，再实现功能。审查时另外以[延迟失败用例](evidence/completion-latency-red.log)复现辅助读取阻塞完成，修复后[用例通过](evidence/completion-latency-green.log)。
- 一次合并静态复验因400秒总时限结束，已完成的两组通过，见[原尝试记录](evidence/combined-static-timeout.json)。剩余节奏 Chrome 组独立复验6项通过，最终静态增量也已通过；没有把中断尝试算作通过。
- 浏览器使用正式HTML、JS、事实接口和真实测试PG，记录全部请求；无未捕获JS异常、外部请求或生成调用。截图已人工查看：[桌面成长卡片](evidence/browser/growth-desktop.png)、[320px移动布局](evidence/browser/growth-mobile.png)、[预测样本事实](evidence/browser/prediction-fact.png)。
- 13份受测文件已记录[文件哈希](evidence/tested-source.json)，其中11份Python／JS文件通过AST或Node语法检查；HTML／CSS以真实浏览器渲染核验。`git diff --check` 和 OpenSpec 严格验证通过；本地文件链接检查见[链接记录](evidence/doc-links.json)。
- 各Python组使用现有隔离runner，真实数据库、外部网络和工作区写入拦截计数均为0。专用测试PG已停止，[清理记录](evidence/test-database-cleanup.json)列出中断夹具遗留在该已停止临时集群内的schema；不含真实账号数据，也未停止其他数据库实例。

## 复现方式

按[部署手册](../../deployment/standalone-web.md#隔离验收)创建一次性 localhost PostgreSQL，显式提供 `TEST_POSTGRES_DSN`。例如：

```sh
TEST_POSTGRES_DSN='host=127.0.0.1 port=专用端口 user=测试角色 dbname=postgres' \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
知行成长/.venv/bin/python -B 知行成长/server/tests/run_web_regression.py \
  --match 'test_coach_facts(\.py|_browser\.py|_client\.cjs)$' \
  --output /tmp/grow-coach-verification
```

账号集成组使用同一隔离 runner 的 `--child test_accounts.py --case-group AccountIntegrationTests`。浏览器组使用已安装的 Chrome 与 Playwright；新增浏览器夹具只有一次性测试记录，不导入用户资料。其他回归组和最终结果以证据中的逐模块记录为准。

## 边界与限制

- 本轮为受影响模块专项验收，不声称全站所有用例重新验收。浏览器夹具复用正式 HTML、JS、事实接口及 PG；部分周边模块为既有夹具的合成响应。
- 阈值是首版明确的产品规则，不是统计显著性、实际能力下滑或遗忘判断；课程缺少通用复习日志，所以只提示最近学完确认记录的间隔。
- 行动提醒及日常节奏的原设置与权限保留；不承诺关闭网页后的送达，未测试真实设备通知。
- 测试没有连接真实业务库、操作真实账号、调用外部模型或发布线上版本。B 真实使用仍可并行收集反馈，D3 保持未实施。
