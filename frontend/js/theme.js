/**
 * Theme management: dark (default) / light / system.
 *
 * The INITIAL theme is applied by a small blocking inline script in
 * <head> (before first paint) — see index.html — so there is no flash of
 * the wrong theme on load. This file only:
 *   1. Syncs the toggle buttons' active state with whatever mode was
 *      already applied.
 *   2. Handles clicks to switch mode, persisting the choice.
 *   3. Keeps 'system' mode live if the OS preference changes mid-session.
 *
 * `document.documentElement` (the <html> element) is the ONLY element
 * data-theme is ever set on. Previously the <body> tag also hardcoded
 * data-theme="dark" in the markup, which — because CSS custom properties
 * are re-declared by the nearest matching ancestor — silently overrode
 * whatever theme was applied to <html> for every component inside <body>.
 * That mismatch was the root cause of the "theme switch doesn't fully
 * apply" bug. Do not reintroduce a data-theme attribute anywhere but
 * <html>.
 */
(function () {
  const STORAGE_KEY = 'ridp:theme';
  const root = document.documentElement;

  function systemPrefersDark() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function applyTheme(mode) {
    const resolved = mode === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : mode;
    root.setAttribute('data-theme', resolved);
    root.dataset.themeMode = mode;
    document.querySelectorAll('.theme-toggle button').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });
  }

  function syncButtonsToCurrentMode() {
    const currentMode = root.dataset.themeMode || localStorage.getItem(STORAGE_KEY) || 'dark';
    document.querySelectorAll('.theme-toggle button').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.mode === currentMode);
    });
  }

  function initTheme() {
    // The inline blocking script already set data-theme/data-theme-mode
    // before paint — just sync the UI and wire up interactions.
    syncButtonsToCurrentMode();

    document.querySelectorAll('.theme-toggle button').forEach((btn) => {
      btn.addEventListener('click', () => {
        localStorage.setItem(STORAGE_KEY, btn.dataset.mode);
        applyTheme(btn.dataset.mode);
      });
    });

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (root.dataset.themeMode === 'system') applyTheme('system');
    });
  }

  document.addEventListener('DOMContentLoaded', initTheme);
})();
