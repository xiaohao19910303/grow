// 课程完成后的思考记录功能
// 这个文件需要合并到现有的 copilot.js 中

// 添加思考记录相关的变量
let currentCourseReflection = null;
const reflectionStorage = {}; // 存储每课的完成记录

// 课程完成后的思考记录功能
function showCourseReflection(lessonNo) {
  // 创建思考记录对话框
  const dialog = document.createElement('dialog');
  dialog.className = 'cp-reflection-dialog';

  const content = document.createElement('div');
  content.className = 'cp-reflection-content';

  // 标题
  const title = document.createElement('h2');
  title.textContent = `第${lessonNo}课完成记录与思考`;
  content.append(title);

  // 说明
  const desc = document.createElement('p');
  desc.className = 'desc';
  desc.textContent = '课程学习完成后，记录你的思考和收获。这有助于巩固学习效果。';
  content.append(desc);

  // 完成时间
  const timeField = document.createElement('div');
  timeField.className = 'plan-field';
  timeField.append(document.createElement('label').textContent = '完成时间：');
  const timeInput = document.createElement('input');
  timeInput.type = 'datetime-local';
  timeInput.value = new Date().toISOString().slice(0, 16);
  timeField.append(timeInput);
  content.append(timeField);

  // 学习时长
  const durationField = document.createElement('div');
  durationField.className = 'plan-field';
  durationField.append(document.createElement('label').textContent = '学习时长（分钟）：');
  const durationInput = document.createElement('input');
  durationInput.type = 'number';
  durationInput.min = 1;
  durationInput.value = 30;
  durationField.append(durationInput);
  content.append(durationField);

  // 核心收获
  const keyLearningsField = document.createElement('div');
  keyLearningsField.className = 'plan-field';
  keyLearningsField.append(document.createElement('label').textContent = '核心收获（1-3个要点）：');
  const keyLearningsInput = document.createElement('textarea');
  keyLearningsInput.rows = 4;
  keyLearningsInput.placeholder = '这节课我学到了什么？哪些观点改变了我的想法？';
  keyLearningsField.append(keyLearningsInput);
  content.append(keyLearningsField);

  // 个人思考
  const reflectionField = document.createElement('div');
  reflectionField.className = 'plan-field';
  reflectionField.append(document.createElement('label').textContent = '个人思考与反思：');
  const reflectionInput = document.createElement('textarea');
  reflectionInput.rows = 6;
  reflectionInput.placeholder = '我如何将这个知识应用到实际生活中？\n还有哪些疑问或想深入探索的方向？\n这个知识与之前学过的内容有什么联系？';
  reflectionField.append(reflectionInput);
  content.append(reflectionField);

  // 行动清单
  const actionsField = document.createElement('div');
  actionsField.className = 'plan-field';
  actionsField.append(document.createElement('label').textContent = '后续行动清单：');
  const actionsInput = document.createElement('textarea');
  actionsInput.rows = 4;
  actionsInput.placeholder = '基于这节课的内容，我打算：\n1. \n2. \n3. ';
  actionsField.append(actionsInput);
  content.append(actionsField);

  // 按钮
  const actions = document.createElement('div');
  actions.className = 'cp-actions';

  const cancelButton = document.createElement('button');
  cancelButton.textContent = '取消';
  cancelButton.className = 'btn';
  cancelButton.onclick = () => dialog.close();
  actions.append(cancelButton);

  const saveButton = document.createElement('button');
  saveButton.textContent = '保存完成记录';
  saveButton.className = 'btn primary';
  saveButton.onclick = async () => {
    const reflection = {
      lesson_no: lessonNo,
      completed_at: timeInput.value,
      duration_minutes: parseInt(durationInput.value) || 0,
      key_learnings: keyLearningsInput.value.trim(),
      personal_reflection: reflectionInput.value.trim(),
      action_items: actionsInput.value.trim()
    };

    try {
      await saveCourseReflection(reflection);
      dialog.close();
      alert('完成记录已保存！');
      // 刷新课程列表
      await load(false);
    } catch (e) {
      alert('保存失败：' + e.message);
    }
  };
  actions.append(saveButton);

  content.append(actions);
  dialog.append(content);
  document.body.append(dialog);
  dialog.showModal();
}

// 保存课程完成记录
async function saveCourseReflection(reflection) {
  // 保存到本地存储或API
  const data = await request('/course-reflections', 'POST', reflection);
  return data;
}

// 获取课程的完成记录
async function getCourseReflection(lessonNo) {
  try {
    const data = await request(`/course-reflections/${lessonNo}`, 'GET');
    return data;
  } catch (e) {
    return null;
  }
}

// 在课程列表中添加完成记录按钮
function addReflectionButton(course, container) {
  // 检查是否已有完成记录
  const hasReflection = course.reflection_completed;

  const button = document.createElement('button');
  button.textContent = hasReflection ? '查看完成记录' : '记录学习完成';
  button.className = 'btn' + (hasReflection ? '' : ' primary');
  button.onclick = async () => {
    if (hasReflection) {
      // 查看已有记录
      const reflection = await getCourseReflection(course.lesson_no);
      if (reflection) {
        showReflectionView(reflection);
      }
    } else {
      // 添加新记录
      showCourseReflection(course.lesson_no);
    }
  };

  container.append(button);
}

// 显示完成记录详情
function showReflectionView(reflection) {
  const dialog = document.createElement('dialog');
  dialog.className = 'cp-reflection-view';

  const content = document.createElement('div');

  const title = document.createElement('h2');
  title.textContent = `第${reflection.lesson_no}课完成记录`;
  content.append(title);

  // 完成信息
  const info = document.createElement('div');
  info.className = 'reflection-info';
  info.innerHTML = `
    <p><strong>完成时间：</strong>${new Date(reflection.completed_at).toLocaleString('zh-CN')}</p>
    <p><strong>学习时长：</strong>${reflection.duration_minutes} 分钟</p>
  `;
  content.append(info);

  // 核心收获
  if (reflection.key_learnings) {
    const learnings = document.createElement('div');
    learnings.className = 'reflection-section';
    learnings.append(document.createElement('h3').textContent = '核心收获');
    learnings.append(document.createElement('p').textContent = reflection.key_learnings);
    content.append(learnings);
  }

  // 个人思考
  if (reflection.personal_reflection) {
    const reflection_text = document.createElement('div');
    reflection_text.className = 'reflection-section';
    reflection_text.append(document.createElement('h3').textContent = '个人思考与反思');
    reflection_text.append(document.createElement('p').textContent = reflection.personal_reflection);
    content.append(reflection_text);
  }

  // 行动清单
  if (reflection.action_items) {
    const actions = document.createElement('div');
    actions.className = 'reflection-section';
    actions.append(document.createElement('h3').textContent = '后续行动清单');
    actions.append(document.createElement('p').textContent = reflection.action_items);
    content.append(actions);
  }

  // 编辑按钮
  const actions = document.createElement('div');
  actions.className = 'cp-actions';

  const editButton = document.createElement('button');
  editButton.textContent = '编辑记录';
  editButton.className = 'btn';
  editButton.onclick = () => {
    dialog.close();
    showCourseReflection(reflection.lesson_no);
  };
  actions.append(editButton);

  const closeButton = document.createElement('button');
  closeButton.textContent = '关闭';
  closeButton.className = 'btn';
  closeButton.onclick = () => dialog.close();
  actions.append(closeButton);

  content.append(actions);
  dialog.append(content);
  document.body.append(dialog);
  dialog.showModal();
}

// 在课程卡片中添加完成状态标识
function addReflectionBadge(course, card) {
  if (course.reflection_completed) {
    const badge = document.createElement('span');
    badge.className = 'reflection-badge';
    badge.textContent = '✓ 已完成记录';
    badge.title = '已记录学习完成';
    card.append(badge);
  }
}

// CSS样式（需要添加到 copilot.css）
const reflectionStyles = `
.cp-reflection-dialog, .cp-reflection-view {
  border: none;
  border-radius: 12px;
  padding: 0;
  max-width: 600px;
  width: 90%;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 10px 40px rgba(0,0,0,0.2);
}

.cp-reflection-content {
  padding: 24px;
}

.cp-reflection-content h2 {
  margin-top: 0;
  color: var(--text);
  font-size: 20px;
}

.cp-reflection-content .desc {
  color: var(--muted);
  font-size: 14px;
  margin-bottom: 20px;
}

.cp-reflection-content .plan-field {
  margin-bottom: 16px;
}

.cp-reflection-content .plan-field label {
  display: block;
  font-weight: 500;
  margin-bottom: 6px;
  color: var(--text);
}

.cp-reflection-content input,
.cp-reflection-content textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 14px;
  font-family: inherit;
}

.cp-reflection-content textarea {
  resize: vertical;
  line-height: 1.6;
}

.cp-reflection-content input:focus,
.cp-reflection-content textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(79, 110, 247, 0.1);
}

.cp-reflection-view {
  padding: 24px;
}

.reflection-info {
  background: var(--bg-soft);
  padding: 16px;
  border-radius: 8px;
  margin-bottom: 20px;
}

.reflection-info p {
  margin: 8px 0;
  color: var(--text);
}

.reflection-section {
  margin-bottom: 20px;
}

.reflection-section h3 {
  font-size: 16px;
  color: var(--primary);
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 2px solid var(--primary-soft);
}

.reflection-section p {
  line-height: 1.7;
  color: var(--text);
  white-space: pre-wrap;
}

.reflection-badge {
  display: inline-block;
  background: var(--success-bg);
  color: var(--success-text);
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  margin-top: 8px;
}

.reflection-badge::before {
  content: '✓';
  margin-right: 4px;
}
`;

// 注入样式
const style = document.createElement('style');
style.textContent = reflectionStyles;
document.head.append(style);

// 导出函数供外部使用
window.showCourseReflection = showCourseReflection;
window.addReflectionButton = addReflectionButton;
window.addReflectionBadge = addReflectionBadge;
