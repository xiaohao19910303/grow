# 真实 GitHub 仓库读写与课程保存核验

2026-10-25，目标为 xiaohao19910303/zhixing 的 main 分支。**新 Token 的读取通过，实际写入被 GitHub 拒绝，课程保存尚不能以新 Token 验收通过。**

## 当前 Token 结果

配置已从 .env 中实际加载，管理员使用默认仓库，与已有规划存储绑定一致。仓库元数据、分支 ref 和 commit 读取成功。本机服务重载后，登录、仓库连接测试、已有课程与参考资料读取以及健康检查均返回 200。

实际写入请求 POST git/trees 返回 403，GitHub 消息为 Resource not accessible by personal access token，响应明确列出需要 contents=write。API 限额仍有余量。fine-grained Token 的目标仓库授权及 Contents Read and write 需补齐。仅有仓库用户角色的 push=true 不能证明该 Token 获得写权限。

需在 GitHub Token 设置中确认 Repository access 包含此仓库，并把 Repository permissions 的 Contents 设为 Read and write，保存后重验。如果重新生成 Token，只更新本地 GITHUB_CONTENT_TOKEN。

## 配置位置修正

发现新 GitHub Token 曾误填到 ACCOUNT_ENCRYPTION_KEY，使服务重载预检失败。已把它移到 GITHUB_CONTENT_TOKEN。只读核对无已加密个人 GitHub 凭证后，按用户此前授权生成合法固定 Fernet 密钥并写入账号加密字段。其他配置保留，.env 权限 600，未在聊天、报告或 Git 中输出密钥。服务随后重新启动，当前保持运行于 http://127.0.0.1:8000。

ACCOUNT_ENCRYPTION_KEY 应保持固定并安全备份；其用途是加密账号凭证。GitHub 访问权限由 GITHUB_CONTENT_TOKEN 提供，后续权限调整不应覆盖账号加密字段。

## 先前凭证与课程链路

最初因新 Token 放错字段，程序实际加载了此前共享配置中的凭证。该凭证真实完成了规划采用、资料保存、课程发布，课程及参考资料读取 200，内容哈希与发布日志一致，双向链接正确；同 key 重放返回相同 commit 且分支不再前进。

首轮验收脚本遗漏发布时自动追加的参考资料链接，误报正文差异；复核按正式发布格式通过。失败记录和修正后的结果均保留在 evidence/previous-credential 中。这些成功结果不能代替新 Token 的写权限验证。

测试使用一次性 localhost PG 和仓库随机 _grow_verification 前缀，没有往真实账号课程列表增加测试规划。先前凭证测试的 8 个文件已经清理，清理后 Git 树与验收前完全相同；4 个真实验收／清理提交保留在仓库历史，不做 force push。新 Token 的课程采用返回 503，未在目标分支留下测试文件。权限诊断只尝试创建未引用 Git 树，返回 403，没有改动分支。两轮专用 PG 均已停止。

本次未调用模型、未覆盖已有课程、未发布远端应用。用户当前正在修改的 CSS 和已有工作树未纳入此次提交。

## 证据

- [新 Token 读取](evidence/read-check.json)
- [新 Token 课程接口结果](evidence/course-check.json)
- [GitHub 403 与所需权限](evidence/permission-diagnostic.json)
- [重载服务及已有课程读取](evidence/service-check.json)
- [此前凭证链路及清理](evidence/previous-credential/)

后续收到权限已调整的确认后，需重新跑实际写入、读回、同 key 重放及临时文件清理；目前不能把 B2 的真实学习或新凭证课程保存标为完成。
