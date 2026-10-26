## ADDED Requirements

### Requirement: SRC-01 只使用三路本人确认的课程完成证据

系统 SHALL 在可信账号内只读接入认知第一轮、英语/表达、新学习计划三路课程完成记录。认知课程 MUST 存在未归档的 `copilot_learning_records`；英语/表达 MUST 存在 `study_learning_records`；新计划 MUST 存在计划、已发布课程和 `state=completed` 的 `learning_feedback`。生成、打开、时长、打卡或行动完成 MUST NOT 替代课程完成证据；复习功能 MUST NOT 修改原完成记录或个人笔记。

#### Scenario: SRC-01a 三路课程均有明确完成记录
- **WHEN** 同一账号分别完成认知课程、英语课程、表达课程和一个新计划课程并打开候选入口
- **THEN** 对应来源分别列出这些课程及可追溯的完成证据，保留真实来源时间，不生成评分或改变原记录

#### Scenario: SRC-01b 只有生成或阅读行为
- **WHEN** 课程仅已生成、打开或达到停留阈值，或者个人记录仍为待本人反馈
- **THEN** 系统不将其作为可加入复习的已完成课程，也不补写已学习或掌握状态

#### Scenario: SRC-01c 只有行动勾选或模块打卡
- **WHEN** 用户勾选关联行动、选择最小步骤或产生模块级打卡，但没有该课的权威完成记录
- **THEN** 系统不创建课程完成证据或复习项，原行动与打卡保持原样

### Requirement: SRC-02 使用账号范围的稳定课程身份

系统 MUST 以 `source_kind` 加规范来源键区分课程。认知键 SHALL 包含 module_id、round_id、lesson_no；英语/表达键 SHALL 包含 module_id、filename；新计划键 SHALL 包含 plan_id、lesson_no。同课重复引用 SHALL 归为一个对象，跨计划、模块或账号 MUST NOT 按标题或课号合并。

#### Scenario: SRC-02a 不同计划拥有相同课号和标题
- **WHEN** 两个计划各自存在已完成的第001课且标题相同
- **THEN** 候选与复习项保留不同来源身份，评分、跳转和历史互不影响

#### Scenario: SRC-02b 同课被多个行动引用
- **WHEN** 两个行动引用同一模块与文件的课程，用户重复请求加入
- **THEN** 当前账号最多存在一个对应复习项，不按行动数扩增到期数量

### Requirement: SRC-03 分来源分页与不完整数据声明

候选列表 SHALL 按来源稳定排序、每页最多 100 项，游标 MUST 绑定可信账号、来源和排序键。候选读取 MUST NOT 自动入队或逐课下载正文。分页未结束或来源故障时，系统 MUST 明确当前结果不完整，不把当前页数量冒充全量数量。

#### Scenario: SRC-03a 读取超过一页的历史课程
- **WHEN** 某来源存在 120 条合格课程，用户依次读取分页
- **THEN** 每页不超过 100 项，未变更数据集下合并得到 120 个唯一身份，读取不写入复习项或评分

#### Scenario: SRC-03b 游标用于另一账号或来源
- **WHEN** 用户将账号 A 或来源 copilot 的游标用于账号 B 或来源 plan
- **THEN** 服务端拒绝该游标，不读取游标指定的其他私人 schema

#### Scenario: SRC-03c 一个来源不可用
- **WHEN** 新计划来源查询失败而认知和英语/表达来源可用
- **THEN** 页面可读取可用来源，明确标注新计划来源不可用和结果不完整，不展示“全站没有待复习内容”的结论

### Requirement: SRC-04 当前完成证据与正文版本持续核验

加入、回顾和评分 SHALL 使用权威来源的当前状态和正文 SHA-256 版本。系统 MUST 区分 `eligible`、`source_unconfirmed`、`source_missing`、`version_changed` 和 `source_unavailable`，不从标题、当前时间或错误占位文字伪造版本和完成时间。来源无法核验或正文变化时 MUST 阻止新的评分写入，但保留已有复习历史。

#### Scenario: SRC-04a 完成撤销、归档或删除
- **WHEN** 计划反馈变为 unknown、认知完成记录被归档或复习课程被删除
- **THEN** 该项退出可评分到期集合并显示对应原因，既有事件与操作回执不删除；同版证据恢复后可继续原调度

#### Scenario: SRC-04b 正文在打开后变化
- **WHEN** 用户打开版本 V1 的复习页，服务端提交时读取到正文 V2
- **THEN** 系统拒绝旧版本评分并提示重新确认，不把 V1 的分数套用到 V2

#### Scenario: SRC-04c 暂时故障或版本无法证明
- **WHEN** 课程内容读取超时、来源表不可用或无法得到可靠的正文版本
- **THEN** 系统显示 source_unavailable，拒绝加入和新评分，保留草稿及历史；不记录未学习、休息或失败评分
