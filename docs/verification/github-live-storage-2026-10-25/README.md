# 真实 GitHub 仓库读写与课程保存核验

2026-10-25，最终更新的 Token 已通过 xiaohao19910303/zhixing 的 main 分支真实读写与课程保存验收。本机服务已重启加载新配置，连接及已有课程读取通过。

## 最终验收结果

| 验收项 | 结果 |
| --- | --- |
| 实际生效配置 | server/.env 的 GITHUB_CONTENT_TOKEN；默认仓库与已有规划绑定一致 |
| 仓库与分支读取 | 通过 |
| 创建规划草稿、采用规划、保存资料 | 全部返回 200 |
| 正式课程发布与读回 | 返回 200；正文哈希、参考资料链接一致 |
| 同 key 重复发布 | 返回同一 commit，分支未新增提交 |
| 写入日志 | 三项均为 done |
| 测试内容清理 | 8 个文件全部删除；最终仓库 Git 树与测试前完全一致 |
| 本机服务 | 预检通过；登录、连接测试、已有课程与资料读取、健康检查均为 200 |
| 运行模块 | 9 项均 ready；页面、4 项静态资源与3项业务读取接口均为 200 |

课程保存使用生产 API 处理函数和 GitHub 存储实现，真实写入目标仓库；本地数据库为一次性 localhost PostgreSQL，课程正文为人工构造的验收样本，未调用模型。远端仅使用随机 `_grow_verification/` 子目录，不覆盖已有课程，真实账号课程列表未新增测试规划。

最新一轮的 4 个验收及清理提交保留在 main 历史，没有 force push。清理后剩余测试文件为 0，专用 PostgreSQL 已停止。课程学习状态仍为 unknown，不能把存储链路通过等同于本人学完第一课；B2 真实学习验证继续待办。

## 配置与服务

ACCOUNT_ENCRYPTION_KEY 是加密账号凭据的固定 Fernet 密钥，不是 GitHub Token。早前误填已修正；本轮再次发现字段格式无效后，从本机仍在运行的本项目服务内存环境恢复原密钥，没有重新生成，也没有改变用户新填的 GitHub Token。当前密钥已配置好，应保持不变并安全备份。后续 GitHub Token 只更新 GITHUB_CONTENT_TOKEN。

.env 权限为 600，密钥、Token、Cookie 未写入证据或 Git。服务已重新加载当前配置，保持运行于 http://127.0.0.1:8000，仅监听本机。未发布远端应用，本次未修改应用代码，用户进行中的 CSS 与已有工作树未纳入提交。

## 历史失败与本轮修正

早期新 Token 放错配置字段，程序曾使用共享配置中的旧凭证完成课程写入；该轮脚本最初遗漏发布时自动追加的参考资料链接，修正复核后读回及幂等通过，8 个文件也已清理。结果保留在 [此前凭证证据](evidence/previous-credential/)，不作为当前 Token 的证明。

随后正确字段中的 Token 仍被 GitHub 拒绝写入。用户首次确认 Read and write 后，两轮独立请求依然在 POST git/trees 返回 403，普通 Contents PUT 也为 403。GET /user 确认账号归属正确，但目标仓库公开可读不足以证明 Token 写权限。[失败证据](evidence/after-permission-change/)仅作历史记录，已由最终通过结果取代。

用户再次更新 Token 后，首次只读请求出现临时网络中断；重试读取成功，继而完成上述真实写入、读回、幂等及清理。最终结果未使用旧凭证替代。

## 最终证据

- [配置来源、仓库及绑定读取](evidence/final/read-check.json)
- [课程保存、幂等及清理](evidence/final/course-check.json)
- [脱敏 GitHub 请求审计](evidence/final/http-audit.json)
- [服务重载后的连接及已有课程读取](evidence/final/service-check.json)
- [启动预检与接口检查](evidence/final/startup-check.json)
- [加密字段恢复及文件权限](evidence/final/configuration-check.json)

验收范围为本次配置、真实存储链路和服务启动专项；未以此替代全量回归、远端部署或 B 项真实使用验证。
