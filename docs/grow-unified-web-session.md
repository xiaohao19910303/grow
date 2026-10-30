# Grow 与 LightTick 统一网页登录

2026-10-30。C05复用Zook唯一公共登录、refresh、logout及记录／行动合同。默认关闭；部署需显式配置`GROW_ZOOK_WEB_AUTH_ENABLED=1`、有效`LIGHTTICK_BRIDGE_URL`和既有`ACCOUNT_ENCRYPTION_KEY`。HTTPS用于实际服务，localhost HTTP仅测试。

已有Grow用户先按原方式登录，在设置中填写自己的LightTick账号密码，并明确确认关联。服务核验正式membership、两边身份及已有数据目标一致，保存一对一身份映射；同名不合并，没有映射的LightTick登录不能自动打开旧空间。此操作不迁移记录或扩大课程授权。

完成关联后可在登录页选择“LightTick账号”。Grow同源BFF只给浏览器HttpOnly／SameSite随机句柄，access及refresh以既有Fernet密钥加密保存服务端；浏览器响应、URL及localStorage没有Token。每次请求核验会员，必要时串行续期；新refresh先持久化再做后续远程查询。服务地址改变、凭据撤销或映射变化均拒绝，不退回旧Grow Cookie。

迁入记录及行动网页请求使用当前本人Token和严格路由白名单。记录历史通过公共`GET /records/{id}/history`读取，原始历史与来源状态仍归各原协议；可信来源bridge继续只做已授权同步和接管，不替代网页Token。统一身份关联后，新的接管目标也必须相同，不能先迁往另一账号再事后报错。

退出调用Zook正规撤销；access过期时先安全续期再撤销当前refresh，随后清理本地会话。上游暂不可用时明确退出未确认并允许重试，不假称已完成。切换回原Grow登录会关闭旧BFF会话，迁入数据仍要求统一账号，不恢复第二写入方。

实际个人账号关联／历史接管及正式部署需在本人可见的登录界面完成；工程验收仅使用合成身份、真实公共HTTP处理器与一次性PostgreSQL，不能代替个人长期使用证据。
