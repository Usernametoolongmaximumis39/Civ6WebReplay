/* Safe, offline rendering of Civ6 policy and ability descriptions. */
(function () {
  "use strict";
  const L = value => window.Civ6I18n ? window.Civ6I18n.text(value) : value;
  const escape = value => String(value || "").replace(/[&<>"']/g, c =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

  function render(text, profile = "vanilla") {
    if (!text) return L('<span class="muted">尚未采集当前规则集的说明文本。</span>');
    const clean = String(text).replace(/\[(?:COLOR[^\]]*|ENDCOLOR|BOLD|ENDBOLD)\]/gi, "")
      .replace(/\[NEWLINE\]/gi, "\n").replace(/([。；])(?=\S)/g, "$1\n");
    return escape(clean).replace(/\[ICON_([A-Za-z0-9_]+)\]/gi, (marker, raw) => {
      const key = raw.toUpperCase();
      const entry = (window.Civ6TextIcons || {})[key];
      const icon = entry && { ...entry, ...(entry.profiles || {})[profile.toLowerCase()] };
      // Preserve future/unknown markers so an unsupported symbol cannot vanish.
      if (!icon || !icon.icon) return `${L("<span class=\"rule-text-missing\" title=\"尚未收录的图标\">")}${marker}</span>`;
      return `<img class="rule-text-icon" data-text-icon="${key}" ` +
        `src="/assets/icons/${escape(icon.icon)}" alt="${escape(L(icon.label))}" title="${escape(L(icon.label))}">`;
    });
  }
  window.Civ6RuleText = Object.freeze({ render });
})();
