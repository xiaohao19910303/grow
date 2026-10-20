/**
 * 股票复盘模块前端逻辑 - 优化版
 */

class StocksModule {
  constructor() {
    this.records = [];
    this.statistics = {};
    this.currentFilter = null;
    this.editingId = null;
    this.formContainer = null;
  }

  async init() {
    this.formContainer = document.getElementById('stocks-form-container');
    await this.loadRecords();
    this.render();
    this.bindEvents();
    this.setupKeyboardShortcuts();
  }

  async loadRecords() {
    try {
      const response = await fetch('/api/stocks', {
        headers: { 'X-Copilot-Request': '1' }
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      this.records = data.records || [];
      this.statistics = data.statistics || {};
    } catch (err) {
      console.error('加载股票记录失败:', err);
      this.showToast('加载失败，请刷新页面重试', 'error');
    }
  }

  render() {
    const container = document.getElementById('stocks-container');
    if (!container) return;

    let filtered = this.records;
    if (this.currentFilter) {
      filtered = this.records.filter(r => r.outcome === this.currentFilter);
    }

    container.innerHTML = `
      <div class="stocks-container">
        ${this.renderStatistics()}
        <div class="stocks-actions">
          <button class="btn primary" id="btn-new-stock" title="创建新的股票记录 (Ctrl+N)">
            <span>+</span> 新建股票记录
          </button>
          <button class="btn" id="btn-refresh" title="刷新数据 (Ctrl+R)">
            <span>↻</span> 刷新
          </button>
        </div>
        <div class="stocks-filter">
          <button class="filter-btn ${!this.currentFilter ? 'active' : ''}" data-filter="">全部</button>
          <button class="filter-btn ${this.currentFilter === 'pending' ? 'active' : ''}" data-filter="pending">进行中</button>
          <button class="filter-btn ${this.currentFilter === 'success' ? 'active' : ''}" data-filter="success">成功</button>
          <button class="filter-btn ${this.currentFilter === 'failure' ? 'active' : ''}" data-filter="failure">失败</button>
        </div>
        <div id="stocks-form-container"></div>
        <div class="stocks-list">
          ${filtered.length === 0 ? this.renderEmpty() : filtered.map(r => this.renderCard(r)).join('')}
        </div>
      </div>
    `;

    this.bindCardEvents();
  }

  renderStatistics() {
    const stats = this.statistics;
    const profitClass = (stats.total_profit_loss || 0) >= 0 ? 'profit' : 'loss';
    const profitPrefix = (stats.total_profit_loss || 0) >= 0 ? '+' : '';

    return `
      <div class="stocks-stats">
        <div class="stat-card" title="总记录数">
          <div class="stat-value">${stats.total || 0}</div>
          <div class="stat-label">总记录</div>
        </div>
        <div class="stat-card" title="进行中的记录">
          <div class="stat-value">${stats.pending || 0}</div>
          <div class="stat-label">进行中</div>
        </div>
        <div class="stat-card" title="成功的记录">
          <div class="stat-value profit">${stats.successes || 0}</div>
          <div class="stat-label">成功</div>
        </div>
        <div class="stat-card" title="失败的记录">
          <div class="stat-value loss">${stats.failures || 0}</div>
          <div class="stat-label">失败</div>
        </div>
        <div class="stat-card" title="成功率">
          <div class="stat-value">${stats.success_rate ? (stats.success_rate * 100).toFixed(0) : 0}%</div>
          <div class="stat-label">成功率</div>
        </div>
        <div class="stat-card" title="总盈亏">
          <div class="stat-value ${profitClass}">${profitPrefix}¥${(stats.total_profit_loss || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</div>
          <div class="stat-label">总盈亏</div>
        </div>
      </div>
    `;
  }

  renderCard(record) {
    const actionMap = { buy: '买入', sell: '卖出', hold: '持有' };
    const outcomeMap = { pending: '进行中', success: '成功', failure: '失败' };

    let profitLossHtml = '';
    if (record.profit_loss !== null && record.profit_loss !== undefined) {
      const plClass = record.profit_loss >= 0 ? 'positive' : 'negative';
      const plPrefix = record.profit_loss >= 0 ? '+' : '';
      profitLossHtml = `
        <div class="profit-loss ${plClass}">
          盈亏: ${plPrefix}¥${record.profit_loss.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}
        </div>
      `;
    }

    let outcomeHtml = '';
    if (record.outcome && record.outcome !== 'pending') {
      outcomeHtml = `
        <div class="stock-outcome">
          <span class="outcome-badge ${record.outcome}">${outcomeMap[record.outcome]}</span>
          ${record.result_date ? `<span style="margin-left:8px;color:var(--muted);font-size:12px;">${record.result_date}</span>` : ''}
          ${profitLossHtml}
          ${record.retrospective ? `
            <div style="margin-top:12px;font-size:13px;color:var(--muted);line-height:1.6;">
              ${record.retrospective.what_went_right ? `<div style="margin-bottom:6px;"><strong style="color:var(--text);">做对了:</strong> ${this.escapeHtml(record.retrospective.what_went_right)}</div>` : ''}
              ${record.retrospective.what_went_wrong ? `<div style="margin-bottom:6px;"><strong style="color:var(--text);">做错了:</strong> ${this.escapeHtml(record.retrospective.what_went_wrong)}</div>` : ''}
              ${record.retrospective.lessons_learned ? `<div style="margin-bottom:6px;"><strong style="color:var(--text);">教训:</strong> ${this.escapeHtml(record.retrospective.lessons_learned)}</div>` : ''}
              ${record.retrospective.pattern ? `<div><strong style="color:var(--text);">模式:</strong> ${this.escapeHtml(record.retrospective.pattern)}</div>` : ''}
            </div>
          ` : ''}
        </div>
      `;
    }

    return `
      <div class="stock-card" data-id="${record.id}">
        <div class="stock-header">
          <div>
            <div class="stock-title">${this.escapeHtml(record.stock_name)}</div>
            <div class="stock-code">${this.escapeHtml(record.stock_code)}</div>
          </div>
          <span class="stock-action ${record.action}">${actionMap[record.action]}</span>
        </div>
        <div class="stock-meta">
          <span>📅 ${record.date}</span>
          <span>💰 ¥${record.price.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</span>
          ${record.quantity ? `<span>📊 ${record.quantity}股</span>` : ''}
          ${record.target_price ? `<span>🎯 ¥${record.target_price.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</span>` : ''}
          ${record.stop_loss ? `<span>🛡️ ¥${record.stop_loss.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</span>` : ''}
          ${record.confidence ? `<span>💪 ${(record.confidence * 100).toFixed(0)}%</span>` : ''}
        </div>
        ${record.rationale ? `<div class="stock-rationale">${this.escapeHtml(record.rationale)}</div>` : ''}
        ${record.tags && record.tags.length > 0 ? `
          <div class="stock-tags">
            ${record.tags.map(tag => `<span class="tag">${this.escapeHtml(tag)}</span>`).join('')}
          </div>
        ` : ''}
        ${outcomeHtml}
        <div class="stock-actions-bar">
          ${record.outcome === 'pending' ? `
            <button class="btn-small primary" data-action="update-outcome" data-id="${record.id}" title="更新结果和复盘">更新结果</button>
          ` : ''}
          <button class="btn-small" data-action="edit" data-id="${record.id}" title="编辑记录">编辑</button>
          <button class="btn-small" data-action="delete" data-id="${record.id}" title="删除记录">删除</button>
        </div>
      </div>
    `;
  }

  renderEmpty() {
    return `
      <div class="empty-state">
        <div class="empty-state-icon">📊</div>
        <div class="empty-state-title">暂无股票记录</div>
        <div class="empty-state-description">点击"新建股票记录"开始记录你的投资操作</div>
        <button class="btn primary" onclick="document.getElementById('btn-new-stock').click()">
          创建第一条记录
        </button>
      </div>
    `;
  }

  renderForm(editRecord = null) {
    const isEdit = !!editRecord;
    const title = isEdit ? '编辑股票记录' : '新建股票记录';
    const r = editRecord || {};

    return `
      <div class="stock-form">
        <div class="form-title">${title}</div>
        <form id="stock-form" novalidate>
          <div class="form-grid">
            <div class="form-field">
              <label>股票代码 *</label>
              <input type="text" name="stock_code" value="${this.escapeHtml(r.stock_code || '')}" required maxlength="20" placeholder="如 600519" autocomplete="off">
            </div>
            <div class="form-field">
              <label>股票名称 *</label>
              <input type="text" name="stock_name" value="${this.escapeHtml(r.stock_name || '')}" required maxlength="100" placeholder="如 贵州茅台" autocomplete="off">
            </div>
            <div class="form-field">
              <label>操作类型 *</label>
              <select name="action" required>
                <option value="buy" ${r.action === 'buy' ? 'selected' : ''}>买入</option>
                <option value="sell" ${r.action === 'sell' ? 'selected' : ''}>卖出</option>
                <option value="hold" ${r.action === 'hold' ? 'selected' : ''}>持有</option>
              </select>
            </div>
            <div class="form-field">
              <label>操作日期 *</label>
              <input type="date" name="date" value="${this.escapeHtml(r.date || new Date().toISOString().split('T')[0])}" required>
            </div>
            <div class="form-field">
              <label>价格 *</label>
              <input type="number" name="price" value="${r.price || ''}" required step="0.01" min="0" placeholder="如 1800.50">
            </div>
            <div class="form-field">
              <label>数量</label>
              <input type="number" name="quantity" value="${r.quantity || ''}" step="1" min="0" placeholder="如 100">
            </div>
            <div class="form-field">
              <label>目标价</label>
              <input type="number" name="target_price" value="${r.target_price || ''}" step="0.01" min="0" placeholder="如 2000">
            </div>
            <div class="form-field">
              <label>止损价</label>
              <input type="number" name="stop_loss" value="${r.stop_loss || ''}" step="0.01" min="0" placeholder="如 1600">
            </div>
            <div class="form-field">
              <label>信心 (0-1)</label>
              <input type="number" name="confidence" value="${r.confidence || ''}" step="0.01" min="0" max="1" placeholder="如 0.7">
            </div>
            <div class="form-field">
              <label>标签</label>
              <input type="text" name="tags" value="${this.escapeHtml((r.tags || []).join(', '))}" placeholder="如 白酒, 消费升级">
            </div>
            <div class="form-field full-width">
              <label>操作理由</label>
              <textarea name="rationale" maxlength="5000" placeholder="记录你的投资理由和逻辑...">${this.escapeHtml(r.rationale || '')}</textarea>
            </div>
          </div>
          <div class="form-actions">
            <button type="button" class="btn" id="btn-cancel-form">取消</button>
            <button type="submit" class="btn primary">${isEdit ? '保存修改' : '创建记录'}</button>
          </div>
        </form>
      </div>
    `;
  }

  renderOutcomeForm(record) {
    return `
      <div class="retrospective-form">
        <h4>更新结果与复盘</h4>
        <form id="outcome-form" data-id="${record.id}" novalidate>
          <div class="form-grid">
            <div class="form-field">
              <label>结果 *</label>
              <select name="outcome" required>
                <option value="success">成功</option>
                <option value="failure">失败</option>
              </select>
            </div>
            <div class="form-field">
              <label>实际价格 *</label>
              <input type="number" name="actual_price" required step="0.01" min="0" placeholder="如 1950">
            </div>
            <div class="form-field">
              <label>结果日期 *</label>
              <input type="date" name="result_date" value="${new Date().toISOString().split('T')[0]}" required>
            </div>
            <div class="form-field full-width">
              <label>做对了什么</label>
              <textarea name="what_went_right" placeholder="记录你做对的决策或判断..."></textarea>
            </div>
            <div class="form-field full-width">
              <label>做错了什么</label>
              <textarea name="what_went_wrong" placeholder="记录你做错的决策或判断..."></textarea>
            </div>
            <div class="form-field full-width">
              <label>学到的教训</label>
              <textarea name="lessons_learned" placeholder="记录你从这次投资中学到的教训..."></textarea>
            </div>
            <div class="form-field full-width">
              <label>投资模式</label>
              <input type="text" name="pattern" placeholder="如 value_investing, momentum, event_driven">
            </div>
          </div>
          <div class="form-actions">
            <button type="button" class="btn" id="btn-cancel-outcome">取消</button>
            <button type="submit" class="btn primary">保存结果</button>
          </div>
        </form>
      </div>
    `;
  }

  bindEvents() {
    document.getElementById('btn-new-stock')?.addEventListener('click', () => {
      this.formContainer.innerHTML = this.renderForm();
      this.bindFormEvents();
      this.focusFirstField();
    });

    document.getElementById('btn-refresh')?.addEventListener('click', async () => {
      await this.loadRecords();
      this.render();
      this.showToast('数据已刷新', 'success');
    });

    document.querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.currentFilter = btn.dataset.filter || null;
        this.render();
      });
    });
  }

  bindCardEvents() {
    document.querySelectorAll('[data-action="edit"]').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        const record = this.records.find(r => r.id === id);
        if (record) {
          this.formContainer.innerHTML = this.renderForm(record);
          this.editingId = id;
          this.bindFormEvents();
          this.focusFirstField();
        }
      });
    });

    document.querySelectorAll('[data-action="update-outcome"]').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        const record = this.records.find(r => r.id === id);
        if (record) {
          this.formContainer.innerHTML = this.renderOutcomeForm(record);
          this.bindOutcomeFormEvents();
          this.focusFirstField();
        }
      });
    });

    document.querySelectorAll('[data-action="delete"]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        const record = this.records.find(r => r.id === id);
        if (record && confirm(`确定要删除 ${record.stock_name} (${record.stock_code}) 的记录吗？此操作不可撤销。`)) {
          await this.deleteRecord(id);
        }
      });
    });
  }

  bindFormEvents() {
    const form = document.getElementById('stock-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      if (!this.validateForm(form)) {
        return;
      }

      const formData = new FormData(form);
      const data = {
        stock_code: formData.get('stock_code').trim(),
        stock_name: formData.get('stock_name').trim(),
        action: formData.get('action'),
        date: formData.get('date'),
        price: parseFloat(formData.get('price')),
        quantity: formData.get('quantity') ? parseInt(formData.get('quantity')) : null,
        target_price: formData.get('target_price') ? parseFloat(formData.get('target_price')) : null,
        stop_loss: formData.get('stop_loss') ? parseFloat(formData.get('stop_loss')) : null,
        confidence: formData.get('confidence') ? parseFloat(formData.get('confidence')) : null,
        rationale: formData.get('rationale').trim(),
        tags: formData.get('tags').split(',').map(t => t.trim()).filter(t => t)
      };

      if (this.editingId) {
        await this.updateRecord(this.editingId, data);
      } else {
        await this.createRecord(data);
      }
    });

    document.getElementById('btn-cancel-form')?.addEventListener('click', () => {
      this.formContainer.innerHTML = '';
      this.editingId = null;
    });
  }

  bindOutcomeFormEvents() {
    const form = document.getElementById('outcome-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      if (!this.validateForm(form)) {
        return;
      }

      const formData = new FormData(form);
      const id = form.dataset.id;
      const data = {
        outcome: formData.get('outcome'),
        actual_price: parseFloat(formData.get('actual_price')),
        result_date: formData.get('result_date'),
        retrospective: {
          what_went_right: formData.get('what_went_right').trim(),
          what_went_wrong: formData.get('what_went_wrong').trim(),
          lessons_learned: formData.get('lessons_learned').trim(),
          pattern: formData.get('pattern').trim()
        }
      };

      await this.updateOutcome(id, data);
    });

    document.getElementById('btn-cancel-outcome')?.addEventListener('click', () => {
      this.formContainer.innerHTML = '';
    });
  }

  validateForm(form) {
    const inputs = form.querySelectorAll('[required]');
    let isValid = true;

    inputs.forEach(input => {
      if (!input.value.trim()) {
        input.style.borderColor = 'var(--red)';
        isValid = false;
      } else {
        input.style.borderColor = '';
      }
    });

    if (!isValid) {
      this.showToast('请填写所有必填字段', 'error');
    }

    return isValid;
  }

  async createRecord(data) {
    try {
      const response = await fetch('/api/stocks', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Copilot-Request': '1'
        },
        body: JSON.stringify(data)
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || '创建失败');
      }

      await this.loadRecords();
      this.render();
      this.formContainer.innerHTML = '';
      this.showToast('记录创建成功', 'success');
    } catch (err) {
      console.error('创建股票记录失败:', err);
      this.showToast('创建失败: ' + err.message, 'error');
    }
  }

  async updateRecord(id, data) {
    try {
      const response = await fetch(`/api/stocks/${id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'X-Copilot-Request': '1'
        },
        body: JSON.stringify(data)
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || '更新失败');
      }

      await this.loadRecords();
      this.render();
      this.formContainer.innerHTML = '';
      this.editingId = null;
      this.showToast('记录更新成功', 'success');
    } catch (err) {
      console.error('更新股票记录失败:', err);
      this.showToast('更新失败: ' + err.message, 'error');
    }
  }

  async updateOutcome(id, data) {
    try {
      const response = await fetch(`/api/stocks/${id}/outcome`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Copilot-Request': '1'
        },
        body: JSON.stringify(data)
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || '更新结果失败');
      }

      await this.loadRecords();
      this.render();
      this.formContainer.innerHTML = '';
      this.showToast('结果更新成功', 'success');
    } catch (err) {
      console.error('更新结果失败:', err);
      this.showToast('更新失败: ' + err.message, 'error');
    }
  }

  async deleteRecord(id) {
    try {
      const response = await fetch(`/api/stocks/${id}`, {
        method: 'DELETE',
        headers: { 'X-Copilot-Request': '1' }
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.message || '删除失败');
      }

      await this.loadRecords();
      this.render();
      this.showToast('记录已删除', 'success');
    } catch (err) {
      console.error('删除股票记录失败:', err);
      this.showToast('删除失败: ' + err.message, 'error');
    }
  }

  showToast(message, type = 'info') {
    // 移除已存在的 toast
    const existing = document.querySelector('.stock-toast');
    if (existing) {
      existing.remove();
    }

    const toast = document.createElement('div');
    toast.className = `stock-toast stock-toast-${type}`;
    toast.textContent = message;
    toast.style.cssText = `
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%) translateY(20px);
      background: ${type === 'error' ? 'var(--red)' : type === 'success' ? 'var(--green)' : 'var(--text)'};
      color: #fff;
      padding: 10px 18px;
      border-radius: 10px;
      font-size: 13px;
      opacity: 0;
      transition: 0.25s;
      z-index: 200;
      pointer-events: none;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    `;
    document.body.appendChild(toast);

    requestAnimationFrame(() => {
      toast.style.opacity = '1';
      toast.style.transform = 'translateX(-50%) translateY(0)';
    });

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(-50%) translateY(20px)';
      setTimeout(() => toast.remove(), 250);
    }, 3000);
  }

  focusFirstField() {
    const firstInput = this.formContainer.querySelector('input, select, textarea');
    if (firstInput) {
      firstInput.focus();
    }
  }

  setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      if (!this.formContainer || document.getElementById('view-stocks')?.style.display === 'none') return;
      // Ctrl+N: 新建记录
      if ((e.ctrlKey || e.metaKey) && e.key === 'n' && !this.formContainer.innerHTML) {
        e.preventDefault();
        document.getElementById('btn-new-stock')?.click();
      }

      // Ctrl+R: 刷新（当在 stocks 页面时）
      if ((e.ctrlKey || e.metaKey) && e.key === 'r' && document.getElementById('stocks-container')) {
        e.preventDefault();
        document.getElementById('btn-refresh')?.click();
      }

      // Escape: 关闭表单
      if (e.key === 'Escape' && this.formContainer.innerHTML) {
        this.formContainer.innerHTML = '';
        this.editingId = null;
      }
    });
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

// 全局初始化
window.stocksModule = null;

window.initStocksModule = async function() {
  if (window.stocksModule) return;
  window.stocksModule = new StocksModule();
  await window.stocksModule.init();
};

// 页面加载时自动初始化（如果在投资复盘页面）
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('stocks-container')) {
    window.initStocksModule();
  }
});
