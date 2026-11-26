/* Operator Wall theme switch: light by default, choice kept in localStorage. Loaded in <head> so the first paint is already themed. */
(() => {
  const KEY = "jit-wall-theme";
  const THEMES = ["light", "dark"];
  const stored = () => { try { return localStorage.getItem(KEY); } catch (err) { return null; } };
  const apply = (theme) => {
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll("[data-theme-pick]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.themePick === theme)));
  };
  const initial = THEMES.includes(stored()) ? stored() : "light";
  apply(initial);
  document.addEventListener("DOMContentLoaded", () => {
    apply(initial);
    document.querySelectorAll("[data-theme-pick]").forEach((b) => b.addEventListener("click", () => {
      try { localStorage.setItem(KEY, b.dataset.themePick); } catch (err) { /* private mode: keep the choice for this page only */ }
      apply(b.dataset.themePick);
    }));
  });
})();
