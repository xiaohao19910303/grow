# 知行成长 - 云端应用

## 🌐 在线访问

**应用地址**: https://zhixingchengzhang.onrender.com

随时随地通过浏览器访问，无需安装任何软件。

## 📱 快速开始

### 1. 打开应用
在任何设备的浏览器中访问上面的网址

### 2. 开始使用
- 查看学习任务
- 记录学习进度
- 查看知识图谱
- 管理个人成长

### 3. 添加到主屏幕（推荐）
**iPhone**: Safari → 分享 → 添加到主屏幕  
**Android**: Chrome → 菜单 → 添加到主屏幕

## ✨ 功能特性

- 📚 **学习管理** - 追踪每日学习任务
- 📝 **反思笔记** - 记录学习心得
- 📊 **知识图谱** - 可视化知识结构
- 📈 **成长追踪** - 记录习惯和打卡
- 💹 **股票复盘** - 投资学习和记录
- 📖 **阅读记录** - 管理阅读进度

## 🔧 技术栈

- **后端**: FastAPI (Python)
- **数据库**: PostgreSQL (Supabase)
- **部署**: Render.com
- **前端**: HTML5 + CSS3 + JavaScript

## 📂 项目结构

```
知行成长/
├── server/              # 后端代码
│   ├── app.py          # 主应用
│   ├── db.py           # 数据库层
│   ├── requirements.txt # 依赖
│   └── ...             # 其他模块
├── render.yaml         # Render 配置
├── Procfile            # 进程配置
└── README.md           # 本文件
```

## 💻 本地开发

如果需要本地开发：

```bash
# 1. 克隆仓库
git clone https://github.com/你的用户名/知行成长.git
cd 知行成长

# 2. 安装依赖
cd server
pip install -r requirements.txt

# 3. 启动服务器
python3 app.py

# 4. 访问 http://localhost:8000
```

## 🔄 自动部署

代码推送到 GitHub 后，Render 会自动重新部署：

```bash
git add .
git commit -m "更新说明"
git push
# 等待 2-3 分钟，应用自动更新
```

## GitHub 课程存储试点：新学习计划

`PLAN_CONTENT_BACKEND=github` 时，新学习计划直接通过 GitHub API 发布和读取 Markdown。
Render 不克隆内容仓库，不把正式课程、锁文件或发布恢复日志保存在本机磁盘。
生成输出、草稿、发布日志和个人反馈存入 PostgreSQL；正式规划、备课资料、课程正文和参考资料进入 GitHub。
日常记录在 GitHub 模式下仅保存到 PostgreSQL，不写临时文件或公开仓库。旧认知课程与阅读收藏的文件发布尚未迁移，云端明确暂停这些入口；英文、表达的既有打包资料仍为历史只读资料。

### 首次配置

本次已确定内容仓库为 `xiaohao19910303/zhixing`，目标分支为 `main`，已写入部署配置。该仓库目前可公开访问，提交的教学内容会公开；个人反馈仍只存数据库。

1. 使用已确定的内容仓库。空仓库会在首次正式发布时通过 Contents API 创建 README，再提交规划；生成草稿与阅读请求不会初始化仓库。若目标分支与空仓库的默认分支不同，须先在 GitHub 建立目标分支。需要私密课程时，先将仓库设置为私有。
2. 创建仅授权该内容仓库的 fine-grained Token，授予 **Contents: Read and write**。目标分支应允许该凭证直接提交；要求 PR 的保护规则会阻止直接发布。不要授予 Workflows 权限。
3. 在 Render 的 Environment 中配置仓库根目录 [.env.github.example](../.env.github.example) 所列变量。GitHub Token、数据库连接串、登录密码只写入服务端密钥配置，不写入 Git 或聊天。用户 AI 配置在浏览器设置页填写。
4. `GITHUB_CONTENT_REPO` 使用 `账号/仓库`，`GITHUB_CONTENT_BRANCH` 默认 `main`。`DATABASE_URL` 使用 Supabase Connect → Session pooler 的完整连接串（端口 5432），以兼容 Render 的 IPv4 网络。AI 配置仅保存在当前站点的浏览器 localStorage；Base URL 可填写 `/v1` 等兼容接口根地址或完整 `/chat/completions` 地址。每次生成必须携带用户自己的三项配置，不回退读取服务端 `QWEN_*` 或数据库配置。
5. `APP_PASSWORD` 至少 24 位，`APP_USERNAME` 默认 `owner`。公网浏览器首次打开时使用浏览器登录框认证；健康检查 `/api/health` 保持公开。仅经 HTTPS 访问。
6. 使用根目录 `render.yaml` 的构建和启动命令；无需配置持久磁盘。使用**一个实例、一个 Uvicorn worker**，生成任务中断后需显式重新生成，不会自动重复调用模型。

通用百炼接口可配置为 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`，并使用对应地区的通用 API Key 和可用模型。Coding Plan 专用密钥与通用 API Key 不能混用；[官方说明](https://help.aliyun.com/zh/model-studio/coding-plan-faq)将 Coding Plan 限定用于编程工具，长期运行的应用后台应使用通用 API。

启动时会清理数据库中旧的 AI 配置字段（保留超时等运行设置），不会将旧密钥返回浏览器。用户需在「设置与数据」重新填写自己的 Base URL、API Key、模型名称；换浏览器需重新配置。连接测试不自动保存配置，清除本地配置后不能再发起生成。

启动时会增量创建学习计划表，并绑定内容仓库和分支。已有绑定后不能直接换仓库或分支；先做显式数据迁移。
若数据库已有旧本地计划，其文件不会自动上传：本轮先新建一套计划验收，历史课程仍需另行迁移。
同一数据库不要同时运行 local 与 github 模式的写入服务。

### 使用与验收

2026-10-17 已完成真实规划、首课生成、GitHub 发布与浏览器阅读，见 [本次验收记录](GitHub课程链路验收.md)。

1. 登录网页，进入「学习计划」，创建一套计划，使用 AI 生成规划并预览，确认采用。
2. 准备第一课资料，生成课程，预览正文和资料后点击「保存正式课程」。
3. 确认页面提示「已提交 GitHub」；内容仓库同一次提交中应包含课程正文、参考资料与更新的课程目录。
4. 点击课程「阅读」，查看正文、展开参考资料，再点击「在 GitHub 打开课程」查看同一提交的原文。
5. 重新部署 Render 后再次阅读。课程由 GitHub 读取，草稿和任务由数据库恢复，不依赖旧实例文件。
6. 填写本课反馈后，确认进度更新；个人反馈只进数据库，不会提交到内容仓库。

每次发布先保存数据库日志，再创建 Git tree 和 commit，最后以 `force=false` 更新分支。
提交成功后才在同一数据库事务中登记课次及发布版本。网络响应丢失或数据库补登记失败，可在列表点击「检查未完成保存」恢复；重试会识别已完成的提交，不重复发布。
分支发生无关变更可以安全重试；目标文件、规划或备课资料被外部修改时停止覆盖，保留任务供人工核对。
GitHub 不可用时，未缓存的正文暂不可读，页面会显示错误；已有数据库记录与草稿不会因此删除。

课程正文和参考资料按发布时的 commit SHA 读取，并做有界内存缓存。后续在 GitHub 直接修改不会静默改变已发布版本；第一阶段请通过平台修订规划，历史正文的外部修订导入留待后续。
原始 Markdown 的相对链接在 GitHub 可正常使用，平台内参考资料使用独立展开区和 GitHub 入口。
平台不会向浏览器发送仓库 Token；私有仓库的 GitHub 原文页面需要浏览器另行登录 GitHub。

### 备份与故障边界

Git 历史覆盖课程文件，Supabase 备份覆盖草稿、任务、索引、反馈和仓库版本映射，两者都需要保留。
GitHub 模式不支持原本的本地「完整学习备份」按钮，避免把临时文件误当成完整备份。
课程已提交成功后，撤销发布应使用新的修订提交，不能强制回退内容分支。
旧代码曾将数据库凭证写入配置；切换前应轮换已暴露的凭证，`render.yaml` 已改为服务端输入。

### 开发验证

Python 3.11+，安装根目录 requirements 后执行（测试不访问真实 GitHub 或模型）：

```bash
PYTHONPATH=知行成长/server python -m unittest discover -s 知行成长/server/tests -p 'test_github_plans.py' -v
PYTHONPATH=知行成长/server python -m unittest discover -s 知行成长/server/tests -p 'test_cloud_auth.py' -v
node 知行成长/server/tests/test_plan_observer.cjs
# 可选：安装 playwright 后运行真实浏览器流程
RUN_GITHUB_BROWSER=1 PYTHONPATH=知行成长/server python -m unittest discover -s 知行成长/server/tests -p 'test_github_browser.py' -v
```

设置 `TEST_GITHUB_PG_DSN` 为专用本地 PostgreSQL 的 DSN，可对同一组场景额外运行真实 PostgreSQL 事务和并发锁验证；测试拒绝非 localhost 数据库并为每例创建独立 schema。
`test_github_cloud_app.py` 另外覆盖真实 app 启动、登录中间件与发布阅读接口；`test_github_browser.py` 使用真实 Chromium 和实际前端脚本，GitHub 与 AI 均为 HTTP/流式模拟服务。
2026-10-17 验证覆盖新计划链路、故障恢复、并发、空仓库和旧本地发布兼容。旧全量测试目前还受基线 `server/plans/backup.py:201` 的语法错误阻塞；旧模块也有未完成的 PostgreSQL SQL 迁移。本试点隔离旧模块初始化失败，使新学习计划可独立启动，不宣称已修复整个平台。
GitHub 接口依据：[Contents](https://docs.github.com/en/rest/repos/contents)、[Trees](https://docs.github.com/en/rest/git/trees)、[Commits](https://docs.github.com/en/rest/git/commits)、[References](https://docs.github.com/en/rest/git/refs)。

## 📊 状态监控

- **应用状态**: 查看 Render 控制台
- **数据库状态**: 查看 Supabase 控制台
- **日志查看**: Render → Logs

## 🐛 问题反馈

如遇问题：
1. 检查应用状态（是否休眠）
2. 查看日志信息
3. 验证数据库连接

## 📄 许可证

私人项目，仅供个人使用。

---

**部署时间**: 2026-10-16  
**版本**: v1.0  
**状态**: ✅ 运行中

当前改动的迁移边界与隔离验收见 [浏览器 AI 配置与云端存储验收](浏览器AI配置与云端存储验收.md)。
