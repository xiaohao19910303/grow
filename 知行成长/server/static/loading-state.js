/* Unified loading state component for consistent UI feedback */
(() => {
  'use strict';

  const requests = new WeakMap();
  const LoadingState = {
    // Each request owns its indicator; late completions cannot hide newer work.
    start(container, message = '正在加载…', detail = '') {
      if (!container) return {finish() {}};
      const previous = requests.get(container);
      const busy = previous ? previous.busy : container.getAttribute('aria-busy');
      container.querySelector('.loading-state')?.remove();
      const el = document.createElement('div');
      el.className = 'loading-state page-loading';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      const spinner = document.createElement('span');
      spinner.className = 'page-loading-spinner';spinner.setAttribute('aria-hidden', 'true');
      const text = document.createElement('div'), title = document.createElement('strong');
      title.textContent = message;text.append(title);
      if (detail) { const description = document.createElement('p');description.textContent = detail;text.append(description); }
      el.append(spinner, text);container.prepend(el);container.setAttribute('aria-busy', 'true');
      const owner = {busy};requests.set(container, owner);
      return {finish() {
        el.remove();
        if (requests.get(container) !== owner) return;
        requests.delete(container);
        if (busy === null) container.removeAttribute('aria-busy');else container.setAttribute('aria-busy', busy);
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
