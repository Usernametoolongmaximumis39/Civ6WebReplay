/* Geometry for responsive HUD docks. Floating dimensions stay separate from docks. */
(function (root) {
  "use strict";
  const EDGES = ["left", "right", "bottom"];
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function members(panels, edge) {
    return Object.keys(panels).filter(k => !panels[k].hidden && !panels[k].minimized && panels[k].dock === edge)
      .sort((a, b) => (panels[a].order || 0) - (panels[b].order || 0));
  }

  // Respect readable minimum sizes when possible, and fit even tiny viewports.
  function lengths(keys, panels, total, minimum) {
    const min = Math.min(minimum, total / Math.max(1, keys.length));
    const result = {}, pending = keys.slice();
    let remaining = total;
    while (pending.length) {
      const weight = pending.reduce((sum, k) => sum + (panels[k].weight || 1), 0);
      const small = pending.filter(k => remaining * (panels[k].weight || 1) / weight < min);
      if (!small.length) {
        pending.forEach(k => { result[k] = remaining * (panels[k].weight || 1) / weight; });
        break;
      }
      small.forEach(k => {
        result[k] = min;
        remaining -= min;
        pending.splice(pending.indexOf(k), 1);
      });
    }
    return result;
  }

  function compute(panels, size) {
    const groups = Object.fromEntries(EDGES.map(edge => [edge, members(panels, edge)]));
    const thickness = (edge, axis, fallback) => {
      const key = groups[edge][0];
      if (!key) return 0;
      const st = panels[key];
      const ratio = Number.isFinite(st.dockRatio) ? st.dockRatio
        : edge === "bottom" ? .2 : (st[axis] || fallback) / size[axis];
      return clamp(ratio * size[axis], Math.min(edge === "bottom" ? 140 : 200, size[axis] * .2),
        size[axis] * (edge === "bottom" ? .65 : .6));
    };
    let left = thickness("left", "w", 250), right = thickness("right", "w", 416);
    const bottom = thickness("bottom", "h", 260);
    const budget = size.w * .8;
    if (left + right > budget) {
      const scale = budget / (left + right);
      left *= scale; right *= scale;
    }
    const rects = {}, splitters = [];
    for (const edge of EDGES) {
      const keys = groups[edge], horizontal = edge === "bottom";
      const total = horizontal ? size.w - left - right : size.h;
      const spans = lengths(keys, panels, total, horizontal ? 200 : 140);
      let offset = horizontal ? left : 0;
      keys.forEach((key, i) => {
        const next = offset + spans[key];
        rects[key] = horizontal
          ? { x: Math.round(offset), y: Math.round(size.h - bottom),
              w: Math.round(next) - Math.round(offset), h: Math.round(bottom) }
          : { x: edge === "left" ? 0 : Math.round(size.w - right), y: Math.round(offset),
              w: Math.round(edge === "left" ? left : right), h: Math.round(next) - Math.round(offset) };
        if (i < keys.length - 1) {
          const rect = rects[key];
          splitters.push({ edge, before: key, after: keys[i + 1], total,
            x: horizontal ? Math.round(next) - 3 : rect.x,
            y: horizontal ? rect.y : Math.round(next) - 3,
            w: horizontal ? 6 : rect.w, h: horizontal ? rect.h : 6 });
        }
        offset = next;
      });
    }
    return { rects, groups, splitters, left, right, bottom };
  }
  const api = { EDGES, members, compute };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PanelLayout = api;
})(typeof window !== "undefined" ? window : globalThis);
