/* Unified loading state component for consistent UI feedback */
(() => {
  'use strict';

  const owners = new WeakMap();
  const LoadingState = {
    // Request-owned handle: a late completion must not hide a newer request.
    start(container, message = '正在加载…', detail = '') {
      if (!container) return {finish() {}};
      this.hide(container);
      const el = document.createElement('div');
      el.className = 'loading-state desc';
      el.setAttribute('role', 'status');
      const title = document.createElement('p'); title.textContent = message; el.append(title);
      if (detail) { const hint = document.createElement('p'); hint.textContent = detail; el.append(hint); }
      container.prepend(el); owners.set(container, el); container.setAttribute('aria-busy', 'true');
      return {finish() {
        if (owners.get(container) === el) { container.removeAttribute('aria-busy'); owners.delete(container); }
        el.remove();
      }};
    },
    // Show loading message in a container
    show(container, message = '正在加载…') {
      if (!container) return;
      const existing = container.querySelector('.loading-state');
      if (existing) {
        existing.textContent = message;
        return existing;
      }
      const el = document.createElement('p');
      el.className = 'loading-state desc';
      el.setAttribute('role', 'status');
      el.textContent = message;
      container.prepend(el);
      return el;
    },

    // Hide loading message
    hide(container) {
      if (!container) return;
      const el = container.querySelector('.loading-state');
      if (el) el.remove();
    },

    // Update loading message
    update(container, message) {
      if (!container) return;
      const el = container.querySelector('.loading-state');
      if (el) el.textContent = message;
    },

    // Show error message
    error(container, message, retryCallback = null) {
      if (!container) return;
      this.hide(container);
      const el = document.createElement('p');
      el.className = 'loading-state loading-error';
      el.setAttribute('role', 'alert');
      el.textContent = message;
      if (retryCallback) {
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.className = 'btn';
        retry.textContent = '重试';
        retry.onclick = () => {
          this.show(container, '正在重试…');
          retryCallback();
        };
        el.append(' ', retry);
      }
      container.prepend(el);
      return el;
    },

    // Show success message (auto-hide after delay)
    success(container, message, delay = 2000) {
      if (!container) return;
      this.hide(container);
      const el = document.createElement('p');
      el.className = 'loading-state loading-success';
      el.setAttribute('role', 'status');
      el.textContent = message;
      container.prepend(el);
      if (delay > 0) {
        setTimeout(() => this.hide(container), delay);
      }
      return el;
    }
  };

  window.LoadingState = LoadingState;
})();
