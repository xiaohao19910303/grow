/* Learning history with calendar view */
(() => {
  'use strict';
  const root = document.getElementById('view-learning-history');
  if (!root) return;

  let currentMonth = new Date();
  let selectedDate = null;
  let monthData = {}; // date -> count

  const months = ['一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月'];
  const weekDays = ['日', '一', '二', '三', '四', '五', '六'];

  function today() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function formatTime(dateStr) {
    if (!dateStr) return '未知时间';
    const d = new Date(dateStr);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }

  function formatDate(dateStr) {
    if (!dateStr) return '未知日期';
    const d = new Date(dateStr);
    return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
  }

  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  }

  async function loadMonthData(year, month) {
    // Load learning counts for the entire month
    const startDate = `${year}-${String(month + 1).padStart(2, '0')}-01`;
    const endDate = `${year}-${String(month + 1).padStart(2, '0')}-31`;

    try {
      const response = await fetch(`/api/copilot/learning-history/months?start=${startDate}&end=${endDate}`);
      if (!response.ok) throw new Error('加载失败');
      monthData = await response.json();
      renderCalendarGrid();
    } catch (e) {
      console.error('Failed to load month data:', e);
      monthData = {};
      renderCalendarGrid();
    }
  }

  async function loadHistory(date) {
    try {
      const response = await fetch(`/api/copilot/learning-history/by-date?date=${date}`);
      if (!response.ok) throw new Error('加载失败');
      return response.json();
    } catch (e) {
      console.error('Failed to load history:', e);
      return { date, total: 0, items: [] };
    }
  }

  function renderCalendar() {
    const calendar = node('div', undefined, 'learning-calendar');

    // Header with month navigation
    const header = node('div', undefined, 'calendar-header');

    const prevBtn = node('button', '◀ 上月');
    prevBtn.className = 'btn btn-small';
    prevBtn.onclick = () => changeMonth(-1);
    header.append(prevBtn);

    const monthLabel = node('span', `${currentMonth.getFullYear()}年${currentMonth.getMonth() + 1}月`);
    monthLabel.className = 'month-label';
    header.append(monthLabel);

    const nextBtn = node('button', '下月 ▶');
    nextBtn.className = 'btn btn-small';
    nextBtn.onclick = () => changeMonth(1);
    header.append(nextBtn);

    calendar.append(header);

    // Calendar grid (will be filled by renderCalendarGrid)
    const grid = node('div', undefined, 'calendar-grid');
    calendar.append(grid);

    root.append(calendar);
  }

  function renderCalendarGrid() {
    const grid = root.querySelector('.calendar-grid');
    if (!grid) return;
    grid.replaceChildren();

    const year = currentMonth.getFullYear();
    const month = currentMonth.getMonth();

    // Week day headers
    weekDays.forEach(day => {
      grid.append(node('div', day, 'calendar-cell weekday-header'));
    });

    // Days in month
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const firstDay = new Date(year, month, 1).getDay();

    // Empty cells before first day
    for (let i = 0; i < firstDay; i++) {
      grid.append(node('div', '', 'calendar-cell empty'));
    }

    // Day cells
    for (let day = 1; day <= daysInMonth; day++) {
      const date = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
      const cell = node('div', String(day), 'calendar-cell');
      cell.dataset.date = date;

      // Highlight if has records
      const count = monthData[date] || 0;
      if (count > 0) {
        cell.classList.add('has-records');
        cell.title = `${count} 条学习记录`;
      }

      // Highlight today
      if (date === today()) {
        cell.classList.add('today');
      }

      // Highlight selected date
      if (date === selectedDate) {
        cell.classList.add('selected');
      }

      cell.onclick = () => selectDate(date);
      grid.append(cell);
    }
  }

  async function changeMonth(delta) {
    currentMonth.setMonth(currentMonth.getMonth() + delta);
    root.querySelector('.month-label').textContent = `${currentMonth.getFullYear()}年${currentMonth.getMonth() + 1}月`;
    await loadMonthData(currentMonth.getFullYear(), currentMonth.getMonth());
    renderCalendarGrid();
  }

  async function selectDate(date) {
    selectedDate = date;
    renderCalendarGrid();

    // Update selected date label
    const label = root.querySelector('.selected-date-label');
    if (label) {
      label.textContent = formatDate(date) + ' 学习记录';
    }

    const history = await loadHistory(date);
    renderHistoryList(history);
  }

  function renderHistoryList(history) {
    const list = root.querySelector('.history-list');
    if (!list) return;
    list.replaceChildren();

    if (!history.items.length) {
      list.append(node('p', '这天没有学习记录。', 'desc'));
      return;
    }

    // Stats summary
    const totalTime = history.items.reduce((sum, item) => sum + (item.time_spent_seconds || 0), 0);
    const totalMinutes = Math.round(totalTime / 60);

    const stats = node('div', undefined, 'history-stats');
    stats.append(node('span', `共 ${history.items.length} 课 · ${totalMinutes} 分钟`, 'desc'));
    list.append(stats);

    // Record cards
    history.items.forEach(record => {
      const card = node('div', undefined, 'history-card');

      // Header: lesson title and time
      const header = node('div', undefined, 'history-card-header');
      header.append(node('h4', `第${String(record.lesson_no).padStart(3, '0')}课`));
      header.append(node('span', `${formatTime(record.completed_at)} · ${Math.round((record.time_spent_seconds || 0) / 60)}分钟`, 'desc'));
      card.append(header);

      // Summary section
      if (record.summary_text) {
        const summarySection = node('div', undefined, 'history-section');
        summarySection.append(node('h5', '核心收获'));
        summarySection.append(node('p', record.summary_text));
        card.append(summarySection);
      }

      // Review answers section
      if (record.review_answers && Object.keys(record.review_answers).length) {
        const reviewSection = node('div', undefined, 'history-section');
        reviewSection.append(node('h5', '练习反馈'));

        const answersList = node('ul', undefined, 'history-answers');
        Object.entries(record.review_answers).forEach(([qNum, answer]) => {
          const li = node('li');
          li.append(node('strong', `问题${qNum}: `));
          li.append(node('span', answer));
          answersList.append(li);
        });
        reviewSection.append(answersList);
        card.append(reviewSection);
      }

      list.append(card);
    });
  }

  window.loadLearningHistory = async () => {
    root.replaceChildren();

    // Title
    root.append(node('h2', '学习记录'));
    root.append(node('p', '通过日历查看每天的学习记录。', 'desc'));

    // Selected date label
    const dateLabel = node('h3', '', 'selected-date-label');
    root.append(dateLabel);

    // Calendar
    renderCalendar();

    // History list
    const list = node('div', undefined, 'history-list');
    root.append(list);

    // Load current month data
    await loadMonthData(currentMonth.getFullYear(), currentMonth.getMonth());

    // Select today by default
    selectDate(today());
  };
})();
