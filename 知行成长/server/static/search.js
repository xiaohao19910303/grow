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
  let warnings = [];
  let requestNumber = 0, activeRequest = null;

  const moduleLabels = {
    investment:'投资记录',
    learning: '学习记录',
    reflection: '日常记录',
    review: '四问复盘', insight: '灵感记录', action: '行动记录',
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
      // Password managers can fill this field without a search interaction.
      if (document.activeElement !== searchInput) return;
      ++requestNumber; activeRequest?.abort();
      debounceTimer = setTimeout(() => {
        if (document.activeElement !== searchInput) return;
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
        clearTimeout(debounceTimer);
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
    if(typeFilter && !typeFilter.querySelector('option[value=investment]')){const option=document.createElement('option');option.value='investment';option.textContent='投资记录';typeFilter.append(option);}
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
    if (typeof goTab === 'function' && goTab('search') === false) return;
    const request = ++requestNumber;
    activeRequest?.abort(); activeRequest = new AbortController();
    let loading;

    // 显示加载状态
    if (container) {
      container.replaceChildren();
      loading = window.LoadingState?.start(container, '正在搜索资料…', '正在查找学习记录、笔记和其他已保存内容。');
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

      const response = await fetch(`/api/search?${params}`, {signal: activeRequest.signal});
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || error.message || '搜索失败');
      }

      const data = await response.json();
      if (request !== requestNumber) return;
      searchResults = data.results || [];
      totalResults = data.total_count || 0;
      warnings = data.warnings || [];

      renderResults();
      renderPagination();
      renderMeta();

    } catch (error) {
      if (error.name === 'AbortError' || request !== requestNumber) return;
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
    } finally { loading?.finish(); }
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

    const html = searchResults.map((result, index) => {
      const moduleLabel = moduleLabels[result.module] || result.module;
      const moduleColor = moduleColors[result.module] || '#6B7280';
      const title = highlightText(result.title || '无标题', currentQuery);
      const summary = result.summary ? highlightText(result.summary, currentQuery) : '';
      const date = result.date ? (typeof fmtDateCN === 'function' ? fmtDateCN(result.date) : result.date) : '';

      return `
        <div class="search-result-item" role="button" tabindex="0" data-index="${index}" data-module="${esc(result.module)}" data-id="${esc(result.id)}">
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
        navigateToResult(searchResults[Number(item.dataset.index)]);
      });
      item.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); item.click(); }
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
      container.textContent = warnings.length ? '部分内容暂时无法读取，当前范围内未找到结果；可重试。' : '未找到相关结果';
    } else {
      const start = (currentPage - 1) * currentPageSize + 1;
      const end = Math.min(currentPage * currentPageSize, totalResults);
      container.textContent = `找到 ${totalResults} 条结果，显示 ${start}-${end}` + (warnings.length ? ' · 部分内容暂时无法读取，可重试以补齐结果。' : '');
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
  async function navigateToResult(result) {
    if (!result) return;
    const target = result.target || {kind: 'legacy', module: result.module, id: result.id};
    try {
      if (target.kind === 'course' || target.kind === 'plan') {
        return await window.CourseLibrary.open(target.course_key || 'plan:'+target.id);
      }
      if (target.kind === 'study') {
        if (target.module === 'plan') {
          const split = target.course.lastIndexOf('/');
          return await window.openPlanCourse(target.course.slice(0, split), Number(target.course.slice(split + 1)));
        }
        if (target.module === 'renzhi') return await window.openCopilotLesson(Number(target.course));
        window.rememberLearningOrigin?.();
        if (goTab('library') === false) return;
        await window.loadDailyLearning();
        return await window.openStudyCourse(target.module, target.course, {preserveOrigin: true});
      }
      if (target.kind === 'copilot') return await window.openCopilotLesson(target.lesson_no);
      if (target.kind === 'article') {
        if (goTab('reading') === false) return;
        return await window.openActionArticle(target.id);
      }
      if (target.kind === 'reflection') {
        if (goTab('reviews') === false) return;
        if (await window.Reflections.load() === false) throw new Error('日常记录暂时无法读取。');
        return window.Reflections.viewEntry(target.id);
      }
      if (target.kind === 'investment') {
        if (goTab('stocks') === false) return;
        return await window.Investments.openRecord(target);
      }
      if (target.kind === 'action') {
        if (goTab('action-plans') === false) return;
        if (window.ActionPlans.openRecord) return await window.ActionPlans.openRecord(target.id);
        return await window.ActionPlans.enter();
      }
      const tabs = {learning: 'custom', reflection: 'reviews', decision: 'decisions', prediction: 'predictions', review: 'reviews', insight: 'insights', knowledge: 'knowledge'};
      if (goTab(tabs[target.module] || 'custom') === false) return;
      const forms = {decision: ['decisions', 'openDecisionForm'], prediction: ['predictions', 'openPredictionForm'], review: ['reviews', 'openReviewForm'], insight: ['insights', 'openInsightForm'], learning: ['customRecords', 'openRecordForm']};
      const form = forms[target.module];
      if (form && typeof state !== 'undefined') {
        const index = state[form[0]].findIndex(row => String(row.id ?? row._record_id) === String(target.id));
        if (index < 0) throw new Error('原记录已变更，请刷新后重试。');
        return window[form[1]](index);
      }
      if (target.module === 'knowledge') {
        await window.loadKnowledge();
        const filter = document.getElementById('knowledgeSearch');
        if (filter) filter.value = result.title;
        window.renderKnowledgeList();
      }
    } catch (error) { if (typeof toast === 'function') toast('打开记录失败：' + error.message); }
  }
  window.RecordDiscovery = {open: navigateToResult};

  /* ---------- 清空结果 ---------- */
  function clearResults() {
    ++requestNumber; activeRequest?.abort();
    searchResults = [];
    totalResults = 0;
    warnings = [];
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
