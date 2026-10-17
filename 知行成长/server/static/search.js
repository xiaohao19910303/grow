/* 统一搜索模块 */
(function () {
  'use strict';

  let currentQuery = '';
  let currentFilters = {
    types: [],
    start_date: null,
    end_date: null,
  };
  let currentPage = 1;
  let currentPageSize = 20;
  let searchResults = [];
  let totalResults = 0;

  const moduleLabels = {
    learning: '学习记录',
    reflection: '反思日志',
    decision: '决策记录',
    prediction: '预测记录',
    knowledge: '知识图谱',
  };

  const moduleColors = {
    learning: '#4F6EF7',
    reflection: '#7C5CF0',
    decision: '#00A6A6',
    prediction: '#E07B39',
    knowledge: '#2FA84F',
  };

  /* ---------- 初始化 ---------- */
  function init() {
    const searchInput = document.getElementById('globalSearch');
    if (!searchInput) return;

    // 输入事件（带防抖）
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        const query = e.target.value.trim();
        if (query.length >= 2) {
          performSearch(query);
        } else if (query.length === 0) {
          clearResults();
        }
      }, 300);
    });

    // 回车事件
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const query = searchInput.value.trim();
        if (query) {
          performSearch(query);
        }
      }
    });

    // 快捷键 ⌘K / Ctrl+K
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        searchInput.focus();
        searchInput.select();
      }
    });

    // 筛选事件
    const typeFilter = document.getElementById('searchTypeFilter');
    const startDate = document.getElementById('searchStartDate');
    const endDate = document.getElementById('searchEndDate');

    if (typeFilter) {
      typeFilter.addEventListener('change', updateFilters);
    }
    if (startDate) {
      startDate.addEventListener('change', updateFilters);
    }
    if (endDate) {
      endDate.addEventListener('change', updateFilters);
    }
  }

  /* ---------- 执行搜索 ---------- */
  async function performSearch(query) {
    if (!query) {
      clearResults();
      return;
    }

    currentQuery = query;
    currentPage = 1;

    await executeSearch();
  }

  /* ---------- 执行搜索请求 ---------- */
  async function executeSearch() {
    const container = document.getElementById('searchResults');

    // 显示加载状态
    if (container) {
      container.innerHTML = '<div class="loading">搜索中...</div>';
    }

    try {
      const params = new URLSearchParams({
        q: currentQuery,
        page: currentPage,
        page_size: currentPageSize,
      });

      if (currentFilters.types.length > 0) {
        params.set('types', currentFilters.types.join(','));
      }
      if (currentFilters.start_date) {
        params.set('start_date', currentFilters.start_date);
      }
      if (currentFilters.end_date) {
        params.set('end_date', currentFilters.end_date);
      }

      const response = await fetch(`/api/search?${params}`);
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || error.message || '搜索失败');
      }

      const data = await response.json();
      searchResults = data.results || [];
      totalResults = data.total_count || 0;

      renderResults();
      renderPagination();
      renderMeta();

      // 切换到搜索视图
      if (typeof goTab === 'function') {
        goTab('search');
      }
    } catch (error) {
      console.error('Search error:', error);
      if (container) {
        container.innerHTML = `
          <div class="error-state">
            <p>搜索失败: ${esc(error.message)}</p>
            <button class="btn" onclick="Search.retrySearch()">重试</button>
          </div>
        `;
      }
      if (typeof toast === 'function') {
        toast('搜索失败: ' + error.message);
      }
    }
  }

  /* ---------- 更新筛选条件 ---------- */
  function updateFilters() {
    const typeSelect = document.getElementById('searchTypeFilter');
    const startDate = document.getElementById('searchStartDate');
    const endDate = document.getElementById('searchEndDate');

    currentFilters.types = Array.from(typeSelect?.selectedOptions || [])
      .map(o => o.value)
      .filter(v => v);
    currentFilters.start_date = startDate?.value || null;
    currentFilters.end_date = endDate?.value || null;

    if (currentQuery) {
      currentPage = 1;
      executeSearch();
    }
  }

  /* ---------- 渲染搜索结果 ---------- */
  function renderResults() {
    const container = document.getElementById('searchResults');
    if (!container) return;

    if (searchResults.length === 0) {
      if (!currentQuery || currentQuery.trim() === '') {
        container.innerHTML = '<p class="empty">请输入搜索关键词</p>';
      } else {
        container.innerHTML = `
          <div class="empty-state">
            <p>未找到相关结果</p>
            <p class="desc">尝试使用不同的关键词或调整筛选条件</p>
          </div>
        `;
      }
      return;
    }

    const html = searchResults.map(result => {
      const moduleLabel = moduleLabels[result.module] || result.module;
      const moduleColor = moduleColors[result.module] || '#6B7280';
      const title = highlightText(result.title || '无标题', currentQuery);
      const summary = result.summary ? highlightText(result.summary, currentQuery) : '';
      const date = result.date ? (typeof fmtDateCN === 'function' ? fmtDateCN(result.date) : result.date) : '';

      return `
        <div class="search-result-item" data-module="${esc(result.module)}" data-id="${esc(result.id)}">
          <div class="search-result-header">
            <div class="search-result-title">${title}</div>
            <span class="search-result-module" style="background:${hexRgba(moduleColor, 0.12)};color:${moduleColor}">
              ${esc(moduleLabel)}
            </span>
          </div>
          ${summary ? `<div class="search-result-summary">${summary}</div>` : ''}
          <div class="search-result-meta">
            <span>${esc(date)}</span>
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = html;

    // 添加点击事件
    container.querySelectorAll('.search-result-item').forEach(item => {
      item.addEventListener('click', () => {
        const module = item.dataset.module;
        const id = item.dataset.id;
        navigateToResult(module, id);
      });
    });
  }

  /* ---------- 渲染分页 ---------- */
  function renderPagination() {
    const container = document.getElementById('searchPagination');
    if (!container) return;

    const totalPages = Math.ceil(totalResults / currentPageSize);
    if (totalPages <= 1) {
      container.innerHTML = '';
      return;
    }

    let html = '';

    // 上一页
    html += `<button ${currentPage === 1 ? 'disabled' : ''} onclick="Search.goToPage(${currentPage - 1})">上一页</button>`;

    // 页码
    for (let i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
        html += `<button class="${i === currentPage ? 'current' : ''}" onclick="Search.goToPage(${i})">${i}</button>`;
      } else if (i === currentPage - 3 || i === currentPage + 3) {
        html += '<span>…</span>';
      }
    }

    // 下一页
    html += `<button ${currentPage === totalPages ? 'disabled' : ''} onclick="Search.goToPage(${currentPage + 1})">下一页</button>`;

    container.innerHTML = html;
  }

  /* ---------- 渲染元信息 ---------- */
  function renderMeta() {
    const container = document.getElementById('searchMeta');
    if (!container) return;

    if (totalResults === 0) {
      container.textContent = '未找到相关结果';
    } else {
      const start = (currentPage - 1) * currentPageSize + 1;
      const end = Math.min(currentPage * currentPageSize, totalResults);
      container.textContent = `找到 ${totalResults} 条结果，显示 ${start}-${end}`;
    }
  }

  /* ---------- 高亮文本 ---------- */
  function highlightText(text, query) {
    if (!query) return esc(text);

    const escaped = esc(text);
    const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return escaped.replace(regex, '<span class="search-highlight">$1</span>');
  }

  /* ---------- 导航到结果 ---------- */
  function navigateToResult(module, id) {
    // 根据模块类型导航到对应视图
    const moduleToTab = {
      learning: 'library',
      reflection: 'reviews',
      decision: 'decisions',
      prediction: 'predictions',
      knowledge: 'knowledge',
    };

    const tab = moduleToTab[module];
    if (tab && typeof goTab === 'function') {
      goTab(tab);
      // TODO: 可以在目标视图中滚动到对应记录
    }
  }

  /* ---------- 清空结果 ---------- */
  function clearResults() {
    searchResults = [];
    totalResults = 0;
    currentQuery = '';

    const container = document.getElementById('searchResults');
    if (container) container.innerHTML = '';

    const pagination = document.getElementById('searchPagination');
    if (pagination) pagination.innerHTML = '';

    const meta = document.getElementById('searchMeta');
    if (meta) meta.textContent = '';
  }

  /* ---------- 重试搜索 ---------- */
  function retrySearch() {
    if (currentQuery) {
      executeSearch();
    }
  }

  /* ---------- 公开接口 ---------- */
  window.Search = {
    init,
    performSearch,
    retrySearch,
    goToPage: (page) => {
      currentPage = page;
      executeSearch();
    },
  };

  // DOM 加载后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
