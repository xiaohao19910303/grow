# 网页独立交付第一批验收

实施始于2026-10-22，验收收尾于2026-10-23。本地实施分支 `codex/web-standalone-batch1`，基础 main `0039de5991b43a2337e398daf1bcd5ed0c12774b`。冻结代码与测试候选 `a9c72ae`（冷启动补修在`84bb945`，测试执行预算在`176aaac`），文档追加提交不改变被测代码。最终完整网页回归通过，本地独立启动与恢复通过；Linux实际运行及公开部署的外部放行仍未完成，不能据此宣布可公开上线。

## 范围与保护

实现 B00、D01–D06、W01/W02 的本地切片。起始记录原主目录16份未提交文件；收尾复核时其中6份出现并行修改，primary HEAD仍未变。本批未写入主目录，也未还原或覆盖这些变化，详见 preservation-check.json；并行变化未纳入本候选，因此不声称当前全部指纹仍与起始一致。未导入 full-suite-repair 工作树的未提交修复；未合并 C3 连接分支。只在独立工作树提交，未推送、合并主分支或发布线上，原先打开的 localhost 页面不自动代表此候选。

App/Zook 无改动；连接写入、配对、接管和导入门禁保持原状；独立读写验收针对solo/未联动账号，既有pending/active账号不自动解绑或变更写入归属，现有本地拒绝写入合同留在回归。仅依赖 Zook 独立 HTTP/PG fixture 的 test_action_source_http.py 单列延后，不能计作网页通过。

## 已实施的交付切片

| 项目 | 实现与本地验证 | 状态边界 |
| --- | --- | --- |
| B00 | 固定main候选、五栏/API/存储边界、工作区指纹、网页集合自动发现与逐模块隔离 | 已完成 |
| D01 | 配置例值全部占位，强密码、PG URL、Fernet、单worker校验；日志不回显配置值 | 本地完成；历史凭证有效性/轮换需持有者确认 |
| D02 | 单一requirements.lock，干净Python环境安装及pip check；统一deployment.py check/serve、本地manage与Render/Docker入口；发行教材白名单导出，排除历史个人记录/进度，LEARN_ROOT显式配置 | 本机通过；干净Linux构建未通过环境检查 |
| D03 | 新库管理账号/邀请/租户/核心读写、重复启动；代表性旧表升级、记录保留及拒绝不明确迁移 | 已完成合成验收；未操作生产旧库 |
| W01 | 持久/仅内存状态、配额/禁止存储持续提示、局部恢复副本、严格账号/格式校验、原key重试、共享存储最新值和失败删除墓碑 | 已完成；存储被禁用时强行刷新仍无法自动持久，页面提供下载路径 |
| W02 | 局部副本实际范围、准确文件名与说明；清空范围明确，服务端确认后才成功；丢响应/冲突/失败保留当前输入 | 已完成；不新增全站JSON导入协议 |
| D04 | 去除定时阅读的固定域名/仓库；默认关闭自动搜集；精确OIDC audience/repository/id/workflow/ref签名合同，禁用时不依赖内容模块就绪 | 已完成合成合同；真实Actions唤醒未验证 |
| D05 | 全数据库一致性pg_dump、表数量/逐表摘要、账号绑定/内容SHA、独立Git bundles、包SHA256、原密钥指纹及保护权限 | 已完成合成备份与篡改/缺版本拒绝；镜像须由管理员供给 |
| D06 | 另一空数据库/新运行目录恢复、Git fsck/版本核对、实际网页API重启读取与租户隔离、发布补确认一次、任务中断保留输出、失败升级事务回退 | 已完成本地合成；不等同线上切流或真实GitHub灾难恢复 |

配套[部署与恢复手册](../../deployment/standalone-web.md)包含工具、角色权限、HTTPS/Cookie、单worker、停写确认、保留策略与升级回退命令。网页的局部副本不覆盖行动、独立笔记、正式内容或账号；浏览器未同步草稿与个人AI配置也不在服务器包中。

## 回归修复说明

- 实际产品：新部署材料目录混有历史个人记录（改为正式教材白名单，新管理账号从未学习开始，旧根目录不删除）；PostgreSQL 初始化误执行 PRAGMA；课程已有完成记录时仍展示“待本人记录”；首次创建行动早于初始快照就绪导致提交失败（现等待快照并保留期间输入）；LoadingState.start 缺失导致页面加载异常；行动草稿存储失败被旧值覆盖/删除后复活及跨标签缓存；日常记录冲突重载再次载入旧浏览器草稿。
- 测试合同：按真实页面入口补展开执行条、学习库、历史文章与新按钮；补缺失的笔记/加载依赖、server_time与main.wrap；旧SQLite专用测试改用隔离PG；无夹具的课程全流程改为确定性数据和明确AI配置。不删业务/console断言、不放宽浏览器单步超时、不跳过失败；账号模块外层执行预算调整另见下文。
- 首轮519项Python诊断与20份JS发现26个失败模块；该诊断期间有并行修复，属于找错记录，不是冻结候选的通过证据。首次、定向和最终完整集合分别留档。

账号文件原整文件300秒总时限在宿主压力下超时，日志已执行33项但未输出最终统计。改为三个既有测试类各600秒、浏览器单步时限不变；自动核对整文件collect节点与各组并集，漏测、重复或收集漂移即失败。仅collect-only的1/18/19统计用于验证分组，不算业务通过。

## 验证结果

| 验证 | 最终结果 | 证据 |
| --- | --- | --- |
| 完整网页集合 | 87份Python文件、539项用例；22份JS测试文件；111执行组；0失败、0跳过 | [最终摘要](evidence/final-summary.json)、[逐组结果](evidence/verified-final/results.json) |
| 真实账号与浏览器 | 账号1+18+19全部通过，整文件节点覆盖检查通过；P0 Chrome 7项、冷启动Chrome 1项及其他网页浏览器检查通过 | 同目录逐文件日志、screenshots |
| 独立启动与发行边界 | 启动/登录/核心记录/重启1项、配置4项、教材隔离2项通过 | test_deployment_boot/config、test_packaged_materials日志 |
| 故障恢复 | 真实pg_dump/Git备份6项、另一空库/新目录的实际API恢复与重复重启1项通过 | test_standalone_backup/recovery日志 |
| 定时合同 | 10项通过；无真实Actions请求 | test_daily_reading_schedule日志 |
| 环境与规范 | 48项生产依赖精确匹配，pip check通过，manage/start正确路径bash -n通过，OpenSpec严格校验通过；隔离审计0次越界阻断 | runtime-lock-check.json、[环境检查](evidence/final-environment-checks.json)、[规格校验](evidence/openspec-validate.json) |
| Linux实际运行 | 未通过环境准备：Docker daemon不可连接；镜像未构建、Linux恢复未执行 | [构建记录](evidence/linux-build.log) |

JS按测试文件计数，未伪称22项用例；账号浏览器类含继承的API用例，以原始38个collect节点为准。范围内无失败和跳过；跨仓Zook模块明确排除，不计通过。完整结果不包含主目录的并行未提交代码。

较早完整轮次535项Python/22份JS中账号模块失败；随后整体文件/分组时限导致的超时及被新候选替代的中止均保留，均不计通过。原进程采样看到真实Scrypt派生占用，未观察到PG锁等待，故只调整外层预算并保留原口令参数/浏览器限时。最终冻结候选重新从头完成539项，而非拼接定向结果。

已完成定向：配置4、定时合同10、真实启动/重启1、pg_dump/Git备份6、实际API空库恢复1、局部操作Chrome1，及草稿/加载/冲突恢复等浏览器检查。不同定向集合有重复，不相加冒充独立总数。

## 环境与命令

- macOS、全新Python3.13.9环境 `/tmp/grow-web-batch1-env`，锁定生产依赖另装pytest/playwright；pip check无破损依赖。
- 专用PostgreSQL15.17，localhost:55491，测试随机schema或web_boot_/web_backup_一次性数据库；无真实账号、GitHub/AI请求。备份使用真实pg_dump/pg_restore与真实Git提交/bundle，网页协议端用受控HTTP夹具读取恢复的bundle。验收后已停止本轮专用PG，未停止其他数据库服务，见evidence/test-database-cleanup.json。
- Chrome155真实浏览器；JS Playwright1.64.0，通过独立NODE_PATH提供，代码工作树无node_modules。
- Linux Python3.12 x86_64/aarch64各48份锁定依赖wheel下载/解析成功，已记录文件哈希；这是依赖可获取性检查，未运行Linux后端或镜像。
- 启动路径实测使用 deployment.py，缺少GitHub/AI/App/Zook可登录并保存核心记录；本机HTTP用CLOUD_DEPLOY=0，HTTPS会话另列外部验证。

```sh
PATH=/opt/homebrew/opt/postgresql@15/bin:$PATH \
TEST_POSTGRES_DSN='host=127.0.0.1 port=55491 user=grow_web_test dbname=postgres' \
NODE_PATH=/tmp/grow-web-batch1-node/node_modules \
/tmp/grow-web-batch1-env/bin/python -B 知行成长/server/tests/run_web_regression.py \
  --output /tmp/grow-web-batch1-evidence/verified-final
```

原始日志路径 `/tmp/grow-web-batch1-evidence/`。最终逐组结果、日志、截图与关键定向记录已复制到[证据索引](evidence/README.md)。网页发现集合见test-profile.json；子进程会清除真实DATABASE_URL/桥接凭证，拒绝真实工作区写入、外网连接和非localhost数据库，失败/跳过/阻断均导致返回失败。

运行期间宿主两次空间告急，一次导致本轮一次性PG中断。只清理本轮可重建临时库/包下载缓存后重建同端口PG，先前DiskFull结果标环境失败并重跑；不清理用户业务库、源码或其他工作树。Docker Desktop启动失败，构建日志为“Docker Desktop is unable to start”，未伪造干净Linux通过。

## 剩余阻塞与延后项

1. **D01外部放行**：历史示例中非占位凭证是否仍有效/已轮换，持有者尚未确认。本轮无权凭空核销，不访问旧地址。
2. **D02 Linux交付门槛**：Docker Desktop不可用，干净Linux安装/镜像构建与Linux恢复路径未验证。Dockerfile和同锁命令已提供，本机启动/恢复通过不替代此项。
3. **公开部署门槛**：真实域名/TLS代理/Secure Cookie、真实GitHub权限及故障恢复、真实Actions OIDC唤醒、选用AI供应商尚未实测。未做生产部署。O01就绪/运行诊断属于后续清单，公网放行前仍需补齐。
4. **备份操作前提**：管理员必须停止全部写入，并为所有默认/自定义仓库提供覆盖历史/待发布SHA的bare mirror；丢失的SHA/原Fernet密钥不能由脚本编造。包不含集群角色/ACL、外部认证、未同步浏览器草稿、浏览器AI配置或旧未导入pending_sync文件；这些需另行安全保管。
5. **已识别未扩展体验**：阅读collectForm载入/setup只更新query，未同步数量/主题；真实手机、屏幕阅读器和规模性能未验证，依后续网页清单处理。浏览器样例中的390宽度不能替代真实设备验收。
6. **范围延后**：App、Zook、原生消费者与跨仓连接HTTP合同、连接写入、P1/P2均未推进。原并行节奏工作未纳入本候选，收尾检测到的6份并行变化保持原样。

本批可形成本地网页候选；完整公开交付仍须解除以上适用门槛。任何未验证项均不计为通过。
