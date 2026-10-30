# 本地研究归档与跨批次对比

2026-10-30 实现设计中的不可变归档、筛选／回测比较及完整备份恢复。PostgreSQL继续保存真值，文件是可校验副本；事前观察协议、AI报告语义对比、Parquet卸载仍属于后续扩展。

## 使用

进入「投资工作台 → 市场研究工具 → 归档与对比」。新建市场快照、历史、筛选、回测和对比后，在业务事务提交完成后自动归档；已有记录点「归档／重试」。失败只更新归档状态，不回滚研究记录、不改资金，也不重新请求供应商或模型。同一身份的文件不能覆盖；损坏归档须保留现场，核对备份后由管理员处理，重试不会悄悄替换损坏内容。

归档状态包括未归档、归档中、已归档、失败和损坏。状态为最近一次落盘或核验结果，磁盘变化由显式校验及下载时检测；下载包含所有来源依赖，并重新核验文件清单、SHA-256和数据库冻结版本。ZIP下载总量限制100MB；更大资料使用管理员完整备份。

选择同类的左右两个批次，保存冻结对比。历史选择器和差异每页50条，账户间隔离；关闭页面后可重新打开已保存对比。

- 筛选：区分同数据不同条件、同条件跨日期和混合输入。同一来源／单位／算法可比时计算精确指标差值；规则和资料同时改变时给出提示。覆盖新增／减少单列，不能当作条件进入／退出；null保持未知。保存数据日、采集时点、覆盖、规则和源版本哈希。
- 回测：核对历史哈希、算法、初始资金、年化与无风险假设。可比时比较绩效、费用、逐笔成交及订单拒绝原因；基线不同或资料不完整时只列原值，所有数值差值为null。保留参数试验及样本外上下文，不自动选优。
- 差值方向始终为右减左。金融数值以十进制字符串处理，不使用二进制浮点差分。JSON保留完整冻结结果；CSV用显式`null`表示未知，防护表格公式注入。普通正数及代码也须由表格软件按合适列类型导入，避免自行丢失前导零和精度。

## 本机目录与权限

本机已配置：`/Volumes/肖豪/project/grow-data/investment-research`。服务端`知行成长/server/.env`设置`INVESTMENT_RESEARCH_ARCHIVE_ROOT`，实际配置不进入Git；其他部署使用自己的绝对持久目录，留空关闭文件归档。目录必须独立于源码、static及可清理runtime。网页只提交对象ID和版本，不接收路径。

目录与子目录700，文件600；租户和账户路径使用哈希。使用FD相对打开、O_NOFOLLOW、原子发布、fsync、互斥锁及哈希。只允许macOS固定系统路径别名，其他祖先与子级符号链接均拒绝；特殊文件、硬链接和未声明条目也拒绝。写入暂存目录中断不会产生可下载的半份归档。

每个版本保存`manifest.json`、`record.json`和按数据类型拆分的gzip JSONL。大列表不重复塞入清单；可精确重建原数据库记录。清单记录格式／写入器版本、原记录哈希、来源、单位、币种、时区、算法和父版本。保存的是规范化冻结资料，明确标识不含供应商原始报文。来源依赖按引用保存，下载时打包。文件可能含私人研究内容，完整备份和下载副本也应私有保存。

## 管理员完整备份及恢复

沿用`standalone_backup.py`。先停止网页及全部写入，再按[部署手册](deployment/standalone-web.md)准备数据库、加密密钥和内容Git镜像。创建备份时需加载与服务相同的`INVESTMENT_RESEARCH_ARCHIVE_ROOT`；若数据库有ready引用但目录未配置、文件损坏或依赖遗漏，会拒绝完整备份。当前单份完整备份最多20000个已归档版本，超出会在发布前拒绝，需另行规划分卷。备份增加`research-archives.zip`，外层及内部清单均有哈希，不把原机绝对路径或凭证写入清单。pending/failed记录仍随数据库备份，恢复后可从冻结资料主动重试。

```sh
.venv/bin/python 知行成长/server/standalone_backup.py create /ABS/NEW_BACKUP \
  --content-mirror OWNER/REPO=/ABS/CONTENT_MIRROR.git --writers-stopped
.venv/bin/python 知行成长/server/standalone_backup.py verify /ABS/NEW_BACKUP
# DATABASE_URL须已指向全新的空数据库；加密密钥和内容绑定与备份一致。
.venv/bin/python 知行成长/server/standalone_backup.py restore /ABS/NEW_BACKUP \
  --content-directory /ABS/NEW_CONTENT \
  --archive-directory /ABS/NEW_RESEARCH --writers-stopped
```

含归档的恢复必须显式给新目录，不覆盖原归档。ZIP不使用任意路径解包；文件核验后才恢复数据库，最后核对数据库表计数、行哈希、归档身份和引用。清单遗漏归档但数据库存在ready引用时也会失败。任何失败都不要启动写入，保留新数据库／目录检查。旧的不含归档的备份兼容。

恢复成功后将`INVESTMENT_RESEARCH_ARCHIVE_ROOT`改为新归档目录再启动服务；不会据此重新授权外部调用。文件完整性不代替独立保存原加密密钥与接口凭证。

## API

均沿用当前登录用户的私人schema和投资账户校验，`Cache-Control: no-store`。写入沿用既有同源请求保护。

- `GET /api/investments/research/archives?account_id=...&page=1&page_size=50`
- `POST /api/investments/research/archives`、`.../archives/verify`：`account_id/object_id/version`；归档以不可变对象身份去重。
- `GET /api/investments/research/archives/{id}/download?account_id=...&version=1`
- `POST /api/investments/research/comparisons`：`account_id/left_id/left_version/right_id/right_version/name`，必须提供`Idempotency-Key`。
- `GET /api/investments/research/objects?account_id=...&kind=comparison`及既有对象详情。
- `GET /api/investments/research/comparisons/{id}/export?account_id=...&format=json|csv`

## 验证

隔离localhost PostgreSQL及真实Chrome用于写入／恢复测试，不向用户业务数据库灌入合成账户。已验证：精度和null往返、业务提交后磁盘失败重试、不可变冲突、断写、篡改阻止下载、链接和路径拒绝、跨账户拒绝、对比身份重放与资金不变、同规则跨日覆盖／未知差异、手算费用差额、不可比基线抑制全部差值、完整备份到空库／新目录恢复、备份遗漏归档元信息拒绝、桌面1440及手机390浏览器分页／下载／历史恢复／脚本转义。

最终验证见[证据目录](verification/research-archive-20261030/README.md)：本轮19项定向检查通过（0跳过、0失败、0错误）；桌面和手机真实Chrome流程通过。全站首轮1080项Python测试中1077项通过、2失败、1错误，39份JavaScript检查全部通过。3项旧浏览器用例定位为临时标准库HTTP服务的连接队列过小导致脚本连接重置；将隔离测试服务backlog从5增为128后，三项保留原功能断言定向重跑全部通过，未声称再次运行了完整全站检查。

本机服务`http://localhost:8756/`已重启到功能提交`4bd1326`，原登录通过、10个模块全部ready、新归档脚本HTTP200；1440和390宽度无文档溢出、无页面脚本错误或HTTP5xx。原账号目前0个投资账户，写入和备份恢复测试使用隔离localhost PostgreSQL，未向用户业务库写入合成研究账户。后续提交仅补充管理员离线恢复路径检查、测试环境和证据；运行中HTTP功能代码未变化。

独立只读审查所发现的不可比逐笔差值、CSV未知值、递归来源校验及备份漏元信息引用检查均已修复；额外跨模型审查按用户选择不追加。
