# 第一批证据索引

- `verified-final/results.json`及同目录日志：冻结代码a9c72ae的最终完整网页集合，539项Python、22份JS，0失败、0跳过。`final-summary.json`为核对摘要。
- `full-final/`：较早完整轮次535项Python，账号首次提交失败，非当前通过证据。
- `*-cancellation.json`：被新候选替代的中止运行，不计通过。
- `browser-repair/cold-contract-final-red/`与`green/`：仅在测试HTTP响应中回放旧前端的冷启动故障复现与修复验证；摘要中的早期PG超时已由最终完整集合覆盖。
- `materials-red/`与`materials-final/`：发行教材排除个人历史资料的先失败后通过证据。
- `w01/`：合成账号的存储失败恢复提示及检查记录。
- `linux-build.log`、`final-environment-checks.json`：Docker不可用，Linux运行未验证；后者同时保留一次错误目录执行manage.sh的失败与正确路径重验通过。
- `linux-wheels-*.json`：Python3.12两种Linux架构各48份锁定wheel的可获取性及哈希，未安装运行。
- `openspec-validate.json`：严格规格校验通过。

日志使用合成数据；不包含业务PG备份、Fernet密钥或真实服务凭证。未同步浏览器数据不在服务器备份范围。
