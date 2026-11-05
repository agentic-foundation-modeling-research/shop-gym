// Light, dark or system color theme for every report page, kept per browser.
// Loaded in <head> so the theme is set before the first paint.
(() => {
  const KEY = 'shopgym-reports-theme';
  const MODES = ['system', 'light', 'dark'];
  const LABELS = { system: 'System', light: 'Light', dark: 'Dark' };
  const root = document.documentElement;

  function stored() {
    try {
      const mode = localStorage.getItem(KEY);
      return MODES.includes(mode) ? mode : 'system';
    } catch {
      return 'system';
    }
  }

  function apply(mode) {
    if (mode === 'system') {
      delete root.dataset.theme;
    } else {
      root.dataset.theme = mode;
    }
    const button = document.getElementById('theme-toggle');
    if (button !== null) {
      button.textContent = LABELS[mode];
      button.title = `Color theme: ${LABELS[mode]}. Click to change.`;
    }
  }

  let mode = stored();
  apply(mode);
  document.addEventListener('DOMContentLoaded', () => apply(mode));
  document.addEventListener('click', (event) => {
    if (!(event.target instanceof Element) || event.target.closest('#theme-toggle') === null) {
      return;
    }
    mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      // Storage is blocked: the choice holds for this page only.
    }
    apply(mode);
  });
})();
