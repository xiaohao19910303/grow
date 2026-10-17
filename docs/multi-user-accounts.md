# 多用户账号与个人 GitHub 存储

## 目标与验收

- 仅限邀请注册，使用用户名和密码登录、退出。密码使用 scrypt，服务端仅存会话摘要，Cookie 为 HttpOnly、SameSite=Lax，云端强制 Secure。登录注册限速，同源校验覆盖所有写接口。
- 原 APP_USERNAME / APP_PASSWORD 初始化原管理账号，保留原数据库及文件。注册永远不能认领该账号或旧数据。
- 新用户使用服务器生成的独立 PostgreSQL schema；所有业务连接只搜索该 schema，不回退 public。各模块、后台生成任务及文件目录按用户隔离。
- 新用户默认沿用服务端 GitHub 配置，在 `用户/<用户ID>/学习计划/` 下发布；原账号沿用原目录。数据库记录和个人反馈不会写入 GitHub。公开仓库中的教学内容仍公开。
- 设置页可测试并保存自己的仓库、分支和 Token，也可恢复默认。Token 经 Fernet 加密，只在服务端解密使用，接口不回传。发布后锁定目标仓库及分支，允许更新 Token；更换目标需显式迁移，不能使旧课程失联。
- AI 浏览器配置按登录账号分开，切换账号不会沿用其他账号的 Key；旧配置仅迁入原管理账号。

## 技术方案与顺序

1. `server/accounts.py` 管理账号、会话、限流和存储配置；`server/tenancy.py` 提供请求上下文和各模块独立实例。
2. `db.connect()` 设置可信服务端 schema；API 模块通过 scoped 工厂获取当前用户实例，异步任务继承上下文。新用户不扫描原工作区、不导入原同步文件。
3. 外层认证中间件保护业务接口和首页；登录页、受邀注册接口、静态资源和健康检查公开。注册接口必须额外校验一次性邀请，匿名用户不能创建邀请。过期会话跳回登录页。
4. 添加登录注册 UI、账号菜单和 GitHub 设置；最后验证真实数据库、多账号 API 和 Chromium 流程。

## 项目约定

沿用 FastAPI、原生 JavaScript 和 unittest，无前端构建。SQL 参数化，JSON 字段和类命名沿用现有模块。例如 `conn.execute('SELECT id FROM auth_users WHERE username=?', (username,))`。

始终保留现有工作区修改，不提交密钥，不修改生产数据库。新增数据库表和凭证存储属于本需求授权范围；部署、删除数据和迁移正式课程不在本次自动操作范围。

## 验证命令

```sh
PYTHONPATH=知行成长/server python3 -m unittest discover -s 知行成长/server/tests -p 'test_accounts.py' -v
PYTHONPATH=知行成长/server python3 -m unittest discover -s 知行成长/server/tests -p 'test_github_plans.py' -v
PYTHONPATH=知行成长/server python3 -m unittest discover -s 知行成长/server/tests -p 'test_browser_ai_config.py' -v
node 知行成长/server/tests/test_plan_observer.cjs
```

账号集成测试使用 `TEST_ACCOUNTS_PG_DSN` 指向专用 localhost PostgreSQL，仅在随机测试 schema 中操作；GitHub 和模型使用模拟服务。浏览器检查注册、错误提示、退出、重新登录、账号隔离、GitHub 设置及窄屏布局。

## 2026-10-17 验收

- 48 项账号、GitHub 发布、PostgreSQL 事务、原账号兼容、AI 配置和生成响应回归测试通过；另加的共享仓库同课号隔离、schema 缺表不回退两项通过。
- 真实 Chrome 完整流程通过：注册时密码不一致提示、注册登录、待办持久化、个人 GitHub 测试与保存、退出重登、两账号数据和浏览器 AI Key 隔离、旧标签页阻止写入新账号、390px 手机布局。未出现 JavaScript 运行异常。
- 原有 GitHub 学习计划浏览器生成、发布和重载阅读流程通过；原单人数据由管理账号继续读取。
- 加密密钥丢失时仍可登录和进入设置，重新填写 Token 可修复。发布或生成进行中拒绝改配置；更换 Token 保留正式课程绑定。
- 原项目的课程观察器和全量状态客户端检查通过，Python 编译、JavaScript 语法及差异空白检查通过。
- 本地测试未访问生产数据库、真实 GitHub 仓库或真实模型，代码尚未部署。部署时需设置 `ACCOUNT_ENCRYPTION_KEY`，数据库角色需有 CREATE SCHEMA 权限。

实现依据：[PostgreSQL schema 与 search_path](https://www.postgresql.org/docs/15/ddl-schemas.html)、[Fernet](https://cryptography.io/en/latest/fernet/)、[Starlette Cookie 设置](https://www.starlette.dev/responses/)。


## 邀请制注册（2026-10-17 更新）

- 普通登录页不提供直接注册入口。管理账号由服务端 APP_USERNAME / APP_PASSWORD 初始化，所有已有账号仍可登录。
- 任一已登录用户可以在「设置与数据 → 邀请其他人」生成一次性邀请链接，复制后自行发送给受邀人。新账号注册后也可邀请其他人。
- 链接通过 URL fragment 携带高熵 Token，服务端只保存 SHA-256 摘要。每个链接限一人使用、7 天有效，每人最多保留 20 个有效链接。接口仅返回本人邀请的状态，明文链接仅在创建时返回。
- 无邀请、伪造、过期、撤销或已使用的邀请均不能注册，即使直接请求 API 也会拒绝。受邀注册使用行锁，并在同一事务内创建账号、独立 schema 和核销邀请，防止并发重复使用。
- 邀请人可以撤销自己的未使用邀请；不能撤销他人的邀请，也不能借撤销邀请删除已注册账号。用户名重复或校验失败不消耗邀请。

验收：54 项账号、邀请与既有 GitHub/AI 回归测试通过，覆盖匿名禁止邀请、无邀请禁止注册、一次性使用、到期、撤销、邀请权限、用户名冲突不消耗邀请、有效邀请数量限制和并发核销。真实 Chrome 验证原账号生成邀请、受邀注册、受邀用户继续邀请、退出重登、手机撤销邀请及原有数据隔离流程通过。此次代码仍未部署。


## 上线前数据保护与兼容验证

本次发布从最新 origin/main 建立独立分支，只包含账号、邀请和必要的现有功能兼容修改。原工作区未提交的语言、翻译及本地数据库改动不打包上线。

- 生产数据库维持原连接，管理账号沿用原 APP_USERNAME / APP_PASSWORD，在原 public schema 内继续读取已有记录。
- 配置唯一新增的 ACCOUNT_ENCRYPTION_KEY，保留已有环境变量。部署前对全部应用表生成 SHA-256 行清单并保存 PostgreSQL custom-format 备份；恢复演练只在 localhost 临时数据库执行。
- 原管理账号登录复用启动时的服务实例，避免再次初始化而中断正在运行的任务。
- 已有每日阅读 GitHub OIDC 仅允许访问原定时搜集端点，映射到原管理账号；不能凭该凭证登录、邀请用户或读取其他业务接口。普通用户不能触发原管理账号的定时搜集。
- 已发布的认知课程、阅读资料与学习计划均锁定仓库及分支；迁移前不能切换到不同仓库。已有生成或搜集任务运行时也不能更换配置。
- 回退时在 Render 重新部署原版本，仅回退应用代码，不删除新建账号表或 schema，不覆盖生产学习数据。
