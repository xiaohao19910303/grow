/* ================= 主题切换 ================= */
function readThemePreference() {
  try { return localStorage.getItem('theme'); } catch (_) { return null; }
}

function initTheme() {
  // 从 localStorage 读取主题偏好,如果没有则跟随系统
  const saved = readThemePreference();
  if (saved === 'dark' || saved === 'light') {
    document.documentElement.setAttribute('data-theme', saved);
  }
  updateThemeButton();
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  let newTheme;

  if (current === 'dark') {
    newTheme = 'light';
  } else if (current === 'light') {
    newTheme = 'dark';
  } else {
    // 没有手动设置,跟随系统偏好反向切换
    newTheme = prefersDark ? 'light' : 'dark';
  }

  document.documentElement.setAttribute('data-theme', newTheme);
  try { localStorage.setItem('theme', newTheme); } catch (_) { /* Keep this page usable when storage is denied. */ }
  updateThemeButton();
}

function updateThemeButton() {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;

  const current = document.documentElement.getAttribute('data-theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const isDark = current === 'dark' || (current === null && prefersDark);

  btn.textContent = isDark ? '☀️' : '🌙';
  btn.setAttribute('aria-label', isDark ? '切换到明亮模式' : '切换到暗黑模式');
}

// 监听系统主题变化
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (!readThemePreference()) {
    updateThemeButton();
  }
});

// 初始化主题
initTheme();

