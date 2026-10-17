/* 时间线视图模块 */
(function () {
  'use strict';

  let currentFilters = {
    start_date: null,
    end_date: null,
    types: [],
  };
  let currentPage = 1;
  let currentPageSize = 50;
  let timelineData = [];
  let totalRecords = 0;

  const moduleLabels = {
    learning: '学习记录',
    reflection: '反思日志',
    decision: '决策记录',
    prediction: '预测记录',
    review: '复盘记录',
    insight: '灵感记录',
    knowledge: '知识图谱',
  };

  const moduleColors = {
    learning: '#4F6EF7',
    reflection: '#7C5CF0',
    decision: '#00A6A6',
    prediction: '#E07B39',
    review: '#2FA84F',
    insight: '#D64580',
    knowledge: '#6B7280',
  };

  /* ---------- 初始化 ---------- */
  function init() {
    // 设置默认日期范围（当月）
    const today = new Date();
    const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);

    const startDate = document.getElementById('timelineStartDate');
    const endDate = document.getElementById('timelineEndDate');

    if (startDate && !startDate.value) {
      startDate.value = formatDateISO(firstDay);
    }
    if (endDate && !endDate.value) {
      endDate.value = formatDateISO(today);
    }

    // 筛选事件
    if (startDate) {
      startDate.addEventListener('change', updateFilters);
    }
    if (endDate) {
      endDate.addEventListener('change', updateFilters);
    }

    const typeFilter = document.getElementById('timelineTypeFilter');
    if (typeFilter) {
      typeFilter.addEventListener('change', updateFilters);
    }
  }

  /* ---------- 加载时间线 ---------- */
  async function load() {
    const container = document.getElementById('timelineList');
    const statsContainer = document.getElementById('timelineStats');

    // 显示加载状态
    if (container) {
      container.innerHTML = '<div class="loading">加载中...</div>';
    }

    try {
      const params = new URLSearchParams({
        page: currentPage,
        page_size: currentPageSize,
      });

      if (currentFilters.start_date) {
        params.set('start_date', currentFilters.start_date);
      }
      if (currentFilters.end_date) {
        params.set('end_date', currentFilters.end_date);
      }
      if (currentFilters.types.length > 0) {
        params.set('types', currentFilters.types.join(','));
      }

      const response = await fetch(`/api/timeline?${params}`);
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || error.message || '加载时间线失败');
      }

      const data = await response.json();
      timelineData = data.records || [];
      totalRecords = data.total_count || 0;

      renderTimeline();
      renderPagination();
      loadStats();
    } catch (error) {
      console.error('Timeline error:', error);
      if (container) {
        container.innerHTML = `
          <div class="error-state">
            <p>加载失败: ${esc(error.message)}</p>
            <button class="btn" onclick="Timeline.load()">重试</button>
          </div>
        `;
      }
      if (typeof toast === 'function') {
        toast('加载时间线失败: ' + error.message);
      }
    }
  }

  /* ---------- 加载统计 ---------- */
  async function loadStats() {
    try {
      const response = await fetch('/api/timeline/stats');
      if (!response.ok) throw new Error('加载统计失败');

      const stats = await response.json();
      renderStats(stats);
    } catch (error) {
      console.error('Timeline stats error:', error);
    }
  }

  /* ---------- 渲染统计 ---------- */
  function renderStats(stats) {
    const container = document.getElementById('timelineStats');
    if (!container || !stats) return;

    // 使用 API 返回的完整统计数据
    let totalRecords = 0;
    let activeDays = 0;
    let moduleCount = 0;

    if (stats.by_module) {
      // 如果 API 返回了按模块统计
      moduleCount = Object.keys(stats.by_module).length;
      totalRecords = Object.values(stats.by_module).reduce((sum, m) => sum + (m.count || 0), 0);
    } else if (stats.total_records !== undefined) {
      totalRecords = stats.total_records;
    } else {
      // 回退到使用当前页数据计算
      totalRecords = window.Timeline._getTotalRecords();
    }

    if (stats.active_days !== undefined) {
      activeDays = stats.active_days;
    } else {
      // 回退到使用当前页数据计算
      activeDays = window.Timeline._getActiveDays();
    }

    const html = `
      <div class="card">
        <div class="k">总记录数</div>
        <div class="v">${totalRecords}</div>
      </div>
      <div class="card">
        <div class="k">活跃天数</div>
        <div class="v">${activeDays}</div>
      </div>
      <div class="card">
        <div class="k">模块数</div>
        <div class="v">${moduleCount}</div>
      </div>
    `;

    container.innerHTML = html;
  }

  // 内部方法：获取总记录数（从当前页数据计算）
  function _getTotalRecords() {
    return totalRecords;
  }

  // 内部方法：获取活跃天数（从当前页数据计算）
  function _getActiveDays() {
    const dates = new Set(timelineData.map(r => r.date).filter(Boolean));
    return dates.size;
  }

  /* ---------- 渲染时间线 ---------- */
  function renderTimeline() {
    const container = document.getElementById('timelineList');
    if (!container) return;

    if (timelineData.length === 0) {
      const hasFilters = currentFilters.start_date || currentFilters.end_date || currentFilters.types.length > 0;
      if (hasFilters) {
        container.innerHTML = `
          <div class="empty-state">
            <p>未找到符合条件的记录</p>
            <p class="desc">尝试调整筛选条件或日期范围</p>
            <button class="btn" onclick="Timeline.clearFilters()">清除筛选</button>
          </div>
        `;
      } else {
        container.innerHTML = `
          <div class="empty-state">
            <p>暂无学习记录</p>
            <p class="desc">开始记录你的学习历程，这里将展示你的成长轨迹</p>
          </div>
        `;
      }
      return;
    }

    // 按日期分组
    const grouped = {};
    timelineData.forEach(record => {
      const date = record.date || '未知日期';
      if (!grouped[date]) grouped[date] = [];
      grouped[date].push(record);
    });

    // 渲染
    const html = Object.entries(grouped)
      .sort((a, b) => b[0].localeCompare(a[0])) // 降序
      .map(([date, records]) => {
        const dateLabel = formatDateCN(date);
        const itemsHtml = records.map(renderItem).join('');

        return `
          <div class="timeline-date-group">
            <div class="timeline-date-header">${esc(dateLabel)}</div>
            ${itemsHtml}
          </div>
        `;
      }).join('');

    container.innerHTML = html;
  }

  // 清除筛选条件
  function clearFilters() {
    const startDate = document.getElementById('timelineStartDate');
    const endDate = document.getElementById('timelineEndDate');
    const typeFilter = document.getElementById('timelineTypeFilter');

    if (startDate) startDate.value = '';
    if (endDate) endDate.value = '';
    if (typeFilter) typeFilter.selectedIndex = -1;

    currentFilters = {
      start_date: null,
      end_date: null,
      types: [],
    };

    load();
  }

  /* ---------- 渲染单个记录 ---------- */
  function renderItem(record) {
    const moduleLabel = moduleLabels[record.module] || record.module;
    const moduleColor = moduleColors[record.module] || '#6B7280';
    const title = esc(record.title || '无标题');
    const summary = record.summary ? esc(record.summary) : '';
    const date = record.date ? formatDateCN(record.date) : '';

    return `
      <div class="timeline-item" data-module="${esc(record.module)}" data-id="${esc(record.id)}">
        <div class="timeline-item-header">
          <div class="timeline-item-title">${title}</div>
          <span class="timeline-item-module" style="background:${hexRgba(moduleColor, 0.12)};color:${moduleColor}">
            ${esc(moduleLabel)}
          </span>
        </div>
        ${summary ? `<div class="timeline-item-summary">${summary}</div>` : ''}
        <div class="timeline-item-meta">${esc(date)}</div>
      </div>
    `;
  }

  /* ---------- 渲染分页 ---------- */
  function renderPagination() {
    const container = document.getElementById('timelinePagination');
    if (!container) return;

    const totalPages = Math.ceil(totalRecords / currentPageSize);
    if (totalPages <= 1) {
      container.innerHTML = '';
      return;
    }

    let html = '';

    // 上一页
    html += `<button ${currentPage === 1 ? 'disabled' : ''} onclick="Timeline.goToPage(${currentPage - 1})">上一页</button>`;

    // 页码（简化版）
    for (let i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
        html += `<button class="${i === currentPage ? 'current' : ''}" onclick="Timeline.goToPage(${i})">${i}</button>`;
      } else if (i === currentPage - 3 || i === currentPage + 3) {
        html += '<span>…</span>';
      }
    }

    // 下一页
    html += `<button ${currentPage === totalPages ? 'disabled' : ''} onclick="Timeline.goToPage(${currentPage + 1})">下一页</button>`;

    container.innerHTML = html;
  }

  /* ---------- 更新筛选 ---------- */
  function updateFilters() {
    const startDate = document.getElementById('timelineStartDate');
    const endDate = document.getElementById('timelineEndDate');
    const typeSelect = document.getElementById('timelineTypeFilter');

    currentFilters.start_date = startDate?.value || null;
    currentFilters.end_date = endDate?.value || null;
    currentFilters.types = Array.from(typeSelect?.selectedOptions || [])
      .map(o => o.value)
      .filter(v => v);

    currentPage = 1;
    load();
  }

  /* ---------- 工具函数 ---------- */
  function formatDateISO(date) {
    const d = new Date(date);
    return d.getFullYear() + '-' +
           String(d.getMonth() + 1).padStart(2, '0') + '-' +
           String(d.getDate()).padStart(2, '0');
  }

  function formatDateCN(dateStr) {
    if (!dateStr) return '';
    const parts = dateStr.split('-').map(Number);
    if (parts.length !== 3) return dateStr;
    return `${parts[1]}月${parts[2]}日`;
  }

  /* ---------- 公开接口 ---------- */
  window.Timeline = {
    init,
    load,
    clearFilters,
    goToPage: (page) => {
      currentPage = page;
      load();
    },
    _getTotalRecords,
    _getActiveDays,
  };

  // DOM 加载后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
