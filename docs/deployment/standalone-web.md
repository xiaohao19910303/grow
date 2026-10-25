# Grow 网页独立部署与恢复

第一批支持：单实例、单 worker，Python 3.11–3.13、PostgreSQL 15，正式内容使用自己的 GitHub 私有仓库。App、Zook、桥接密钥和 AI 均不是网页核心操作的前提。独立读写验收针对 solo/未联动账号；既有 pending/active 联动状态恢复后继续受原有冻结和写入归属门禁保护，不自动解绑或让 Grow 接管连接侧行动。本手册不授权生产发布或连接写入。候选与验收状态见 `docs/verification/web-standalone-batch1/`。

## 唯一主路径：安装、预检、启动

在 Linux 安装 Python 3.12、venv、Git、PostgreSQL 15 客户端，准备一个专用于 Grow 的数据库（不要与其他应用共库）。数据库角色须有 CONNECT、CREATE SCHEMA 及其自有表的建表/读写权限；通过同一主版本的 pg_dump/pg_restore 备份。管理员不是 PostgreSQL 超级用户也可运行网页，创建测试数据库的权限只用于隔离验收。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
cp 知行成长/server/.env.example 知行成长/server/.env
chmod 600 知行成长/server/.env
# 编辑占位值，创建 /var/lib/grow（或自己的目录）并授予运行用户写权限。
# LEARN_ROOT 设为下一步新导出的绝对路径，例如 /var/lib/grow/materials。
cd 知行成长/server
../../.venv/bin/python prepare_materials.py /var/lib/grow/materials
../../.venv/bin/python deployment.py check --offline
../../.venv/bin/python deployment.py check
../../.venv/bin/python deployment.py serve --host 127.0.0.1 --port 8756
```

项目根 requirements.txt → requirements.lock 是唯一生产依赖入口；server/requirements.txt 仅兼容旧命令。requirements.in 记录直接约束，更新后须重新生成锁并跑验收，不能在线启动时自动升级依赖。测试依赖另装 server/requirements-test.txt。原 manage.sh / start.sh 改用相同预检与入口，可用 GROW_PYTHON 指定解释器；后台启动失败要检查其日志，不以启动脚本提示代替 HTTP 验证。

`check --offline` 不连接数据库，但仍校验必填配置、依赖、教材目录以及运行目录可写性；会按配置创建运行目录并写入临时探测文件。离线通过不表示数据库已可连接，也不表示服务已启动。`serve --offline` 会明确拒绝，启动仍必须完成数据库预检。项目根也可运行 `bash 知行成长/manage.sh check --offline` 或 `bash 知行成长/manage.sh check`；预检不产生服务 PID 或后台日志。

deployment.py 只读取进程环境、server/.env 和根 .env.local 中白名单存储变量；进程环境优先，不执行文件中的 shell 文本，不从旧共享配置导入管理密码。新安装推荐只用独立的 server/.env 或部署平台的受管秘密。错误提示只包含变量名；不要把 .env、数据库 URL、token 或含正文的服务日志提交到 Git。

| 变量 | 要求及作用 |
| --- | --- |
| DATABASE_URL | 必填，专用 PostgreSQL URL，含地址与库名；生产启用 TLS |
| APP_USERNAME / APP_PASSWORD | 初始/原管理账号；用户名默认 owner，密码至少24字符。每次启动可能按此密码更新原管理账号，恢复时须明确保留或轮换 |
| ACCOUNT_ENCRYPTION_KEY | 必填，Fernet 密钥；单独安全备份，不能每次启动重新生成。自定义 GitHub token 用它加密 |
| PLAN_CONTENT_BACKEND | 固定 github；本批不交付新的本地内容引擎 |
| GITHUB_CONTENT_REPO / BRANCH / TOKEN | 正式内容仓库 owner/repo、分支及最小权限 token；token 不进浏览器、不带入 Git URL。不配置时警告，可登录/安排/写个人记录，正式课程、文章发布等模块降级 |
| GROW_REVISION / RENDER_GIT_COMMIT | 完整候选SHA。GROW_REVISION供备份识别；现有health.revision沿用RENDER_GIT_COMMIT字段，非Render部署启用push唤醒时也设置为同一SHA，供工作流核对部署版本 |
| RUNTIME_ROOT | 可写临时运行目录；任务进度和个人事实以 PG 为准，不能靠临时磁盘保留已确认数据 |
| LEARN_ROOT | 必填绝对路径，先由prepare_materials.py创建新的正式教材目录；白名单仅含英文每日文章、表达每日练习、思维工具教程，不带学习记录/复盘/个人计划。已有明确配置的旧根目录会提示继承旧状态风险，不删除原资料 |
| CLOUD_DEPLOY / WEB_CONCURRENCY / PORT | 本机 HTTP 使用0，HTTPS代理部署使用1 / 1 / 8756；不运行多副本，不使用 uvicorn --workers>1 |
| GROW_SCHEDULED_READING_ENABLED | 默认0。仅启用后台定时阅读，不改变用户原有阅读偏好 |
| GROW_PUBLIC_URL / GROW_SCHEDULE_REPOSITORY / GROW_SCHEDULE_REPOSITORY_ID / GROW_SCHEDULE_REF | 外部唤醒启用时必填：本部署 HTTPS origin、工作流仓库、数字仓库ID、refs/heads/main 等准确分支 |

Fernet 密钥可在受信任终端生成：`.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`，直接保存至秘密管理，不写入终端共享记录。密钥丢失不能靠备份包恢复自定义凭证。

受 Git 跟踪的旧配置示例曾有非占位数据库连接值。当前文件已占位化；历史凭证是否有效/已轮换，必须由持有者确认，未确认前保留为公开部署阻塞。本轮不访问该地址、不替用户轮换。

## HTTP 与运行边界

本地端口8756，HTTP 本机测试须 CLOUD_DEPLOY=0；CLOUD_DEPLOY=1 会强制 Secure Cookie，必须经 HTTPS 代理访问。公网需由 HTTPS 反向代理终止 TLS，转发 Host/协议且只信任受控代理；在受控网络绑定后端，防止直接绕过代理。认证 Cookie 在 HTTPS 请求使用 Secure，不能把 HTTP localhost 成功当作公网会话验收。/api/health 是存活和部分模块初始化状态；登录后的存储状态接口才展示具体模块错误，仍不等同实时完整就绪探针。公网放行前需完成后续 O01 诊断与实际 HTTPS 验证。

prepare_materials.py 只读原目录、拒绝链接和覆盖既有目标，生成教材文件哈希清单。新管理账号不继承仓库里的历史学习进度；旧实例若显式保留旧资料根目录，原兼容行为继续保留。

Render build会导出至/opt/render/project/src/.grow-public-materials；新实例将LEARN_ROOT显式设为此路径。已有实例先保留原LEARN_ROOT，核对/迁移仅存于旧文件的进度与记录后再切换；蓝图不自动改写该值。导出目标已存在时明确失败，确认是可重建发行副本后改用新目录，不能清理旧个人根目录绕过。

Dockerfile 仅复制同一正式教材白名单，构建上下文也排除历史个人资料与秘密，使用相同入口；构建时用 --build-arg GROW_REVISION=完整候选SHA 写入版本，部署时经受控 HTTPS 代理访问并配置原密钥/数据库。当前 Linux 镜像验收结果须查阅报告，文件存在不代表已通过构建。

内置正式教材随代码包恢复。PG 保留所有账号、隔离 schema、行动/执行事实、笔记、自由记录、文章元数据、草稿、发布日志；正式新增内容在 GitHub。浏览器未同步草稿及个人 AI 配置不在服务器备份内，行动草稿可在页面下载局部恢复副本。设置里的“局部记录副本”只涵盖旧版表单，不是全站备份。

## 定时阅读：双侧显式启用

服务端 GROW_SCHEDULED_READING_ENABLED=1；GitHub Actions 仓库 Variables 同时设置 GROW_SCHEDULED_READING_ENABLED=1 和 GROW_PUBLIC_URL。服务端填入该工作流仓库的数字 ID、owner/repo、ref。OIDC 只允许 GitHub 签发的 RS256、精确 audience/仓库 ID/仓库名/workflow/ref 与 schedule/workflow_dispatch/push；不授予其他 API 访问权。不配或关闭时不自动搜集、不回退请求旧站点。手动搜集和用户偏好沿用原行为。

## 完整备份（离线管理员命令）

1. 停止网页服务、所有副本、定时工作流和其他写入；等待进行中的生成/发布结束或记录其中断状态。备份命令要求 --writers-stopped 是操作者确认，不能自行证明远程写入已停止。
2. 为每个默认/自定义内容仓库准备最新 bare mirror。使用受管 Git 凭证助手，URL 不含 token：`git clone --mirror https://github.com/YOUR/CONTENT.git /safe/content.git`；已有镜像执行 `git --git-dir=/safe/content.git fetch --prune origin`。分支移动后不可达的待发布 commit 必须从原仓库另行 fetch 指定 SHA，脚本缺失版本即拒绝备份；不能只保留当前 main。
3. 使用原加密密钥、同一默认仓库/分支、专用数据库配置运行：

```sh
cd 知行成长/server
../../.venv/bin/python standalone_backup.py create /safe/backups/grow-20261022 \
  --writers-stopped --content-mirror YOUR/CONTENT=/safe/content.git
../../.venv/bin/python standalone_backup.py verify /safe/backups/grow-20261022
```

多个仓库重复 --content-mirror。脚本以只读一致性快照枚举所有账号 schema 和所有表，pg_dump custom 包含 schema、数据、序列与私有加密凭证；正式内容按绑定和 commit SHA 创建自包含 Git bundles，并给不可达引用添加本地保留 ref，不改远端。清单含代码SHA、PG版本、默认仓库、表行数与逐表内容摘要、正式版本、文件SHA256和加密密钥指纹，不含明文密钥或私人正文。文件600、目录700；包本身包含私有数据库，须额外用受管存储加密并限制访问。

建议每天备份，保留最近7个每日、4个每周和一次每次升级前的副本，至少一份放另一存储位置；先验证新包和定期恢复抽查后再按策略移除旧包。脚本不会自动清理旧备份。密钥、数据库/仓库认证、部署配置另行安全保管；不可只备份此清单。内置教材由 application_revision 对应代码包提供。

## 空库恢复、重启与升级回退

先校验备份，再新建空 PostgreSQL 数据库（由管理员创建，运行角色拥有），设置 DATABASE_URL 指向新库，使用相同加密密钥、内容绑定及兼容代码版本。停止全部写入；内容恢复目录必须不存在。

```sh
../../.venv/bin/python standalone_backup.py restore /safe/backups/grow-20261022 \
  --writers-stopped --content-directory /safe/recovered-content-20261022
../../.venv/bin/python deployment.py check
../../.venv/bin/python deployment.py serve --host 127.0.0.1 --port 8756
```

恢复前核对校验、密钥指纹、空库、默认仓库配置；Git bundle fsck 与全部引用可读后，pg_restore 单事务恢复，核对所有表行数与内容摘要。恢复使用当前目标角色，不恢复 PostgreSQL 集群角色/所有者/ACL；目标权限和 TLS 配置由安装者单独建立。已有非空库、重复恢复、已有内容目录一律拒绝覆盖。失败保留目标现场，改用另一个空库/新目录重试，原库不被删除或覆盖。

Git bundles 恢复为本地 bare 仓库，不自动推送、强推或替换绑定。原 GitHub 仓库仍可读时应用继续按原版本引用使用；仓库丢失时，先在受控恢复环境从 bundle 恢复原仓库及必要保留引用，并验证 API 可按 SHA 读取，再开放网页。更换仓库/分支需要独立的绑定迁移，不能把文件存在当作 GitHub 恢复成功。本地协议夹具仅验证相同接口与哈希，真实 GitHub 权限/限流/灾难恢复另列未验证。

升级前停写并备份，保留已验收的代码包及依赖锁。先在隔离副本升级；迁移失败不得清表绕过。不兼容非空旧结构会保留原数据并报告模块错误，需单独处理。回退时继续停写，用升级前备份恢复至另一空库，配套原候选代码与原密钥核对，再切流；不要在已产生新事实的升级库上直接降级或覆盖。升级后写入的数据需另行核对迁移，旧快照不会自动包含。

恢复后必须重新登录，确认邀请/租户隔离、check/time/content、事实/笔记/课程正文哈希、搜索、发布恢复和任务中断状态，再复测重启。原会话也在数据库备份中；涉及安全事件应由管理员撤销会话并轮换相关凭证。生成中断不自动重付费，正式发布仍本人确认。详见本批验收报告中的已测/未测清单。

## 隔离验收

需自己创建的一次性 localhost PostgreSQL，禁止连接业务库：

```sh
.venv/bin/python -m pip install -r 知行成长/server/requirements-test.txt
npm install --prefix /tmp/grow-web-test-node --no-save --package-lock=false playwright@1.64.0
# 安装本机 Chrome；其他平台按测试的 CHROME_EXECUTABLE 指定 Chrome 路径。
TEST_POSTGRES_DSN='host=127.0.0.1 port=YOUR_TEST_PORT user=YOUR_TEST_ROLE dbname=postgres' \
NODE_PATH=/tmp/grow-web-test-node/node_modules \
.venv/bin/python -B 知行成长/server/tests/run_web_regression.py --output /tmp/grow-web-regression
```

如需自建一次性测试PG，用普通非root用户执行（先将PostgreSQL15的bin加入PATH，不连接业务库）：

```sh
GROW_TEST_ROOT=$(mktemp -d /tmp/grow-web-pg.XXXXXX)
GROW_TEST_PORT=$(.venv/bin/python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
initdb -D "$GROW_TEST_ROOT/data" -U grow_web_test --auth=trust --no-locale --encoding=UTF8
pg_ctl -D "$GROW_TEST_ROOT/data" -l "$GROW_TEST_ROOT/postgres.log" \
  -o "-h 127.0.0.1 -p $GROW_TEST_PORT -c max_wal_size=64MB -c min_wal_size=32MB" start
export TEST_POSTGRES_DSN="host=127.0.0.1 port=$GROW_TEST_PORT user=grow_web_test dbname=postgres"
# 在同一shell运行上方runner命令（使用这个TEST_POSTGRES_DSN），完成后停止：
pg_ctl -D "$GROW_TEST_ROOT/data" -m fast stop
```

runner 按模块隔离；38项账号文件按三个既有测试类分别隔离，每类600秒看门狗，并核对整文件收集节点与分组节点的并集完全一致（无遗漏/重复/漂移）。这把原整文件300秒总时限改为各组600秒，浏览器单步时限不变。runner 自动开启浏览器用例，失败、跳过和阻止真实访问均使其失败；依赖独立 Zook 仓库的一个合同模块在清单明确列入延后连接集合。完整结果、命令与当前外部阻塞以验收报告为准，不能用历史报告替代当前候选。
