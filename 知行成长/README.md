# 知行成长 - 云端应用

## 🌐 在线访问

**应用地址**: https://zhixingchengzhang.onrender.com

随时随地通过浏览器访问，无需安装任何软件。

## 📱 快速开始

### 1. 打开应用
在任何设备的浏览器中访问上面的网址

### 2. 开始使用
- 查看学习任务
- 记录学习进度
- 查看知识图谱
- 管理个人成长

### 3. 添加到主屏幕（推荐）
**iPhone**: Safari → 分享 → 添加到主屏幕  
**Android**: Chrome → 菜单 → 添加到主屏幕

## ✨ 功能特性

- 📚 **学习管理** - 追踪每日学习任务
- 📝 **反思笔记** - 记录学习心得
- 📊 **知识图谱** - 可视化知识结构
- 📈 **成长追踪** - 记录习惯和打卡
- 💹 **股票复盘** - 投资学习和记录
- 📖 **阅读记录** - 管理阅读进度

## 🔧 技术栈

- **后端**: FastAPI (Python)
- **数据库**: PostgreSQL (Supabase)
- **部署**: Render.com
- **前端**: HTML5 + CSS3 + JavaScript

## 📂 项目结构

```
知行成长/
├── server/              # 后端代码
│   ├── app.py          # 主应用
│   ├── db.py           # 数据库层
│   ├── requirements.txt # 依赖
│   └── ...             # 其他模块
├── render.yaml         # Render 配置
├── Procfile            # 进程配置
└── README.md           # 本文件
```

## 💻 本地开发

如果需要本地开发：

```bash
# 1. 克隆仓库
git clone https://github.com/你的用户名/知行成长.git
cd 知行成长

# 2. 安装依赖
cd server
pip install -r requirements.txt

# 3. 启动服务器
python3 app.py

# 4. 访问 http://localhost:8000
```

## 🔄 自动部署

代码推送到 GitHub 后，Render 会自动重新部署：

```bash
git add .
git commit -m "更新说明"
git push
# 等待 2-3 分钟，应用自动更新
```

## 📊 状态监控

- **应用状态**: 查看 Render 控制台
- **数据库状态**: 查看 Supabase 控制台
- **日志查看**: Render → Logs

## 🐛 问题反馈

如遇问题：
1. 检查应用状态（是否休眠）
2. 查看日志信息
3. 验证数据库连接

## 📄 许可证

私人项目，仅供个人使用。

---

**部署时间**: 2026-10-16  
**版本**: v1.0  
**状态**: ✅ 运行中
