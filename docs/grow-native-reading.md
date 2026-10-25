# Grow 手机原生阅读（2026-10-25）

H5 制订、完善、发布计划，保留私人笔记、作答、学完确认；手机查看计划、原生阅读已发布课程、记录和执行行动。阅读位置先保存在当前设备，I4 单独授权后可显式同步，不等于学完，不改变三种行动的完成规则。

手机新安装直接进入本机空间，可以阅读两篇随包体验课，使用本机记录、目标和计时。连接私人课程时才登录 Zook、生成连接码。在 Grow 联动设置中验证连接码、核对目标账号、单独勾选课程正文阅读范围并连接。已有行动连接也需要单独允许课程阅读。只读课程连接不要求移交行动、清空或迁移节律数据。

课程范围为英文阅读 Materials 和正式计划已发布的正文及参考资料，不包含未发布生成稿、私人笔记和答案。服务端依赖现有可信租户上下文，禁止提交任意用户编号。课程连接使用现有签名桥接、一次性连接码和所属成员校验，独立存储课程镜像。

配置沿用 `GROW_PUBLIC_URL`、`LIGHTTICK_BRIDGE_URL`、`GROW_ACTION_BRIDGE_SECRET` 及 Zook 的两级行动开关；生产默认配置不在本轮启用。后台来源 worker 同步有界课程目录，持久化待发送内容、版本和回执；失败重发同一内容，不冒充已同步。最多 200 篇、每篇正文/参考各 100000 字符、整批 4 MiB，超过范围明确报错，后续可再分页。

手机按账户及服务地址隔离缓存，最多 20 篇正文 / 6 MiB；读过的同版本课程保留段落位置。版本变化提示重新从首段核对，原文更名和来源状态可独立刷新。服务可用时撤回授权、删除课程、换绑会清理对应私人正文和位置；离线设备需联网获知撤回。公开体验课位置保留。用户可清理本机缓存，不改变 H5 状态。

Android 原生显示段落、标题和参考文本；iOS 支持部分行内 Markdown。复杂图片、表格等可打开 H5 原文；H5 登录到期仍保留经过白名单校验的课程路径。I4 已支持单独授权的跨设备位置、手机笔记/作答与显式学完，详情见下文。

验收采用合成用户、独立 PostgreSQL、SE 模拟器和 360dp Android 模拟器；真实设备、读屏和自然后台通知另行验收。未部署生产，未迁移私人数据。

## I4 private learning
Private notes, answers, explicit completion and saved positions use separate consent in Grow's mobile settings. Grow remains their sole writer; H5 routes keep using the same records. Zook holds authorized snapshots and durable commands. Phone acceptance is pending until the source worker commits and returns an immutable receipt; no fake completion or learning time is created. Source CAS rejects concurrent H5 edits; the phone retains input for comparison. Old answers retain their course version and are not automatically assigned to new questions. Unknown legacy completion timestamps remain null.

The existing 30-second source worker processes bounded pending commands; source outage keeps them pending. Revoking reading also revokes private learning; enabling reading again does not regrant private scope. Revocation clears online mirror/queue access while source personal records remain intact. Offline user drafts require device cleanup. This implementation does not migrate personal data or switch H5 to a second writer.
