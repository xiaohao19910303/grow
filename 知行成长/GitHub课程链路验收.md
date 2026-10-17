# GitHub 课程链路验收

日期：2026-10-17。范围：新学习计划试点；不代表所有旧模块均已完成云端迁移。

## 入口与存储

- [线上学习计划](https://zhixingchengzhang.onrender.com/#plans/)，使用浏览器登录框；用户名默认 `owner`，密码取服务端 `APP_PASSWORD`。
- 内容仓库：`xiaohao19910303/zhixing`，分支 `main`。
- 正式规划、备课资料、正文、参考资料和课程目录通过 GitHub API 直接提交。
- PostgreSQL 保存生成任务、草稿、发布日志、版本映射和个人反馈。
- 新计划不依赖 Render 持久磁盘；正文与资料按发布时的 commit SHA 读取。

## 本次真实结果

- 计划：**证据与判断：从观察到结论**，编号 `plan-20261017-001`；1 周、每周 2 次、每次不超过 15 分钟，含一次复盘。
- 使用线上实际配置的 `qwen3.7-plus`，经线上 `/api/plans/generate` 分别生成规划和首课；不是模拟模型。
- 首课：**事实、解释与判断的界定**。采用原创备课摘要；教学例子均为假设，未提交个人笔记。
- 发布前审阅并修改章节标题、假设标注、退货率起止数值与判断标准表述；保留原生成草稿及修订关系。
- 规划提交：`6c9a6fc8ff905934a34c9e8f2ba4f94c8a18e474`。
- 首课提交：`19e439d391c536f141b916b8c3e51c0fd3f3f4d2`；正文、参考资料和课程目录在同一次提交中更新。
- [GitHub 首课原文](https://github.com/xiaohao19910303/zhixing/blob/19e439d391c536f141b916b8c3e51c0fd3f3f4d2/%E5%AD%A6%E4%B9%A0%E8%AE%A1%E5%88%92/plan-20261017-001/%E6%AF%8F%E6%97%A5%E8%AF%BE%E7%A8%8B/2026-10-17-%E7%AC%AC001%E8%AF%BE-%E4%BA%8B%E5%AE%9E-%E8%A7%A3%E9%87%8A%E4%B8%8E%E5%88%A4%E6%96%AD%E7%9A%84%E7%95%8C%E5%AE%9A.md)。
- GitHub 文件与线上阅读接口逐字一致，正文 SHA-256：`c93990a9f4665e27aac73221ab9493836239625e798923c69feb5dccde807a77`，资料 SHA-256：`444a0fa0bc9350a9743af3509f0a11f78450cdf4bb4dcb19e102c1d7f433df72`。
- 真实 Chromium 已完成：进入计划 → 阅读首课 → 展开参考资料 → 点击 GitHub 原文（HTTP 200）→ 重新进入课程并核对正文一致。
- 浏览器无 JavaScript 错误；学习计划相关请求未失败。
- 发布日志 3 项均完成，未遗留待恢复任务。首课状态仍为“待本人反馈”，未替用户标记学完。
- 健康接口返回 `plan_storage=github`、`learning_plans_ready=true`；匿名首页返回 401，认证首页返回 200。

## 边界与后续运维

- 旧 `/api/data` 返回 500，旧课程今日任务和日常记录接口返回 503；旧模块尚有 PostgreSQL 兼容问题，另行迁移。
- 本次沿用已配置且技术验证可调用的 Coding Plan 接口。[阿里云官方说明](https://help.aliyun.com/zh/model-studio/coding-plan-faq)将其限定用于编程工具；长期后台运行应替换为通用 API Key、匹配地区的完整 `chat/completions` 地址及可用模型。
- 生成过程不会自动重试；部署重启会中断未完成生成，因此应等待任务结束后部署。已发布课程不受生成任务中断影响。
- 重启复验方式：确认 `/api/health` 的 revision 为目标提交，再读本计划第 1 课，核对其 commit SHA 与上述正文、资料哈希；浏览器再次从学习计划进入阅读。
- 内容仓库当前公开，教学内容公开；反馈只保存到数据库。仍需分别备份 GitHub 仓库与 Supabase。
