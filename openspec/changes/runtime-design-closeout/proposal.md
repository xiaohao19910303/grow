## Why

新目录的 Python 已重建，但真实启动配置与教材目录尚未验收；页面的待提交设计变量仍与内联 root 重复。本轮完成可复验的运行检查及样式收尾，保留原业务密钥和数据。

## What Changes

- 为预检新增显式离线模式，复用主预检；serve 不允许跳过数据库检查。
- 导出不含个人状态的教材白名单到新目录，核对解释器、锁定依赖、目录与启动重启链路。
- 将网页设计变量收敛到已存在的 design-tokens.css，保持旧变量兼容，改善受影响的状态文字对比度、键盘焦点和减少动态效果。
- 真实配置缺失作为独立阻塞记录，使用一次性 PG 与合成账号验收，不创建或替换真实密钥。

## Capabilities

### New Capabilities
- `runtime-design-closeout`: 运行预检与设计变量收尾。

### Modified Capabilities

## Impact

Grow 私有部署 CLI、管理脚本、静态样式、测试夹具与文档；不修改业务状态机、LightTick／Zook 合同或自动任务开关。
