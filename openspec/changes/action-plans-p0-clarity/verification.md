# P0 实施与验证记录

日期：2026-10-20，Asia/Shanghai。实现分支：`codex/action-plans-p0`。收尾代码提交：`fdfb08d`。

**结论：Grow 本地 P0 的适用自动化回归及指定浏览器验收已通过；连接端 P0 仍被阻塞。** 任务完成25/26，7.1已完成，7.3继续未完成。不扩展P1/P2，未部署、迁移真实数据或配对真实账号。

## 本轮修复与依据

1. 修复原回归 `LegacyCloudAPITests.test_course_generation_publication_learning_and_reading_ai` 的缺列错误。云端初始化调用公共 `legacy_schema.migrate()`，但建表定义缺少课程扫描已依赖的 `archived/archived_at`。新库现在完整建表，旧库即使已有迁移完成记录也执行幂等补列。没有DROP/重建学习表或覆盖历史笔记、分钟、课轮和归档值。
2. 新增旧库补列回归，先执行得到 `KeyError: archived`，修复后通过；原HTTP用例也通过。上一轮基线复现证据 [baseline-legacy-cloud-api.log](evidence/baseline-legacy-cloud-api.log) 保留，不再将该问题列为当前失败。
3. 启用原来跳过的真实Chrome用例，修正其旧「继续学习」页面定位与缺少server_time的行动API替身，保留保存丢响应、学习笔记、下一课、历史记录和移动端断言，没有跳过或放宽验证。
4. Chrome补测发现并修复Escape触发未初始化投资表单的空引用；快捷键只在对应页面可用。另修复学习日历空格继承全局empty样式导致移动端横向溢出，更新静态缓存版本。修复前的浏览器栈保存在 [closeout-browser-diagnosis.log](evidence/closeout-browser-diagnosis.log)，该日志是历史失败证据。
5. 增加本地API、双来源矩阵和可重复Chrome验收；文章与课程分别执行，不用某一路通过代替另一路。补齐第二隔离schema的行动/来源/事件/回执边界、双标签旧版本冲突、多草稿和未知请求恢复。

## 最终自动化结果

Python **139项通过，0失败/报错，0跳过**；两个Node客户端检查组通过。最终结果及每套件日志保存在 [regression-results.json](evidence/regression-results.json)。OpenSpec严格校验、修改脚本语法和差异空白检查通过。

| 套件 | 数量 | 结果 |
| --- | ---: | --- |
| test_action_p0 | 15 | 通过 |
| test_action_p0_sources | 3 | 通过 |
| test_action_p0_closeout | 11 | 通过 |
| test_action_p0_closeout_sources | 24 | 通过，12条共享合同分别对文章/课程执行 |
| test_action_p0_browser | 7 | 通过，真实Chrome与本地HTTP/DB |
| test_action_plans | 7 | 通过 |
| test_action_reviews | 13 | 通过 |
| test_daily_arrangements | 6 | 通过 |
| test_arrangement_sources | 5 | 通过 |
| test_github_plans | 15 | 通过 |
| test_study_notes | 11 | 通过 |
| test_study_materials | 5 | 通过，含原跳过的Chrome场景 |
| test_legacy_cloud_schema | 4 | 通过 |
| test_legacy_cloud_content | 9 | 通过 |
| test_legacy_cloud_api | 2 | 通过 |
| test_plan_read_errors | 2 | 通过 |

复现命令（在本工作区）：

```sh
TEST_LEGACY_PG_DSN='host=127.0.0.1 dbname=postgres user=hao' \
RUN_GITHUB_BROWSER=1 \
PYTHONPATH=知行成长/server:知行成长/server/tests \
/Users/hao/Documents/grow/知行成长/.venv/bin/python -u 知行成长/server/tests/run_action_p0_regression.py

node 知行成长/server/tests/test_action_plan_client.cjs
node 知行成长/server/tests/test_action_p0_client.cjs
openspec validate action-plans-p0-clarity --strict
```

Chrome默认路径为 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`，可用 `CHROME_EXECUTABLE` 指定已有浏览器。测试只使用localhost PostgreSQL临时schema、合成账号/内容、HTTP级GitHub替身和确定性模型替身；没有访问真实私人记录、发布GitHub资料或调用收费模型。

## 50例验收映射与证据边界

这里区分业务规则证据与设备/真实连接证据，不把表内一行自动当作一个Python测试。用例定义仍见 [acceptance.md](acceptance.md)。新增 `closeout` 测试主要填补上一版映射中的缺口。

| 用例 | 本地结果与对应证据 |
| --- | --- |
| F01–F02 | 原API/IAB及Chrome条件表单、未安排/安排后执行通过；API断言日期/时间/阈值null，无伪造日期 |
| F03–F04 | API非法标题、日期、时区、分钟及父级边界通过，拒绝无部分写入；Chrome验证原生数值约束、起步联动、服务端字段错误与输入保留 |
| F05 | 来源不可见/缺失API、真正第二schema访问拒绝通过；Chrome内容模式必须选具体来源；未接入模块只提供time |
| F06 | Chrome模式切换与隐藏字段清理通过，源文章/课程实际入口各走通；API归一化引用验证通过 |
| F07 | API缺日期/时间拒绝、Chrome错误及保留输入通过；有时间但无reminder的日历无alarm；设备权限另列 |
| F08 | Chrome真实POST落库后仅GET刷新abort，显示已保存/刷新失败、仅一项、成功草稿清除，已补齐上一轮缺项 |
| F09 | 合法/越界/异时区/未安排与上级API通过，无隐式修改日期 |
| F10 | Chrome首字段焦点、条件字段可见性、Enter保存、Escape存草稿与焦点返回通过；完整辅助技术使用体验未认证 |
| T01、T03 | API及Chrome分段5+15累计一项完成、中断20后显式完成通过；分钟不重复增加 |
| T02、T04 | API部分/关闭起步/墙钟推进120但只确认3/中断0/正常结束0拒绝通过；计时不自动完成 |
| T05 | API并发start仅一项、重新注册服务恢复同session通过；Chrome跨页面运行条保留 |
| T06–T08 | API状态/模式矩阵、运行中编辑/改期/取消/暂停及祖先操作阻断、已发生事实配置锁定通过；文章与课程均验证上级暂停后不消费事件，恢复可核对 |
| C01–C02 | 两来源API及Chrome实际确认、独立计时与内容完成通过；一条session加一条completion，只算一项完成 |
| C03 | 两来源API笔记/旧状态不足以完成新行动通过；原文章滚动位置回归和课程浏览器独立笔记通过；不将打开或滚动视为来源事件 |
| C04–C05 | 两来源API今日/未来/过去/null桶、明确origin补做与实际日期通过；Chrome日期安排/改期/来源上下文通过 |
| C06 | 两来源API同步失败、次日核对、重复核对、确认后改到未来/未安排拒绝通过；Chrome核对流程通过。服务同步故障为确定性注入 |
| C07 | 两来源API及Chrome运行中确认不静默结束，结算8分钟再核对，完成1/分钟8通过 |
| C08 | 两来源API同key同event、改payload冲突、缺失/异来源/创建前/异origin事件和外账号边界通过；来源不变/事实不增加 |
| C09 | 两来源API取消来源已读不撤销历史、另一日期新安排需新事件通过 |
| C10 | 两来源API在来源SQL事务内注入失败，来源、事件及行动均不产生假完成；原课程发布失败路径回归通过 |
| K01–K03 | API完成/撤销/再完成、不同key并发同revision、同key重放、非法模式/状态拒绝通过；Chrome勾选撤销与再次勾选通过 |
| S01–S02 | API并发、同标题异来源/同来源异标题、时区与null桶通过；Chrome来源重复加入复用ID，完成状态不被改写 |
| S03–S05 | API改期冲突字段/revision/事实不变、部分投入撤销日期保留快照、取消后新ID通过；两来源Chrome取消重建→明日改今日通过 |
| S06–S07 | API不顺延/未安排与未来执行拒绝通过；Chrome过去paused待调整、昨日running排除待调整、两步操作第二步冲突仍保留已安排日期和部分成功提示通过 |
| S08 | API提醒资格/无假时间日历/无alarm/免打扰/设备claim去重及祖先阻断回归通过；Chrome移动端学习记录与快速表单无横向溢出；真实设备导入/投递另列 |
| A01–A02 | API补做、跨午夜、新旧日期口径、复盘范围通过；文章与课程分别验证session归开始日、completion归确认日；记录不会被后来改期/时区编辑重算 |
| A03–A04 | 原复盘套件与API多会话/撤销/旧快照/预览哈希/v1事实保持通过；没有执行生产历史重写 |
| A05 | API执行后配置锁、终态限制与内容去重通过；Chrome复制新行动为active/0分钟/0完成，不带事实；双标签冲突保留旧页输入 |
| R01–R02 | Node上下文/日期/父级/账号隔离、同上下文多草稿与存储拒绝降级通过；Chrome账号A→合成B→A及刷新、选择草稿/新建另一份通过。浏览器账号切换替换fixture身份响应；不是生产登录联调 |
| R03–R04 | API幂等、客户端同key恢复/not found不换key/不可变pending和输入分叉通过；ChromePOST已提交响应abort、新输入保留、原key核对、真实双标签旧revision拒绝通过 |
| R05 | 两个真实隔离schema下的行动/来源/事件/回执拒绝、同源/跨站写入拒绝通过；生产身份服务联调未执行 |
| R06 | 本地版本头、不支持远端模拟、接管pending/active期间旧回执GET及配对不冻结通过；**真实Zook/原生合同集成未通过完成门槛，7.3仍阻塞** |

所有API/数据库注入均有明确预期，不依赖页面文字来证明持久写入；Chrome使用本地真实HTTP/数据库，且检查页面无未捕获异常。网络故障使用路由abort或fixture503，**没有物理关闭网卡/TCP链路**。

## 浏览器证据

本轮Chrome新增7条场景与原study-materials场景全部通过；上一轮IAB4张图作为历史观察保留。本轮证据：

- [键盘与草稿](evidence/05-closeout-keyboard-draft.png)、[丢响应后输入保留](evidence/06-closeout-lost-response-draft.png)。
- [安排成功但尚未开始](evidence/07-closeout-arrange-partial-success.png)、[累计计时与勾选](evidence/08-closeout-cumulative-and-check.png)。
- [文章计时/确认/核对](evidence/09-closeout-article-receipt.png)、[课程计时/确认/核对](evidence/09-closeout-plan-receipt.png)。
- [390px学习日历及记录](evidence/10-closeout-mobile-history.png)。快速创建另检320/390/768/1024/1440宽度，无文档或对话框横向溢出。

## 连接合同与剩余阻塞

详细证据、逐项差异、最小工作包与放行标准见 [contract-gaps.md](contract-gaps.md)。已对照Zook当前 `0ae27a4` 和两端含既有未提交改动的工作区，只读核对，没有修改它们。

1. Zook没有完整v2字段/三模式状态事实/统计与来源安排合同，现有实现明确只接time。
2. 来源事件尚未从Grow可靠投递到Zook；现有v1接管包遗漏事件及v2关系，不能安全迁移。
3. 两端尚无共享行动DTO/API/命令与页面；需要固定合同SHA，补账号隔离及未知请求恢复。
4. 真实隔离双端合同、原生实机、系统通知权限/设备日历、物理断网、完整屏幕阅读器、生产迁移与部署均未验证。它们不能由本地模拟通过替代。

因此7.3继续阻塞，带P0数据的新接管与未声明支持的远端写入继续关闭，不回退到本地双写。没有当前已知失败的本地回归项；也不宣称整体P0或连接模式已验收完成。

## 工作区与使用说明

工作目录：`/Users/hao/.codex/worktrees/action-plans-p0/grow`。前置19份日程/规格改动保存于 `d7bf19d` 基线，原工作区中的并行改动未覆盖。

- 普通新建默认勾选；time才填写标准/起步分钟，content需具体文章/课程；日期可以暂不安排。
- 内容完成和实际投入分别确认；运行时已经读完可先保存投入再核对回执。
- 未知提交先核对或原key重试；修改后的输入是独立草稿，不猜测性重建。
- 日期无具体时间不生成伪造日历；网页关闭后的通知仍需验证对应设备能力。


2026-10-21 连接端 C2 增量：来源证明、可靠投递与核对的实现、故障恢复/合同/完整回归和剩余阻塞见 [source-delivery-verification.md](source-delivery-verification.md)。C3/原生/真实连接放行未完成，总任务7.3继续未勾选。


2026-10-21 验收后修复：Zook 8个行数门禁失败已解决，合同警告212→197，详见 [source-repair-verification.md](source-repair-verification.md)。未启用连接写入或推进原生/C3。
