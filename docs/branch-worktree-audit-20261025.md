# 分支与 worktree 合并审计报告

生成时间：2026-10-25 21:00 CST
仓库：`/Volumes/肖豪/project/grow`（origin: `git@github.com:xiaohao19910303/grow.git`）
当前 HEAD：`codex/d0-rhythm-startup`（被外部进程切换，非本次操作）

> 本报告**未对仓库做任何写操作**。所有分支、worktree、main 均保持原状。

---

## 0. 前置警告：仓库存在并发写入

审计期间检测到另一个 Codex 会话在同一仓库实时提交：

| 时间 | 观测到的事件 |
|---|---|
| 20:53:50 | 主工作区 `main` 被切到 `codex/d0-rhythm-startup`，并打了一个 `[Checkout-checkpoint]` commit |
| 20:56 | 新建 worktree `code-structure-regression`（detached HEAD，带未提交改动） |
| 20:57 | `d0` 分支新增 commit `63a7c3f style(dark-mode): fix dialog backgrounds for learning-record and rhythm` |

**结论：在执行任何 merge / 删分支 / `git worktree remove` 之前，必须先确认该会话已停止，否则会产生 checkout 冲突、丢失未提交改动、或删掉对方正在用的 worktree。**

---

## 1. 总体结论

| 类别 | 数量 | 处理建议 |
|---|---|---|
| 已完全并入 main | 12 | 直接删除（安全） |
| 未并入、但属于同一条提交链 | 4 | 只合 `d0` 一个，其余随之消解 |
| 未并入、遗留/已被取代 | 2 | 直接删除（用户已确认） |
| 无本地分支的 worktree | 1 | 单独处理（detached，有未提交改动） |
| **main 与 origin/main 不同步** | — | main 领先 1、落后 3，需先对齐 |

---

## 2. 已完全并入 main 的分支（可安全删除）

判定方法：`git merge-base --is-ancestor <branch> main` 为真，且 `main..<branch>` 提交数为 0。

| 分支 | HEAD | 最后提交日期 |
|---|---|---|
| `codex/action-plans-p0` | b0de9b3 | 2026-10-22 |
| `codex/fix-learning-consistency` | 80f69af | 2026-10-18 |
| `codex/full-suite-repair` | d313cfb | 2026-10-24 |
| `codex/growth-navigation-release` | 2858c75 | 2026-10-21 |
| `codex/growth-navigation-round2-current` | f433821 | 2026-10-21 |
| `codex/growth-navigation-round3` | 23a0970 | 2026-10-21 |
| `codex/merge-local-20261024` | 3f0b83e | 2026-10-24 |
| `codex/navigation-audit-polish` | ddd5d58 | 2026-10-21 |
| `codex/readable-recommendations` | c875e0f | 2026-10-17 |
| `codex/reading-in-site` | b3c0ea6 | 2026-10-17 |
| `codex/today-learning-schedule` | fa80034 | 2026-10-19 |
| `codex/web-standalone-batch1` | 370684f | 2026-10-23 |

这 12 个分支的全部提交都已存在于 `main` 历史中，删除不会丢失任何内容。其中 4 个当前挂着 worktree（action-plans-p0、full-suite-repair、growth-navigation-round3、web-standalone-batch1），必须**先 remove worktree 再删分支**。

---

## 3. 未并入 main 的分支：真实关系

这是本次审计最关键的发现——那 4 个"大分支"不是四条平行的工作线，而是**一条叠加链 + 一个分叉**：

```
main (dc3dafe)
 └─ 3f0b83e  ← 共同 merge-base
     ├─ codex/grow-records-g1-completion      (+16 提交, 312 文件, +22653/-478)
     │    └─ codex/grow-native-reading        (+26 提交, 469 文件, +35698/-542)
     │         ├─ codex/grow-private-learning (+38 提交, 496 文件, +37216/-817)
     │         └─ codex/d0-rhythm-startup     (+40 提交, 542 文件, +39126/-997)
     └─ codex/growth-navigation-round2        (+1 提交, 6 文件, +314/-30)
```

已用 `git merge-base --is-ancestor` 验证的祖先关系：

- `grow-records-g1-completion` → 是 `grow-native-reading` 的祖先
- `grow-records-g1-completion` → 是 `grow-private-learning` 的祖先
- `grow-records-g1-completion` → 是 `d0-rhythm-startup` 的祖先
- `grow-native-reading` → 是 `grow-private-learning` 的祖先
- `grow-native-reading` → 是 `d0-rhythm-startup` 的祖先

**含义：合并 `d0-rhythm-startup` 等价于一次性并入 `g1-completion` + `native-reading` + `d0` 三条线的全部历史。** 唯一游离在外的是 `grow-private-learning`——它是 `native-reading` 之后的分叉，含 37 个 `native-reading` 没有的文件改动（+1552/-309），主要是 `知行成长/server/mobile_private.py` 相关。

---

## 4. 差异规模警示

各分支相对 main 的改动量（`git diff --stat main...<branch>`）：

| 分支 | 文件数 | 增/删行 | 主要目录分布 |
|---|---|---|---|
| `d0-rhythm-startup` | 542 | +39126 / -997 | docs 370、知行成长 126、openspec 24 |
| `grow-private-learning` | 496 | +37216 / -817 | docs 类似规模 |
| `grow-native-reading` | 469 | +35698 / -542 | 同上 |
| `grow-records-g1-completion` | 312 | +22653 / -478 | 同上 |

改动量的大头是 `docs/` 下的文档（每个分支 200–370 个文件）和 `知行成长/`（60–126 个文件），并非纯代码。

**这带来一个实质性风险：这几条分支的 docs 内容高度同源且层层叠加，如果"全部逐个合并"，同一批文档会被反复改写，极易产生大面积冲突和重复内容。** 这也是推荐"只合 d0 一个"的技术依据——不是省事，而是合并 4 条会得到比合 1 条更差的树。

---

## 5. 遗留分支处置（用户已确认：直接删除）

| 分支 | HEAD | 判定依据 |
|---|---|---|
| `wip/main-worktree-20261017` | a08813c | 8 天前的临时快照（"snapshot main worktree before branch consolidation"），merge-base 停在 626068b2，内容已被后续 12 次合并覆盖 |
| `codex/growth-navigation-round2` | ed045a7 | 其后续 `round2-current`、`round3` 均已并入 main；+1 提交仅 6 个文件、314 行（cycle review 测试与导航重构），属被取代的中间迭代 |

---

## 6. Worktree 清单

| 路径 | 挂载分支 | 状态 |
|---|---|---|
| `/Volumes/肖豪/project/grow` | `codex/d0-rhythm-startup`（应为 main） | 干净 |
| `/Users/hao/.codex/worktrees/action-plans-p0/grow` | `codex/action-plans-p0` | 干净，可移除 |
| `/Users/hao/.codex/worktrees/full-suite-repair/grow` | `codex/full-suite-repair` | 干净，可移除 |
| `/Users/hao/.codex/worktrees/growth-navigation-round3/grow` | `codex/growth-navigation-round3` | 干净，可移除 |
| `/Users/hao/.codex/worktrees/web-standalone-batch1/grow` | `codex/web-standalone-batch1` | 干净，可移除 |
| `/Volumes/肖豪/project/grow/.worktrees/grow-records-g1-completion` | `codex/grow-private-learning` | **有未提交改动** `知行成长/server/mobile_private.py` |
| `/Users/hao/.codex/worktrees/code-structure-regression/grow` | detached HEAD (31f6312) | **有未提交改动** `docs/verification/code-structure-2026-10-25/` 下 manifest.json 修改 + README.md 未跟踪 |

注意两点：

1. `.worktrees/` 目录本身在 `git status` 里显示为未跟踪（`?? .worktrees/`），建议加入 `.gitignore`。
2. `code-structure-regression` 是 20:56 外部会话新建的，**不属于本次清理范围**，且带未提交改动，不要动。

---

## 7. main 与 origin 不同步

```
main          dc3dafe  ← 领先 origin/main 1 个提交
origin/main   bb408ca  ← 领先 main 3 个提交
```

- main 独有：`dc3dafe style(dark-mode): fix all dialog backgrounds for dark mode`
- origin 独有：`bb408ca fix: 修复搜索功能的三个问题`、`c4394dc docs: 更新知识管理与Flutter学习笔记`、`71e6efa docs: add October 21-22 daily learning lessons`

合并前必须先把 main 与 origin/main 对齐（rebase 或 merge），否则后续所有合并都基于一个落后 3 个提交的基线，冲突会更多。

---

## 8. 推荐执行顺序

等外部 Codex 会话停止后，按以下顺序执行：

```bash
# ── 阶段 1：环境归位 ──
cd /Volumes/肖豪/project/grow
git checkout main                      # 从 d0 切回 main
git stash list && git status           # 确认无残留改动
git fetch --all --prune

# ── 阶段 2：对齐 origin ──
git merge origin/main                  # 或 rebase，视团队习惯
# 解决冲突 → 测试 → commit

# ── 阶段 3：合并 d0（覆盖 g1 + native-reading + d0 三条线）──
git merge --no-ff codex/d0-rhythm-startup
# 预期在 docs/ 与 知行成长/ 有冲突，逐个解决
# 合并后必须跑测试，确认 dark-mode 相关改动与既有代码兼容

# ── 阶段 4：处理 private-learning 分叉（需单独决策）──
git diff codex/grow-native-reading codex/grow-private-learning
# 仅 37 个文件差异，评估 mobile_private.py 是否需要并入

# ── 阶段 5：清理已合并分支的 worktree，再删分支 ──
git worktree remove /Users/hao/.codex/worktrees/action-plans-p0/grow
git worktree remove /Users/hao/.codex/worktrees/full-suite-repair/grow
git worktree remove /Users/hao/.codex/worktrees/growth-navigation-round3/grow
git worktree remove /Users/hao/.codex/worktrees/web-standalone-batch1/grow
git worktree remove /Volumes/肖豪/project/grow/.worktrees/grow-records-g1-completion --force
# 注意 code-structure-regression 保留不动

# ── 阶段 6：删除除 main 外全部分支 ──
git branch -d codex/action-plans-p0 codex/fix-learning-consistency \
  codex/full-suite-repair codex/growth-navigation-release \
  codex/growth-navigation-round2-current codex/growth-navigation-round3 \
  codex/merge-local-20261024 codex/navigation-audit-polish \
  codex/readable-recommendations codex/reading-in-site \
  codex/today-learning-schedule codex/web-standalone-batch1
git branch -D codex/growth-navigation-round2 wip/main-worktree-20261017
# 阶段 3/4 完成后才能删 d0 / private-learning / native-reading / g1

# ── 阶段 7：收尾 ──
echo ".worktrees/" >> .gitignore
git worktree prune
git branch -a                            # 应只剩 main
```

---

## 9. 需你决策的遗留项

| 项 | 说明 |
|---|---|
| `grow-private-learning` 的 37 个文件差异 | 合 d0 不覆盖它（它是 native-reading 的后续分叉），需单独判断 `mobile_private.py` 是否要 |
| `.worktrees/grow-records-g1-completion` 的未提交改动 | `mobile_private.py` 有修改，删 worktree 会丢；要先 diff 确认或提交 |
| `code-structure-regression` worktree | 外部会话刚建的，带未提交改动，不在清理范围 |
| 是否需要推送 main | 对齐 origin 后是否 `git push`，由你决定 |

---

## 10. 执行结果（2026-10-25 21:00–21:17 已完成）

> 本章节为执行后回填。上方 1–9 章为执行前的原始审计，保留以便追溯判断依据。

### 10.1 时序与并发事故

监测 21:01–21:04 连续 7 次采样均无活动后开始执行。但**外部 Codex 会话并未真正终止**：21:09:13 它在 `.worktrees/grow-records-g1-completion` 内自行执行了 `git merge main`，产生 `71ca3df`，导致我此前的 `--no-ff` 合并被 fast-forward 覆盖。

已核实无破坏性影响（最终 main 与 `codex/grow-private-learning` 差异归零），但这是本次执行中唯一失控点。**结论：多 agent 共用仓库时，静默数分钟不等于会话结束。**

### 10.2 关键保全动作

`codex/grow-private-learning` 的 worktree 里有**未提交的实际功能代码**：

```
知行成长/server/mobile_private.py            (+31/-7)
知行成长/server/mobile_learning_questions.py (+7)
知行成长/server/tests/test_mobile_learning_questions.py (新增)
```

若按原计划 `worktree remove --force` 会直接丢失。已先提交为 `984cabe` 保全，随后正式合入 main。

### 10.3 实际提交链

| 提交 | 说明 | 冲突 |
|---|---|---|
| `c035544` | merge origin/main（3 提交：搜索修复 + 每日课程） | 0 |
| `514a1a6` | merge d0 链（526 文件 / +38269 行） | 0 |
| `71ca3df` | merge private-learning（9 文件 / +308 行） | 0 |

原报告预判 docs 会大面积冲突，实际**零冲突**——因为几条分支的 docs 内容同源，自动合并即可正确收敛。

### 10.4 测试验证

`知行成长/server` 全量 pytest：

| | failed | passed | skipped | errors |
|---|---|---|---|---|
| 合并前基线 `514a1a6` | 11 | 106 | 619 | 2 |
| 合并后 `71ca3df` | 11 | **109** | 623 | 2 |

失败项**完全一致**，均为预先存在的环境问题（缺 `TEST_POSTGRES_DSN`、需浏览器的 UI 测试），非合并引入。通过数 +3 恰为 private-learning 新增的手机端测试。

正确跑法（必须在该目录下，否则 import 失败）：

```bash
cd 知行成长/server && PYTHONPATH=. ../.venv/bin/python -m pytest tests/ -q
```

### 10.5 最终状态

```
本地分支：* main          （仅 1 个，目标达成）
worktree：2 个
  /Volumes/肖豪/project/grow                                71ca3df [main]
  /Users/hao/.codex/worktrees/code-structure-regression/grow 31f6312 (detached)
安全网：tag backup/before-cleanup-20261025 -> 63a7c3f
main：领先 origin/main 44 个提交（未 push）
```

已删除 18 个分支、移除 5 个 worktree。

### 10.6 回滚方式

所有被删分支的内容均可恢复：

```bash
# 从备份 tag 恢复某个分支
git branch <分支名> <该分支原名对应的 commit>
# 或从 reflog 查询
git reflog --all | grep <关键字>
```

备份 tag `backup/before-cleanup-20261025` 指向执行前的 `63a7c3f`。

### 10.7 遗留待办

| 项 | 状态 |
|---|---|
| `git push` main（44 个提交） | 未执行，待确认 |
| worktree `code-structure-regression` | 未动（外部会话在用，有未提交改动） |
| 仓库 2 个 stash | 未处理（`pre-reader-integration`、`grow-reader`） |
| 422 个 `docs/verification/**/*.log`（8.1MB） | 保留，属项目证据约定 |


## 11. 后续收敛验收

本轮补齐 detached 结构优化 worktree 的剩余改动，并在合并后的 main 上运行完整隔离回归：746 项 Python、33 组 JavaScript 全部通过，0 失败、0 错误、0 跳过。最新分支清理与证据以[收敛报告](verification/branch-consolidation-2026-10-25/README.md)为准；上文未配置数据库的 pytest 运行不作为最终验收。


最新清理已完成：main 已同步 origin，远端 5 个旧功能分支已删除，最后一个 detached worktree 已无强制移除。当前本地与远端仅 main，工作树仅 `/Volumes/肖豪/project/grow`。两份 stash 保留，私人会话记忆未发布。
