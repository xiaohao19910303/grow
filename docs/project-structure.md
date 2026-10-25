# 仓库结构与维护约定

本仓库同时保存网页应用、学习源资料和工程文档。FastAPI 负责接口与静态页面，PostgreSQL 保存账号与个人记录，GitHub 保存正式发布内容。结构整理包括历史文档归档，以及将应用入口中的知识扫描、节点持久化和成长报告计算移入独立模块；接口、部署入口、资源 URL 和数据路径保持不变。

| 路径 | 职责 |
| --- | --- |
| `知行成长/server/app.py` | FastAPI 应用、静态资源挂载与路由组装 |
| `知行成长/server/deployment.py` | 部署预检、环境配置与前台服务启动 |
| `知行成长/server/knowledge/scanning.py` | Markdown 索引、思维工具和学习足迹解析；显式传入已解析的账号资料根目录 |
| `知行成长/server/knowledge/catalog.py` | 扫描节点的增量写入与分类读取；通过调用方传入的连接工厂保留账号隔离 |
| `知行成长/server/growth_reports.py` | 周月报与连续活动天数计算；复用 `growth_statistics.py` 的统计口径 |
| `知行成长/server/static/theme.js` | 主题偏好读取、切换与系统主题监听；存储失败时保留页面可用性 |
| `知行成长/server/static/` | HTML、CSS、JavaScript 与浏览器资源 |
| `知行成长/server/{plans,reading,rhythm,copilot,...}/` | 按业务域组织的接口、服务与存储 |
| `知行成长/server/*.py` | 现有共享基础设施、跨域服务与兼容模块；仍保留原导入路径 |
| `知行成长/server/tests/` | 隔离测试、浏览器回归和夹具 |
| `知行成长/server/tools/` | 服务端运维与诊断工具 |
| `知行成长/docs/` | 应用功能规则、设计及实施说明 |
| `知行成长/docs/archive/` | 历史交付、测试、性能与体验报告，见[索引](../知行成长/docs/archive/README.md) |
| `docs/deployment/` | 当前独立部署与恢复操作 |
| `docs/verification/` | 按批次保存的验收报告与证据 |
| `docs/` 中其他说明 | App、账户、阅读和跨端集成 |
| `scripts/` | 仓库级任务脚本 |
| `openspec/` | 规格与变更记录 |
| 根目录中文学习模块 | 学习源资料与个人学习记录 |
| `知行成长/学习资料/` | 默认运行时课程读取目录与打包教学资料 |
| `知行成长/v1-legacy/` | 旧版本迁移来源 |
| 根目录部署与依赖文件 | Docker、Render、进程配置与锁定依赖的唯一现有部署位置 |

## 运行与测试入口

从仓库根目录运行 `make help` 查看入口；`make start`、`make stop`、`make status`、`make logs` 转交现有应用管理脚本。它们沿用现有配置和服务管理规则。安装与配置先按[部署手册](deployment/standalone-web.md)完成。

`make test` 使用根目录 `.venv/bin/python` 调用现有完整隔离回归；可用 `PYTHON=/absolute/path/to/python` 覆盖。完整回归需要专用临时 PostgreSQL、Zook 合同夹具及浏览器，配置见[测试说明](../知行成长/server/tests/README.md)。

`make test-module PATTERN=test_packaged_materials.py` 用于单模块诊断，不替代完整回归。直接运行旧入口和 `make -C 知行成长 ...` 仍然可用。

## 应用入口与业务模块

`app.py` 保留应用创建、路由组装、生命周期和账号准备流程。知识扫描与报告的原函数名继续作为兼容入口，分别转交知识模块和 `growth_reports.py`。原来的 `app.get_conn`、`app.scan_markdown` 测试替换点继续生效。

提取后的业务模块不导入 `app`。资料根目录在兼容入口调用时经过 `learning_root` 解析；数据库连接工厂同样在调用时传入，避免模块导入时固定到某个账号。SQL、排序、节点去重规则、统计字段及时间口径沿用原实现。

本轮重构与验证记录见[代码结构回归报告](verification/code-structure-2026-10-25/README.md)。

## 路径与后续维护

- 新的应用功能文档放在 `知行成长/docs/`；跨端、部署与批次验收分别放在根 `docs/` 对应目录。历史交付报告归入 `知行成长/docs/archive/`，并更新索引。
- 根目录学习模块与应用内 `学习资料/` 承担不同读取和备份职责，不能依据名称相同就合并或删除。`LEARN_ROOT` 默认由应用位置推导，Docker 也按现有路径复制课程。
- `plans/backup.py` 的 `ROOTS`、`ROOT_DOCUMENTS` 和 `PLATFORM_DOCUMENTS` 是版本化备份契约。包括 P0 文档、学习总览在内的已登记路径保持原位。
- `学习仪表盘` 是已有兼容符号链接。旧脚本、Python 导入、静态文件引用及迁移来源路径保持有效。
- 不在整理目录时移动数据库、运行目录、环境配置、个人记录或历史验收证据。虚拟环境、工作树和缓存作为本地产物忽略。
- 未来拆分顶层业务模块时，应逐个业务域迁移，并验证 Python 导入、测试中的补丁目标及启动入口；不能只移动文件再批量替换名称。
