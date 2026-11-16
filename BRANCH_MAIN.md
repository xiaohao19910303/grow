# main 分支 - 知行成长核心

> **分支**: `main`  
> **定位**: 知行成长学习平台核心功能，不包含投资系统或前端迁移代码

---

## 功能范围

### ✅ 包含（知行成长核心）

| 模块 | 说明 |
|------|------|
| 七大学习模块 | 英文阅读、认知通识、思维工具、结构化表达、执行复盘、深度写作、整合练习 |
| 课程系统 | 课程管理、学习进度、笔记 |
| 行动规划 | 今日行动、日常安排 |
| 记录系统 | 学习记录、成长复盘 |
| 知识索引 | 知识总目录 |
| FastAPI 后端 | 知行成长/server/ |

### ❌ 不包含（在其他分支）

| 功能 | 所在分支 |
|------|----------|
| 投资决策系统 | `grow/web-native-migration` |
| React Web 前端 | `grow/web-native-migration`（已迁至 plan/LightTick-Web） |
| iOS 原生 App | `grow/web-native-migration` |
| LightTick 身份 | `grow/web-native-migration` |

---

## 目录结构

```
main
├── 知行成长/              # 平台核心
│   ├── server/           # FastAPI 后端
│   └── docs/             # 平台文档
├── 英文阅读/              # 模块1
├── 每日认知与通识学习/    # 模块2
├── 现代思维工具教程/      # 模块3
├── 结构化表达/            # 模块4
├── 执行复盘/              # 模块5
├── 深度写作/              # 模块6
├── 整合练习/              # 模块7
├── 学习系统总览.md
├── 长期成长学习体系总规划.md
├── 高认知能力训练规划.md
└── 知识索引.md
```

---

## 快速启动

```sh
cd 知行成长/server
../../.venv/bin/python deployment.py check
../../.venv/bin/python deployment.py serve --port 8756
```

---

## 分支关系

```
main (知行成长核心)
 │
 ├── grow/zhixing-learning (同 main，知行成长完整功能)
 │
 └── grow/web-native-migration (前端迁移 + 原生 App + 投资系统)
```

---

## 设计原则

1. **专注学习** - main 只包含学习平台核心功能
2. **独立交付** - 可独立部署运行
3. **功能分离** - 投资、前端迁移等功能走独立分支
