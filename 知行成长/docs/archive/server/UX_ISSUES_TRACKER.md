# UX 问题追踪清单

## 🔴 高优先级问题（P0）

### Issue #1: focusTodayTodo 功能缺失
- **文件**: `static/index.html:252`
- **代码**: `<button class="btn primary" onclick="focusTodayTodo()">新增待办</button>`
- **问题**: 函数未定义，按钮点击无响应
- **影响**: 核心待办功能无法使用
- **修复方案**:
  ```javascript
  function focusTodayTodo() {
    const input = document.getElementById('newTodoInput');
    if (input) {
      input.focus();
      input.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      openTodoForm();
    }
  }
  ```
- **工作量**: 0.5 天
- **状态**: ❌ 待修复

---

### Issue #2: 生成任务取消后状态未更新
- **文件**: `static/plans.js:289-299`
- **代码位置**: `watch` 函数中的取消按钮
- **问题**: 调用 API 后没有更新 UI，用户不知道是否成功
- **影响**: 用户体验严重受损
- **修复方案**:
  ```javascript
  const cancel=button(root,'取消生成',async()=>{
    try {
      await api('/attempts/'+id+'/cancel',{});
      toast('已取消生成');
      status.textContent = '已取消生成';
      cancel.disabled = true;
      cancel.textContent = '已取消';
      setTimeout(()=>window.loadPlans(), 1500);
    } catch(e) {
      toast('取消失败：' + e.message);
    }
  });
  ```
- **工作量**: 0.5 天
- **状态**: ❌ 待修复

---

### Issue #3: 跨标签数据同步延迟
- **文件**: 多个文件（action-plans.js, daily-agenda.js 等）
- **问题**: 数据只在显式调用 load() 时刷新，其他标签的操作不会自动同步
- **影响**: 用户可能看到过时数据
- **修复方案**: 实现全局 EventBus
  ```javascript
  const EventBus = {
    listeners: new Map(),
    on(event, callback) {
      if (!this.listeners.has(event)) {
        this.listeners.set(event, new Set());
      }
      this.listeners.get(event).add(callback);
    },
    emit(event, data) {
      this.listeners.get(event)?.forEach(cb => cb(data));
    }
  };
  
  // 在数据变更时触发
  EventBus.emit('plans:changed', { planId: p.id, action });
  
  // 在其他标签监听
  EventBus.on('plans:changed', () => {
    if (currentTab === 'personal') {
      window.DailyAgenda?.render();
    }
  });
  ```
- **工作量**: 2 天
- **状态**: ❌ 待修复

---

### Issue #4: 乐观更新失败回滚不完善
- **文件**: `static/action-plans.js:24-30`
- **代码位置**: `change` 函数
- **问题**: 操作失败时没有回滚本地状态
- **影响**: 数据可靠性问题
- **修复方案**:
  ```javascript
  async function change(p, action, values={}) {
    const oldPlan = planById(p.id);
    const oldExecution = snapshot.execution;
    
    // 乐观更新
    snapshot.plans = snapshot.plans.map(item => 
      item.id === p.id ? { ...item, ...values, status: 'updating' } : item
    );
    renderHome();
    
    try {
      const result = await client.write(...);
      snapshot.plans = snapshot.plans.map(item => 
        item.id === p.id ? { ...item, ...result.plan } : item
      );
      return result;
    } catch (error) {
      snapshot.plans = snapshot.plans.map(item => 
        item.id === p.id ? oldPlan : item
      );
      snapshot.execution = oldExecution;
      renderHome();
      toast('操作失败：' + error.message);
      throw error;
    }
  }
  ```
- **工作量**: 1 天
- **状态**: ❌ 待修复

---

## 🟡 中优先级问题（P1）

### Issue #5: 导航逻辑复杂
- **文件**: `static/index.html:2054-2095`
- **问题**: goTab 函数包含 20+ 个 if 语句，难以维护
- **影响**: 新增视图容易遗漏边界情况
- **建议**: 使用视图元数据注册机制
- **工作量**: 1.5 天
- **状态**: ❌ 待优化

---

### Issue #6: 树形视图折叠状态丢失
- **文件**: `static/action-plans.js:80-99`
- **代码位置**: `renderTreeNode` 函数
- **问题**: 折叠状态仅保存在 DOM 中，重新渲染后丢失
- **影响**: 用户体验差
- **修复方案**: 使用 Set 持久化展开状态
  ```javascript
  const expandedPlans = new Set();
  
  function renderTreeNode(container,plan,children,byId,depth){
    const isExpanded = expandedPlans.has(plan.id);
    // ... 渲染逻辑
    const body=node('div',undefined,'action-tree-children');
    body.style.display=isExpanded?'':'none';
  }
  ```
- **工作量**: 0.5 天
- **状态**: ❌ 待修复

---

### Issue #7: 表单验证不一致
- **文件**: 多个表单（action-plans.js:253-258 等）
- **问题**: 表单提交前没有验证必填字段
- **影响**: 用户体验差
- **建议**: 添加前端验证逻辑
- **工作量**: 1 天
- **状态**: ❌ 待修复

---

### Issue #8: 加载状态提示不统一
- **文件**: 多个文件
- **问题**: 不同模块的加载状态提示样式不一致
- **影响**: 界面一致性差
- **建议**: 创建统一的加载状态组件
- **工作量**: 1 天
- **状态**: ❌ 待优化

---

### Issue #9: 待调整项提示逻辑错误
- **文件**: `static/daily-agenda.js:85-86`
- **问题**: 代码在 personal 视图执行，但容器在 action-schedule 视图
- **影响**: 提示永远不会显示
- **修复方案**: 在 renderSchedule() 中添加待调整提示
- **工作量**: 0.5 天
- **状态**: ❌ 待修复

---

### Issue #10: 模板功能加载失败静默处理
- **文件**: `static/action-plans.js:152`
- **问题**: 模板加载失败时没有任何提示
- **影响**: 用户不知道原因
- **修复方案**: 添加错误提示
  ```javascript
  client.read('/templates').then(data=>{
    const templates = data.templates.filter(t=>t.period===kind);
    if(templates.length===0){
      option(templateSelect,'','暂无可用模板');
    } else {
      for(const t of templates) option(templateSelect,t.id,t.name);
    }
  }).catch(error=>{
    option(templateSelect,'','模板加载失败');
    console.warn('模板加载失败:', error);
  });
  ```
- **工作量**: 0.3 天
- **状态**: ❌ 待修复

---

### Issue #11: 阅读反馈保存逻辑复杂
- **文件**: `static/reading.js:17`
- **问题**: 多个副作用集中在一个函数中
- **影响**: 代码可维护性差
- **建议**: 拆分为独立函数
- **工作量**: 0.5 天
- **状态**: ❌ 待优化

---

### Issue #12: 文章搜集任务状态更新不及时
- **文件**: `static/reading.js:85-88`
- **问题**: 任务状态是静态的，不会自动更新
- **影响**: 用户体验差
- **建议**: 添加轮询或 WebSocket 实时更新
- **工作量**: 1 天
- **状态**: ❌ 待修复

---

### Issue #13: 草稿预览页面缺少编辑入口
- **文件**: `static/plans.js` (previewDraft 函数)
- **问题**: 用户查看草稿后无法直接编辑
- **影响**: 操作路径过长
- **建议**: 添加"编辑草稿"按钮
- **工作量**: 0.5 天
- **状态**: ❌ 待修复

---

### Issue #14: 数据加载顺序不确定
- **文件**: `static/index.html:2090`
- **问题**: 多个渲染函数并行执行，没有依赖管理
- **影响**: 某个函数失败会影响整体页面
- **修复方案**: 使用 Promise.allSettled
- **工作量**: 0.5 天
- **状态**: ❌ 待修复

---

## 🟢 低优先级问题（P2）

### Issue #15: 缺少课程搜索和筛选
- **文件**: `static/daily-learning.js`
- **问题**: 课程数量多时难以快速找到目标
- **建议**: 添加搜索框和筛选器
- **工作量**: 1 天
- **状态**: ❌ 待实现

---

### Issue #16: 课程刷新按钮位置不合理
- **文件**: `static/index.html:242`
- **问题**: 刷新按钮调用 loadDailyLearning，函数名不匹配
- **影响**: 用户困惑
- **建议**: 重命名为 refreshLibrary
- **工作量**: 0.2 天
- **状态**: ❌ 待修复

---

### Issue #17: 旧版待办数据兼容性
- **文件**: `static/daily-agenda.js:98-106`
- **问题**: legacyAgendaTasks() 函数未定义
- **影响**: 旧版数据无法显示
- **建议**: 添加数据迁移工具
- **工作量**: 0.5 天
- **状态**: ❌ 待修复

---

### Issue #18: 执行记录分页逻辑错误
- **文件**: `static/action-plans.js:123-131`
- **问题**: 硬编码每页 30 条
- **影响**: 分页可能不准确
- **修复方案**: 使用 API 返回的 page_size
- **工作量**: 0.2 天
- **状态**: ❌ 待修复

---

### Issue #19: 确认对话框缺乏详细信息
- **文件**: `static/action-plans.js:61-68`
- **问题**: 确认对话框只显示简单文本
- **影响**: 用户可能误操作
- **建议**: 使用自定义模态框展示详细信息
- **工作量**: 0.5 天
- **状态**: ❌ 待优化

---

### Issue #20: AI 报告生成按钮位置不合理
- **文件**: `static/index.html:277`
- **问题**: 生成按钮在报告列表下方
- **影响**: 不符合 F 型阅读模式
- **建议**: 移到标题右侧或顶部
- **工作量**: 0.2 天
- **状态**: ❌ 待修复

---

### Issue #21: 预测校准标题重复
- **文件**: `static/index.html:323-338`
- **问题**: 两个 section 都使用"预测校准"标题
- **影响**: 容易混淆
- **建议**: 重命名为"校准分析"和"预测记录"
- **工作量**: 0.1 天
- **状态**: ❌ 待修复

---

### Issue #22: 日程安排显示重复
- **文件**: `static/daily-agenda.js:71-89`
- **问题**: agendaTomorrowList 容器在 HTML 中未定义
- **影响**: 可能导致 JavaScript 错误
- **修复方案**: 在 HTML 中添加缺失的容器
- **工作量**: 0.3 天
- **状态**: ❌ 待修复

---

### Issue #23: 行动积累统计不一致
- **文件**: `static/daily-agenda.js:111-118`
- **问题**: actionGrowth 容器在 view-overview 中，不在 view-personal 中
- **影响**: overview 页面的统计数据可能不会自动刷新
- **修复方案**: 在 goTab 中明确刷新 overview 的数据
- **工作量**: 0.3 天
- **状态**: ❌ 待修复

---

## 统计

- **总问题数**: 23
- **高优先级（P0）**: 4 个（17%）
- **中优先级（P1）**: 10 个（43%）
- **低优先级（P2）**: 9 个（40%）

- **总工作量**: 约 15 天
- **P0 工作量**: 4 天
- **P1 工作量**: 6.3 天
- **P2 工作量**: 4.7 天

---

## 修复进度追踪

### 已完成 ✅
- （暂无）

### 进行中 🔄
- （暂无）

### 待修复 ❌
- Issue #1-23（全部）

---

## 备注

- 所有文件路径相对于 `/Users/hao/Documents/grow/知行成长/server/static/`
- 工作量估算基于单个开发者的工作效率
- 优先级可能随需求变化而调整
- 建议在修复前为每个问题创建单独的 Git issue
