/* Language selection and source-literal translation. Runtime game/user text is
   localized by the API, never by scanning arbitrary DOM contents. */
(function () {
  "use strict";
  const key = "civ6replay.language.v1";
  let preference;
  try { preference = localStorage.getItem(key); } catch (_) {}
  if (!["auto", "zh", "en"].includes(preference)) preference = "auto";
  function detect(languages) {
    for (const candidate of languages || []) {
      const base = String(candidate).toLowerCase().split(/[-_]/)[0];
      if (base === "zh" || base === "en") return base;
    }
    return "en";
  }
  let language = preference === "auto" ? detect(navigator.languages || [navigator.language]) : preference;
  const strings = window.Civ6UIStrings || {};
  function text(value) {
    const raw = String(value);
    if (language !== "en") return raw;
    if (Object.prototype.hasOwnProperty.call(strings, raw)) return strings[raw];
    // Translate only complete static text / attribute fragments. Interpolated
    // names and rule descriptions never enter this function from a renderer.
    return raw.replace(/[^<>"'\r\n]+/g, part => {
      const trimmed = part.trim();
      if (!Object.prototype.hasOwnProperty.call(strings, trimmed)) return part;
      const leading = part.match(/^\s*/)[0], trailing = part.match(/\s*$/)[0];
      return leading + strings[trimmed] + trailing;
    });
  }
  function staticText() {
    document.documentElement.lang = language === "zh" ? "zh-Hans" : "en";
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }
    for (const node of nodes) {
      if (["SCRIPT", "STYLE"].includes(node.parentElement.tagName)) continue;
      if (node.parentElement.hasAttribute("data-i18n")) continue;
      if (/[\u3400-\u9fff]/.test(node.textContent)) {
        const original = node.textContent;
        const span = document.createElement("span");
        span.dataset.i18n = original;
        span.textContent = text(original);
        node.replaceWith(span);
      }
    }
    for (const node of document.querySelectorAll("[title],[placeholder],[aria-label]")) {
      for (const attr of ["title", "placeholder", "aria-label"]) {
        const raw = node.getAttribute(attr);
        if (raw && /[\u3400-\u9fff]/.test(raw)) {
          node.setAttribute("data-i18n-" + attr, raw);
          node.setAttribute(attr, text(raw));
        }
      }
    }
  }
  function updateStatic() {
    document.documentElement.lang = language === "zh" ? "zh-Hans" : "en";
    for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = text(node.dataset.i18n);
    for (const attr of ["title", "placeholder", "aria-label"]) {
      for (const node of document.querySelectorAll("[data-i18n-" + attr + "]"))
        node.setAttribute(attr, text(node.getAttribute("data-i18n-" + attr)));
    }
    const select = document.getElementById("language-select");
    if (select) select.value = preference;
  }
  function set(value) {
    if (!["auto", "zh", "en"].includes(value)) return;
    preference = value;
    try { localStorage.setItem(key, value); } catch (_) {}
    const next = value === "auto" ? detect(navigator.languages || [navigator.language]) : value;
    const changed = next !== language;
    language = next;
    updateStatic();
    if (changed) window.dispatchEvent(new CustomEvent("civ6-language-change"));
  }
  function url(raw) {
    const address = new URL(raw, location.href);
    if (address.origin === location.origin && address.pathname.startsWith("/api/"))
      address.searchParams.set("lang", language);
    return address.href;
  }
  function format(template, values) {
    return text(template).replace(/\{([A-Za-z0-9_]+)\}/g, (marker, name) =>
      Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : marker);
  }
  window.Civ6I18n = Object.freeze({ text, format, detect, set, url,
    get language() { return language; }, get preference() { return preference; } });
  document.documentElement.lang = language === "zh" ? "zh-Hans" : "en";
  // Runs before application scripts and before the first rendering opportunity.
  window.Civ6I18nInit = () => {
    staticText(); updateStatic();
    document.getElementById("language-select").onchange = event => set(event.target.value);
  };
  window.addEventListener("languagechange", () => { if (preference === "auto") set("auto"); });
  window.addEventListener("storage", event => {
    if (event.key === key) set(event.newValue || "auto");
  });
})();
