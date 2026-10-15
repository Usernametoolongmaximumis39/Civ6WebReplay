/* Civ6 复盘工具 - application logic. */
(function () {
  "use strict";
  const L = value => window.Civ6I18n ? window.Civ6I18n.text(value) : value;

  const $ = (id) => document.getElementById(id);
  let YIELD_BY_NAME = {};

  // v0.25 (文档 C): the renderer owns the layer list (``HexMap.LAYERS``) so the
  // toggles can never drift out of order or miss a layer.
  let LAYER_KEYS = HexMap.LAYERS.map(([key, label]) => [key, L(label)]);
  const LAYER_STORE = "civ6replay.layers.v1";
  const MAP_VIEW_STORE = "civ6replay.mapView.v1";
  let savedMapView = loadMapView();
  let savedMapViewJSON = JSON.stringify(savedMapView);
  let mapViewReady = false;

  // v0.22 hard-coded small tables for the header meta line.
  let MAPSIZE_ZH;
  let GAMESPEED_ZH;

  // v0.22 fixed icon-row paths (mirrors the in-game yield strip)
  const ICON_CITY = "/assets/icons/icon/settle.png";
  const ICON_POPULATION = "/assets/icons/icon/Population.png";
  const ICON_MIL = "/assets/icons/icon/Strength.png";
  const ICON_FOOD = "/assets/icons/yield/Food.png";
  const ICON_PROD = "/assets/icons/yield/Production.png";
  const ICON_SCI = "/assets/icons/yield/Science.png";
  const ICON_CUL = "/assets/icons/yield/Culture.png";
  const ICON_GOLD = "/assets/icons/yield/gold.png";
  const ICON_FAITH = "/assets/icons/yield/Faith.png";
  const ICON_DIPLO = "/assets/icons/icon/Diplomatic_Favor.png";
  // 单位晋升图标 = 游戏里 [ICON_PROMOTION] 那一枚（Icons_Stats.xml：ICON_PROMOTION =
  // ICON_ATLAS_STATS 的 Index 7，"盾形内四角星"），由 tools/vendor_promotion_icon.py 裁出
  const ICON_PROMOTION = "/assets/icons/icon/promotion.png";
  const GDR_PROMOTION_TECHS = new Set([
    "TECH_ADVANCED_AI", "TECH_ADVANCED_POWER_CELLS", "TECH_CYBERNETICS", "TECH_SMART_MATERIALS",
  ]);
  // 使者图标 = 游戏里 [ICON_Envoy] 那一枚（FontIcons.xml：Envoy =
  // ICON_ATLAS_FONT_ICON_BASELINE_6 的 Index 25），由 tools/vendor_envoy_icon.py 裁出
  const ICON_ENVOY = "/assets/icons/icon/envoy.png";
  // v0.40: 尤里卡 / 鼓舞 / 旅游业绩三枚图标（游戏里对应 [ICON_Eureka] /
  // [ICON_Inspiration] / [ICON_Tourism]），已随 `assets/icons/icon` 入库
  const ICON_EUREKA = "/assets/icons/icon/Eureka.png";
  const ICON_INSPIRATION = "/assets/icons/icon/Inspiration.png";
  const ICON_TOURISM = "/assets/icons/icon/Tourism.png";
  // v0.40.1: 存档里的旅游业绩是定点整数，**1 点 = 256**（一开始按 1024 算是错的，
  // 实测见 README v0.40：「罗马（图拉真）回合 90 对匈牙利累积 407680 → 1592.5，
  // 加上当回合的 11.5 正好是游戏文化面板 tooltip 上的 1,604」）。
  const TOURISM_FIXED = 256;
  // v0.40.1: 每个对手的流量 = 基准值 × 该对手的旅游修正（开边 +25%、商路 +25%、
  // 不同政体 -50%、启蒙运动使宗教旅游 -50%、两者叠加还会出现 -90% …），所以基准值
  // 要从一组流量里反推：从大到小挑候选 B，谁的「能被 B×m 解释」的流量够多（≥ 2/3）
  // 就取谁 —— 逆修正（-50%）通常落在多数对手身上，取最小 / 取众数都会偏小，
  // 而「能自洽的最大候选」在实测里与游戏顶栏对得上（见 README v0.40 的手动验收）。
  const TOURISM_MODS = [0.1, 0.25, 0.5, 0.625, 0.75, 0.875, 1, 1.25, 1.5, 1.75, 2];
  const DISTRICT_CITY_CENTER = 2318532733;
  const DISTRICT_WONDER = 0x62F1B509;
  // 城墙上限 / 城市防御（钢铁）值都来自快照（static_info.wallDefense），见 cityWall()。
  // v0.25 (文档 C2): age state -> icon stem / Chinese label
  const AGE_ICON = { 0: "Dark", 1: "Normal", 2: "Golden", 3: "Heroic" };
  let AGE_ZH;
  // v0.26 右栏文明卡排序（城邦页维持既有排序）
  let CIV_SORT_OPTIONS;
  const CITY_CENTER_HP = 200;
  // v0.23 city-state page order (mirrors state.CITY_STATE_FLAVOUR_ORDER)
  let CS_FLAVOUR_ORDER;
  const DIPLO_VICTORY_MAX = 20;
  // v0.28: 每个宗教最多 4 条信条（创立时 2 条，之后用使徒再补 2 条），
  // 用于宗教区里的「信条 N / 4」——一眼看出这个宗教还差没补满。
  const BELIEF_MAX = 4;

  let map, staticInfo = null, turns = [], currentTurn = null, seed = null;
  let names = {}; const turnCache = new Map(); const TURN_CACHE_MAX = 10;
  let replaySeq = 0, turnSeq = 0;

  let activeTab = "terrain";
  let hudTab = "civ";
  // Standalone comparison opens in its own tab with turn navigation only.
  const urlParams = new URLSearchParams(location.search);
  const wantCompare = urlParams.get("compare") === "1";
  const compareMode = wantCompare;
  let showType = localStorage.getItem("civ6replay.showType") === "1";
  // v0.25: unit coordinates are an optional, non-critical detail (off by default)
  let showCoord = localStorage.getItem("civ6replay.showCoord") === "1";
  let CAT_ZH;

  // v0.22 state: slider load mask, expanded HUD rows
  // (v0.25 文档 C2: the per-turn diplomacy favours were dropped with the row)
  let loadstate = null, loadPoller = null;
  const expanded = {};

  // v0.27: continents are shown by name only (no "大陆 N" numbering)

  // v0.25 (文档 C4): left-sidebar search state (v0.26 adds the exclude box)
  let searchQuery = "", searchExclude = "";
  let searchTimer = null, excludeTimer = null;
  let searchResult = { hits: [], total: 0 };

  // v0.26 右栏排序
  let civSort = localStorage.getItem("civ6replay.civSort") || "floor";

  // v0.26: the city panel remembers which city it shows so a turn change can
  // re-render (or close) it.
  let cityTarget = null;

  // v0.40: 当前回合在 ``turns`` 里的下标 —— 「旅游业绩 / 回合」要拿**上一个
  // 存档**的累积值做差，而 payload 自己不知道它在时间轴上的位置。
  let currentTurnIndex = -1;

  // --- v0.26 floating panels ----------------------------------------------
  // Dock thickness and split weights are proportional to the stage. Floating
  // dimensions are kept separately so dragging a dock out restores a useful box.
  const PANEL_KINDS = ["left", "right", "tile", "city"];
  const PANEL_IDS = { left: "left-panel", right: "right-panel",
                      tile: "tile-panel", city: "city-panel" };
  const PANEL_MIN_W = 200, PANEL_MIN_H = 140, PANEL_EDGE = 8;
  const PANEL_DOCK_SNAP = 24;
  const PANEL_STORE = "civ6replay.panels.v2";
  // hex radius / width ratio, mirrors HexMap's ``R`` (navigation canvas math)
  const HEX_R = 0.5 / Math.cos(Math.PI / 6);

  function defaultPanels() {
    const tileH = 320;
    return {
      left: { x: 0, y: 0, w: 250, h: 0, dock: "left", hidden: false },
      right: { x: 0, y: 0, w: 416, h: 0, dock: "right", hidden: false },
      // x: null = "top-right of the uncovered map"; the city panel starts right
      // under the tile panel
      tile: { x: null, y: PANEL_EDGE, w: 340, h: tileH, dock: null, hidden: false },
      city: { x: null, y: PANEL_EDGE + tileH + PANEL_EDGE, w: 340, h: tileH,
              dock: null, hidden: false },
    };
  }

  let panels = loadPanels();
  let dockLayout = null;
  let activeSplitter = null;
  const SIDE_PANELS = ["left", "right"];
  const sidePanelMotions = new Map();
  const PANEL_MOTION = { duration: 240, easing: "cubic-bezier(.22, .61, .36, 1)" };

  function hashStr(h) { return (h >>> 0).toString(); }
  // whole numbers without decimals, everything else with one
  function fmtNum(v) {
    const n = Number(v) || 0;
    return Math.abs(n - Math.round(n)) < 1e-9 ? String(Math.round(n)) : n.toFixed(1);
  }
  let languageSeq = 0;
  async function getJSON(url, options) {
    const revision = languageSeq;
    const r = await fetch(window.Civ6I18n.url(url), options);
    const data = await r.json().catch(() => ({}));
    if (revision !== languageSeq) throw new DOMException("Language changed", "AbortError");
    if (!r.ok) throw new Error(data.detail || (url + " " + r.status));
    return data;
  }
  // Replay state is mutable; never reuse an HTTP response from a previous scan.
  function getReplayJSON(url) { return getJSON(url, { cache: "no-store" }); }
  async function postJSON(url, body) {
    const revision = languageSeq;
    const r = await fetch(window.Civ6I18n.url(url), { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (revision !== languageSeq) throw new DOMException("Language changed", "AbortError");
    if (!r.ok) throw new Error(data.detail || (url + " " + r.status));
    return data;
  }

  function refreshLanguageTables() {
    LAYER_KEYS = HexMap.LAYERS.map(([key, label]) => [key, L(label)]);
    MAPSIZE_ZH = {
    MAPSIZE_DUEL: L("决斗"), MAPSIZE_TINY: L("微小"), MAPSIZE_SMALL: L("小型"),
    MAPSIZE_STANDARD: L("标准"), MAPSIZE_LARGE: L("大型"), MAPSIZE_HUGE: L("巨大"),
    MAPSIZE_ENORMOUS: L("巨人"), MAPSIZE_GIANT: L("巨人"),
  };
    GAMESPEED_ZH = {
    GAMESPEED_MARATHON: L("马拉松"), GAMESPEED_EPIC: L("史诗"), GAMESPEED_STANDARD: L("标准"),
    GAMESPEED_QUICK: L("快速"), GAMESPEED_ONLINE: L("联机"),
  };
    AGE_ZH = { 0: L("黑暗时代"), 1: L("普通时代"), 2: L("黄金时代"), 3: L("英雄时代") };
    CIV_SORT_OPTIONS = [
    ["floor", L("楼层")], ["team", L("团队")], ["science", L("科技")],
    ["culture", L("文化")], ["cities", L("城市数")], ["production", L("产能")],
    ["military", L("军力")], ["age", L("所属时代")],
  ];
    CS_FLAVOUR_ORDER = [L("科技"), L("文化"), L("商业"), L("军事"), L("工业"), L("宗教")];
    CAT_ZH = { mil: L("军事"), civ: L("平民"), sup: L("支援"), trade: L("商人"), rel: L("宗教") };
    CITY_YIELD_CELLS = [
    [L("食物"), ICON_FOOD], [L("产能"), ICON_PROD], [L("金币"), ICON_GOLD],
    [L("科技"), ICON_SCI], [L("文化"), ICON_CUL], [L("信仰"), ICON_FAITH],
  ];
    LEDGER_RANGES = [["all", L("从第1t")], ["5", L("近5t")], ["10", L("近10t")], ["30", L("近30t")]];
    CIV_ROW_LABELS = {
    city: L("城市"), mil: L("军力"), food: L("粮食"), prod: L("产能"), sci: L("科技"),
    cul: L("文化"), gold: L("金币"), faith: L("信仰"), diplo: L("外交"),
  };
    SHARE_KIND_ZH = { public: L("公网"), uu: L("UU 虚拟网"), lan: L("本机局域网"),
                          manual: L("手填地址"), none: L("未选定") };
    SHARE_SOURCE_ZH = { nic: L("本机网卡"), metadata: L("云元数据"), echo: L("外部回显"),
                            manual: L("手填") };
    SHARE_GROUPS = [["public", L("公网 IP")], ["uu", L("UU 虚拟网")], ["lan", L("其它本机 IP")]];
  }

  async function init() {
    refreshLanguageTables();
    window.addEventListener("civ6-language-change", changeLanguage);
    wireTurnControls();
    if (compareMode) {
      document.documentElement.classList.add("compare-page");
      document.title = L("文明6 · 数据对比");
      hudTab = "compare";
      panels.city.hidden = true;
      panelEl("city").querySelector(".panel-close").onclick = () => closePanel("city");
      $("map").remove();
      panelEl("right").classList.remove("hidden");
      await loadReplayList();
      return;
    }
    map = new HexMap($("map"), {});
    if (savedMapView && Number.isFinite(savedMapView.scale)) {
      map.scale = Math.max(HexMap.MIN_SCALE, Math.min(HexMap.MAX_SCALE, savedMapView.scale));
    }
    map.on("select", onSelectTile);
    map.on("hover", onHoverTile);
    map.on("cityselect", onCitySelect);
    map.on("view", renderNav);      // v0.26: keep the navigation box in sync
    map.on("view", saveMapView);
    restoreLayers();
    buildLayerToggles();
    $("btn-refresh").onclick = doRefresh;
    $("btn-savedir").onclick = openSaveDirModal;
    $("replay-select").onchange = () => loadReplay(parseInt($("replay-select").value, 10));
    window.addEventListener("resize", () => {
      applyPanels();
      map.draw();
    });
    // Header wrapping, banners and container resizing also change the stage.
    new ResizeObserver(() => applyPanels()).observe($("stage"));
    // every panel: title-bar drag, corner resize, ✕ close
    for (const kind of PANEL_KINDS) {
      setupPanelDrag(kind);
      setupPanelResize(kind);
      setupDockResize(kind);
      const btn = panelEl(kind).querySelector(".panel-close");
      if (btn) btn.onclick = () => closePanel(kind);
    }
    for (const kind of SIDE_PANELS) {
      $(kind + "-panel-toggle").onclick = () => {
        if (panels[kind].hidden) openPanel(kind); else closePanel(kind);
      };
    }
    $("layout-btn").onclick = (e) => {
      e.stopPropagation();
      $("layout-pop").classList.toggle("hidden");
      $("layout-btn").setAttribute("aria-expanded", String(!$("layout-pop").classList.contains("hidden")));
      syncLayoutPop();
    };
    $("layout-pop").addEventListener("click", (e) => e.stopPropagation());
    document.addEventListener("click", () => {
      $("layout-pop").classList.add("hidden");
      $("layout-btn").setAttribute("aria-expanded", "false");
    });
    $("layout-pop").querySelectorAll("input[data-panel]").forEach((cb) => {
      cb.onchange = () => {
        const kind = cb.dataset.panel;
        if (cb.checked) openPanel(kind); else closePanel(kind);
      };
    });
    $("layout-reset").onclick = resetLayout;
    wireNav();
    $("search-input").oninput = () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(runSearch, 200);
    };
    $("search-exclude").oninput = () => {
      clearTimeout(excludeTimer);
      excludeTimer = setTimeout(runSearch, 200);
    };
    $("search-clear").onclick = () => {
      $("search-input").value = ""; $("search-exclude").value = "";
      runSearch();
    };
    wireSaveDirModal();
    wireShareModal();                 // v0.38: 共享对话框
    // v0.26: 迷雾复选框并入「图层」, and it drives ``layers.fog`` itself
    $("fog-toggle").onchange = (e) => {
      map.layers.fog = e.target.checked;
      map.fog.enabled = e.target.checked;
      saveLayers();
      map.draw();
    };
    $("fog-player").onchange = (e) => { map.fog.player = parseInt(e.target.value, 10); map.draw(); };
    const typeBox = $("type-toggle");
    typeBox.checked = showType;
    typeBox.onchange = () => {
      showType = typeBox.checked;
      localStorage.setItem("civ6replay.showType", showType ? "1" : "0");
      refreshContext();
    };
    const coordBox = $("coord-toggle");
    coordBox.checked = showCoord;
    coordBox.onchange = () => {
      showCoord = coordBox.checked;
      localStorage.setItem("civ6replay.showCoord", showCoord ? "1" : "0");
      refreshContext();
    };
    $("hud-tabs").querySelectorAll("button").forEach((b) => {
      b.onclick = () => {
        if (b.dataset.hud === "compare") { openComparePage(); return; }
        hudTab = b.dataset.hud; syncHudTabs(); refreshContext();
      };
    });
    const sortSel = $("civ-sort");
    sortSel.innerHTML = CIV_SORT_OPTIONS.map(
      ([v, label]) => `<option value="${v}">${label}</option>`).join("");
    if (!CIV_SORT_OPTIONS.some(([v]) => v === civSort)) civSort = "floor";
    sortSel.value = civSort;
    sortSel.onchange = () => {
      civSort = sortSel.value;
      localStorage.setItem("civ6replay.civSort", civSort);
      refreshContext();
    };
    $("civ-hud-minimize").onclick = () => setCivHudMinimized(true);
    $("civ-hud-restore").onclick = () => setCivHudMinimized(false);
    syncHudTabs();
    // Keep layout visibility even before a tile / city is selected.
    applyPanels();
    await loadReplayList();
    await initShare();
  }

  function wireTurnControls() {
    $("btn-prev").onclick = () => step(-1);
    $("btn-next").onclick = () => step(1);
    $("btn-minus10").onclick = () => step(-10);
    $("btn-plus10").onclick = () => step(10);
    $("turn-slider").oninput = () => {
      const idx = nearestLoadedIndex(parseInt($("turn-slider").value, 10));
      if (idx != null) loadTurn(idx); else renderLoadOverlay();
    };
    window.addEventListener("keydown", onKeyDown);
  }

  function openComparePage() {
    const url = new URL(location.href);
    url.searchParams.set("compare", "1");
    if (seed != null) url.searchParams.set("seed", String(seed));
    url.searchParams.set("turn", currentTurn ? String(Math.max(0, currentTurn.turn)) : "last");
    window.open(url.href, "_blank", "noopener");
  }

  function restoreLayers() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(LAYER_STORE) || "null"); }
    catch (e) {
      if (e.name === "AbortError") return; /* use the renderer's defaults */ }
    map.layers.fog = map.fog.enabled;
    for (const [key] of LAYER_KEYS) {
      if (saved && typeof saved[key] === "boolean") map.layers[key] = saved[key];
    }
    map.fog.enabled = !!map.layers.fog;
    $("fog-toggle").checked = map.fog.enabled;
  }

  function saveLayers() {
    const saved = Object.fromEntries(LAYER_KEYS.map(([key]) => [key, !!map.layers[key]]));
    try { localStorage.setItem(LAYER_STORE, JSON.stringify(saved)); }
    catch (e) {
      if (e.name === "AbortError") return; /* storage may be unavailable */ }
  }

  function buildLayerToggles() {
    // v0.26: 迷雾 lives in the same grid (its checkbox is in index.html so the
    // id survives) - the rebuilt toggles are inserted before it.
    const box = $("layers");
    const fog = $("fog-toggle").closest("label");
    box.querySelectorAll("label.layer-toggle").forEach((el) => {
      if (el !== fog) el.remove();
    });
    for (const [key, label] of LAYER_KEYS) {
      if (key === "fog") continue;
      const l = document.createElement("label");
      l.className = "layer-toggle";
      const cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = !!map.layers[key];
      cb.dataset.layer = key;
      cb.onchange = () => { map.layers[key] = cb.checked; saveLayers(); map.draw(); };
      l.appendChild(cb);
      if (key === "yield") {
        l.classList.add("yield-layer-toggle");
        const text = document.createElement("span");
        text.appendChild(document.createTextNode(L("产出（")));
        const beta = document.createElement("span"); beta.className = "yield-layer-beta";
        beta.textContent = L("测试版"); text.appendChild(beta);
        text.appendChild(document.createTextNode("）")); l.appendChild(text);
      } else l.appendChild(document.createTextNode(label));
      box.insertBefore(l, fog);
    }
  }

  function syncHudTabs() {
    $("hud-tabs").querySelectorAll("button").forEach(
      (b) => b.classList.toggle("active", b.dataset.hud === hudTab));
    // the sort order only applies to the文明 page (城邦 keeps its own order)
    $("hud-sort").classList.toggle("hidden", hudTab !== "civ");
  }

  // --- v0.26 floating panels ----------------------------------------------
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  function panelEl(kind) { return $(PANEL_IDS[kind]); }

  function loadPanels() {
    const out = defaultPanels();
    let doc = null;
    try { doc = JSON.parse(localStorage.getItem(PANEL_STORE) || "null"); }
    catch (e) {
      if (e.name === "AbortError") return; doc = null; }
    if (!doc || typeof doc !== "object") return out;
    for (const kind of PANEL_KINDS) {
      const s = doc[kind];
      if (!s || typeof s !== "object") continue;
      const d = out[kind];
      if (Number.isFinite(s.x) || s.x === null) d.x = s.x;
      if (Number.isFinite(s.y) || s.y === null) d.y = s.y;
      if (Number.isFinite(s.w)) d.w = Math.max(PANEL_MIN_W, s.w);
      if (Number.isFinite(s.h)) d.h = s.h;
      if (PanelLayout.EDGES.includes(s.dock) || s.dock === null) d.dock = s.dock;
      if (Number.isFinite(s.dockRatio) && s.dockRatio > 0) d.dockRatio = s.dockRatio;
      if (Number.isFinite(s.weight) && s.weight > 0) d.weight = s.weight;
      if (Number.isFinite(s.order)) d.order = s.order;
      if (typeof s.hidden === "boolean") d.hidden = s.hidden;
      if (kind === "right" && typeof s.minimized === "boolean") d.minimized = s.minimized;
    }
    return out;
  }

  function savePanels() {
    try { localStorage.setItem(PANEL_STORE, JSON.stringify(panels)); }
    catch (e) {
      if (e.name === "AbortError") return; /* storage may be unavailable */ }
  }

  function stageSize() {
    const el = $("stage");
    return { w: el.clientWidth, h: el.clientHeight };
  }

  function placePanel(el, rect) {
    el.style.left = Math.round(rect.x) + "px";
    el.style.top = Math.round(rect.y) + "px";
    el.style.width = Math.round(rect.w) + "px";
    el.style.height = Math.round(rect.h) + "px";
  }

  function applyPanels() {
    if (compareMode) return;
    const size = stageSize();
    if (!size.w || !size.h) return;
    for (const edge of PanelLayout.EDGES) {
      const keys = PanelLayout.members(panels, edge);
      if (!keys.length) continue;
      const first = panels[keys[0]], axis = edge === "bottom" ? "h" : "w";
      const ratio = first.dockRatio || (edge === "bottom" ? .2 : (first[axis] || 260) / size[axis]);
      keys.forEach(k => { panels[k].dockRatio = ratio; });
    }
    dockLayout = PanelLayout.compute(panels, size);
    for (const kind of PANEL_KINDS) {
      const el = panelEl(kind);
      if (!el) continue;
      const st = panels[kind];
      const minimized = kind === "right" && !!st.minimized;
      el.classList.toggle("hud-minimized", minimized);
      if (kind === "right") $("civ-hud-restore").classList.toggle("hidden", !minimized);
      el.classList.toggle("hidden", !!st.hidden && !sidePanelMotions.has(kind));
      el.classList.toggle("panel-collapsing", !!st.hidden && sidePanelMotions.has(kind));
      el.inert = !!st.hidden;
      el.style.zIndex = st.dock && !minimized ? "40" : "50";
      PanelLayout.EDGES.forEach(edge => el.classList.toggle("dock-" + edge, !minimized && st.dock === edge));
      if (st.hidden) continue;
      if (minimized) {
        placeCompactHUD(size);
      } else if (st.dock) {
        placePanel(el, dockLayout.rects[kind]);
      } else {
        const w = clamp(st.w, Math.min(PANEL_MIN_W, size.w), size.w);
        const h = clamp(st.h || 320, Math.min(PANEL_MIN_H, size.h), size.h);
        const x = clamp(st.x == null ? size.w - dockLayout.right - w - PANEL_EDGE : st.x, 0, size.w - w);
        const y = clamp(st.y == null ? PANEL_EDGE : st.y, 0, size.h - h);
        // Do not write clamped sizes back: shrinking a tab must not destroy
        // the user's preferred dimensions when the viewport grows again.
        placePanel(el, { x, y, w, h });
      }
    }
    syncDockSplitters();
    syncSidePanelToggles(size);
    syncLayoutPop();
  }

  function placeCompactHUD(size) {
    const el = panelEl("right"), grid = $("civ-hud").querySelector(".mini-grid");
    const available = Math.max(1, size.w - dockLayout.right - 2 * PANEL_EDGE);
    const columns = grid ? Number(grid.dataset.columns) : 0;
    const w = Math.min(available, Math.max(80, columns * CMP_COMPACT_W + Math.max(0, columns - 1) * 2 + 8));
    // Measure at the final width so overflow never hides the last data row.
    el.style.width = Math.round(w) + "px";
    const scroll = grid?.parentElement;
    const scrollbar = grid && grid.scrollWidth > Math.round(w) - 8
      ? scroll.offsetHeight - scroll.clientHeight : 0;
    const h = Math.min(Math.max(1, size.h - dockLayout.bottom - 2 * PANEL_EDGE),
      el.querySelector(".panel-head").offsetHeight + (grid ? grid.scrollHeight : 36) + 8 + scrollbar);
    placePanel(el, { x: Math.max(0, size.w - dockLayout.right - w - PANEL_EDGE),
      y: Math.min(PANEL_EDGE, Math.max(0, size.h - h)), w, h });
  }

  function setCivHudMinimized(minimized) {
    if (compareMode || !!panels.right.minimized === minimized) return;
    stopSidePanelMotion("right");
    panels.right.minimized = minimized;
    if (minimized) { hudTab = "civ"; syncHudTabs(); }
    if (currentTurn) renderHUD(currentTurn);
    applyPanels(); savePanels();
    (minimized ? $("civ-hud-restore") : $("civ-hud-minimize")).focus({ preventScroll: true });
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      panelEl("right").animate([{ opacity: .5 }, { opacity: 1 }], { duration: 160 });
    }
  }

  function syncSidePanelToggles(size) {
    for (const kind of SIDE_PANELS) {
      const st = panels[kind], el = panelEl(kind), btn = $(kind + "-panel-toggle");
      btn.classList.toggle("hidden", kind === "right" && !!st.minimized && !st.hidden);
      const edge = !st.minimized && (st.dock === "left" || st.dock === "right") ? st.dock : kind;
      const width = 24, height = Math.min(48, size.h);
      const x = st.hidden ? (edge === "left" ? 0 : size.w - width)
        : edge === "left" ? el.offsetLeft + el.offsetWidth : el.offsetLeft - width;
      let y = st.hidden ? (size.h - height) / 2 : el.offsetTop + (el.offsetHeight - height) / 2;
      // Two hidden HUDs on the same edge still need separate restore handles.
      const peer = panels[kind === "left" ? "right" : "left"];
      const peerEdge = !peer.minimized && (peer.dock === "left" || peer.dock === "right") ? peer.dock : (kind === "left" ? "right" : "left");
      if (st.hidden && peer.hidden && edge === peerEdge) y += kind === "left" ? -26 : 26;
      placePanel(btn, { x: clamp(x, 0, size.w - width), y: clamp(y, 0, size.h - height), w: width, h: height });
      btn.dataset.edge = edge;
      btn.textContent = (edge === "left") === !st.hidden ? "‹" : "›";
      const label = (st.hidden ? L("展开") : L("收起")) + (kind === "left" ? L("探索栏") : L("数据栏"));
      btn.title = label;
      btn.setAttribute("aria-label", label);
      btn.setAttribute("aria-expanded", String(!st.hidden));
    }
  }

  function stopSidePanelMotion(kind) {
    const motion = sidePanelMotions.get(kind);
    if (!motion) return;
    sidePanelMotions.delete(kind);
    motion.panel?.cancel();
    motion.toggle?.cancel();
    panelEl(kind).classList.remove("panel-collapsing");
  }

  function setPanelHidden(kind, hidden) {
    const st = panels[kind], el = panelEl(kind);
    if (SIDE_PANELS.includes(kind) && st.hidden === hidden) return;
    const animate = SIDE_PANELS.includes(kind) && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const btn = animate && $(kind + "-panel-toggle");
    const before = animate && btn.getBoundingClientRect();
    const wasMoving = sidePanelMotions.has(kind);
    const style = animate && getComputedStyle(el);
    const fromTransform = style && style.transform;
    const fromOpacity = style && style.opacity;
    stopSidePanelMotion(kind);
    const motion = {};
    if (animate) sidePanelMotions.set(kind, motion);
    st.hidden = hidden;
    if (hidden && el.contains(document.activeElement) && SIDE_PANELS.includes(kind)) {
      $(kind + "-panel-toggle").focus({ preventScroll: true });
    }
    applyPanels();
    savePanels();
    if (!animate) return;
    const size = stageSize();
    const edge = st.minimized ? null : st.dock;
    const away = edge === "bottom" ? `translateY(${size.h - el.offsetTop}px)`
      : edge === "left" ? `translateX(${-el.offsetLeft - el.offsetWidth}px)`
      : edge === "right" ? `translateX(${size.w - el.offsetLeft}px)`
      : `translateX(${kind === "left" ? -24 : 24}px)`;
    motion.panel = el.animate([
      { transform: !hidden && !wasMoving ? away : fromTransform,
        opacity: !hidden && !wasMoving ? 0 : fromOpacity },
      { transform: hidden ? away : "none", opacity: hidden ? 0 : 1 },
    ], PANEL_MOTION);
    const after = btn.getBoundingClientRect();
    motion.toggle = btn.animate([
      { transform: `translate(${before.x - after.x}px, ${before.y - after.y}px)` },
      { transform: "none" },
    ], PANEL_MOTION);
    motion.panel.onfinish = () => {
      if (sidePanelMotions.get(kind) !== motion) return;
      stopSidePanelMotion(kind);
      el.classList.toggle("hidden", !!panels[kind].hidden);
    };
  }

  function changeDockSplit(split, delta) {
    const a = dockLayout.rects[split.before], b = dockLayout.rects[split.after];
    const axis = split.edge === "bottom" ? "w" : "h";
    const total = a[axis] + b[axis];
    const minimum = Math.min(axis === "w" ? PANEL_MIN_W : PANEL_MIN_H, total / 2);
    const first = clamp(a[axis] + delta, minimum, total - minimum);
    const keys = dockLayout.groups[split.edge];
    const sum = keys.reduce((value, k) => value + (panels[k].weight || 1), 0);
    const span = keys.reduce((value, k) => value + dockLayout.rects[k][axis], 0);
    keys.forEach(k => { panels[k].weight = dockLayout.rects[k][axis] / span * sum; });
    panels[split.before].weight = first / span * sum;
    panels[split.after].weight = (total - first) / span * sum;
  }

  function syncDockSplitters() {
    const stage = $("stage");
    const wanted = new Set();
    for (const split of dockLayout.splitters) {
      const id = "dock-split-" + split.before + "-" + split.after;
      wanted.add(id);
      let el = $(id);
      if (!el) {
        el = document.createElement("div");
        el.id = id; el.className = "dock-splitter"; el.tabIndex = 0;
        el.setAttribute("role", "separator");
        el.setAttribute("aria-label", L("调整面板占比"));
        el.title = L("拖动调整面板占比（方向键也可调整）");
        el.addEventListener("pointerdown", ev => {
          if (ev.button !== 0) return;
          const current = el._split;
          activeSplitter = el;
          let last = current.edge === "bottom" ? ev.clientX : ev.clientY;
          const move = e => {
            const pos = current.edge === "bottom" ? e.clientX : e.clientY;
            changeDockSplit(current, pos - last); last = pos;
            applyPanels();
          };
          const stop = () => {
            el.removeEventListener("pointermove", move);
            el.removeEventListener("pointerup", stop);
            el.removeEventListener("pointercancel", stop);
            activeSplitter = null;
            document.body.classList.remove("panel-dragging");
            applyPanels(); savePanels();
          };
          el.setPointerCapture(ev.pointerId);
          el.addEventListener("pointermove", move);
          el.addEventListener("pointerup", stop);
          el.addEventListener("pointercancel", stop);
          document.body.classList.add("panel-dragging");
          ev.preventDefault(); ev.stopPropagation();
        });
        el.addEventListener("keydown", ev => {
          const horizontal = el._split.edge === "bottom";
          const delta = ev.key === (horizontal ? "ArrowLeft" : "ArrowUp") ? -16
            : ev.key === (horizontal ? "ArrowRight" : "ArrowDown") ? 16 : 0;
          if (!delta) return;
          changeDockSplit(el._split, delta); applyPanels(); savePanels(); ev.preventDefault();
        });
        stage.appendChild(el);
      }
      el._split = split;
      el.dataset.edge = split.edge;
      el.setAttribute("aria-orientation", split.edge === "bottom" ? "vertical" : "horizontal");
      const axis = split.edge === "bottom" ? "w" : "h";
      const a = dockLayout.rects[split.before][axis], b = dockLayout.rects[split.after][axis];
      el.setAttribute("aria-valuenow", Math.round(100 * a / (a + b)));
      el.setAttribute("aria-valuemin", "0"); el.setAttribute("aria-valuemax", "100");
      placePanel(el, split);
    }
    stage.querySelectorAll(".dock-splitter").forEach(el => {
      if (!wanted.has(el.id) && el !== activeSplitter) el.remove();
    });
  }

  function syncLayoutPop() {
    $("layout-pop").querySelectorAll("input[data-panel]").forEach((cb) => {
      cb.checked = !panels[cb.dataset.panel].hidden;
    });
    const pop = $("layout-pop");
    if (!pop.classList.contains("hidden")) {
      const anchor = $("layout-btn").getBoundingClientRect();
      pop.style.left = clamp(anchor.left, 8, Math.max(8, window.innerWidth - pop.offsetWidth - 8)) + "px";
      pop.style.top = anchor.bottom + 8 + "px";
      pop.style.maxHeight = Math.max(80, window.innerHeight - anchor.bottom - 16) + "px";
    }
  }

  // Initial centring and explicit fit() honour the docked panels - showing, hiding,
  // dragging or resizing any panel leaves the map exactly as it is.
  function mapPadding() {
    return dockLayout ? { left: dockLayout.left, right: dockLayout.right, bottom: dockLayout.bottom }
      : { left: 0, right: 0, bottom: 0 };
  }

  function loadMapView() {
    try {
      const saved = JSON.parse(localStorage.getItem(MAP_VIEW_STORE) || "null");
      return saved && typeof saved === "object" ? saved : null;
    } catch (e) {
      if (e.name === "AbortError") return; return null; }
  }

  function restoreMapView() {
    // The zoom is shared across saves; camera coordinates belong to one map.
    // Wait until the first turn and panel layout are ready before saving views.
    if (savedMapView && savedMapView.seed === seed &&
        savedMapView.width === map.width && savedMapView.height === map.height &&
        Number.isFinite(savedMapView.camX) && Number.isFinite(savedMapView.camY)) {
      map.camX = savedMapView.camX;
      map.camY = savedMapView.camY;
    } else {
      map.padding = mapPadding();
      map.centerView();
    }
    mapViewReady = true;
    map.draw();
  }

  function saveMapView() {
    if (!mapViewReady || !map || !map.payload) return;
    const view = { seed, width: map.width, height: map.height,
      scale: map.scale, camX: map.camX, camY: map.camY };
    const serialized = JSON.stringify(view);
    if (serialized === savedMapViewJSON) return;
    savedMapView = view;
    savedMapViewJSON = serialized;
    try { localStorage.setItem(MAP_VIEW_STORE, serialized); }
    catch (e) {
      if (e.name === "AbortError") return; /* Keep the in-page view even when browser storage is unavailable. */ }
  }

  function openPanel(kind) {
    if (compareMode && kind === "city") {
      panels.city.hidden = false;
      panelEl("city").classList.remove("hidden");
      return;
    }
    const edge = panels[kind].minimized ? null : panels[kind].dock;
    const peer = edge && PanelLayout.members(panels, edge).find(k => k !== kind);
    if (peer) panels[kind].dockRatio = panels[peer].dockRatio;
    setPanelHidden(kind, false);
  }

  function closePanel(kind) {
    if (compareMode && kind === "city") {
      panels.city.hidden = true;
      panelEl("city").classList.add("hidden");
      cityTarget = null;
      return;
    }
    setPanelHidden(kind, true);
    if (kind === "city") {
      cityTarget = null;
      if (map) map.setCityHighlight(null, null);
    }
  }

  // 「重置布局」: back to the first-run layout (docks, sizes, visibility).
  function resetLayout() {
    SIDE_PANELS.forEach(stopSidePanelMotion);
    panels = defaultPanels();
    cityTarget = null;
    if (map) map.setCityHighlight(null, null);
    applyPanels();
    savePanels();
    if (currentTurn) renderHUD(currentTurn);
  }

  function dockPanel(kind, edge, position) {
    const keys = PanelLayout.members(panels, edge).filter(k => k !== kind);
    const st = panels[kind], size = stageSize();
    const peer = keys.length ? panels[keys[0]] : null;
    st.dock = edge;
    st.dockRatio = peer ? peer.dockRatio : edge === "bottom" ? .2 : st.w / size.w;
    // Insert at the drop position and initially give the new HUD an equal share.
    const axis = edge === "bottom" ? "w" : "h";
    const offset = edge === "bottom" ? "x" : "y";
    if (keys.length) {
      const sum = keys.reduce((value, k) => value + (panels[k].weight || 1), 0);
      const span = keys.reduce((value, k) => value + dockLayout.rects[k][axis], 0);
      keys.forEach(k => { panels[k].weight = dockLayout.rects[k][axis] / span * sum; });
      st.weight = sum / keys.length;
    } else st.weight = 1;
    let index = keys.findIndex(k => position < dockLayout.rects[k][offset] + dockLayout.rects[k][axis] / 2);
    if (index < 0) index = keys.length;
    keys.splice(index, 0, kind);
    keys.forEach((k, i) => { panels[k].order = i; });
  }

  function dockTarget(el, ev) {
    const size = stageSize(), bounds = $("stage").getBoundingClientRect();
    const px = ev.clientX - bounds.left, py = ev.clientY - bounds.top;
    // Pointer near an edge has priority, so full-height HUDs can still be
    // deliberately moved to the bottom instead of snapping back to a side.
    if (py >= size.h - PANEL_DOCK_SNAP) return "bottom";
    if (px <= PANEL_DOCK_SNAP) return "left";
    if (px >= size.w - PANEL_DOCK_SNAP) return "right";
    const candidates = [
      ["left", Math.abs(el.offsetLeft)],
      ["right", Math.abs(size.w - el.offsetLeft - el.offsetWidth)],
      ["bottom", Math.abs(size.h - el.offsetTop - el.offsetHeight)],
    ].sort((a, b) => a[1] - b[1]);
    return candidates[0][1] <= PANEL_DOCK_SNAP ? candidates[0][0] : null;
  }

  function showDockPreview(kind, edge, position) {
    let preview = $("dock-preview");
    if (!edge) { if (preview) preview.remove(); return; }
    if (!preview) {
      preview = document.createElement("div"); preview.id = "dock-preview";
      preview.className = "dock-preview"; $("stage").appendChild(preview);
    }
    // Calculate the exact resulting partition without changing saved state.
    const saved = panels;
    panels = Object.fromEntries(PANEL_KINDS.map(k => [k, { ...saved[k] }]));
    dockPanel(kind, edge, position);
    const rect = PanelLayout.compute(panels, stageSize()).rects[kind];
    panels = saved;
    placePanel(preview, rect);
  }

  function setupPanelDrag(kind) {
    const el = panelEl(kind);
    if (!el) return;
    const head = el.querySelector(".panel-head");
    if (!head) return;
    head.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0 || panels[kind].minimized) return;
      if (ev.target.closest("button")) return;   // the ✕ stays a plain button
      stopSidePanelMotion(kind);
      const st = panels[kind];
      const startX = ev.clientX, startY = ev.clientY;
      let startLeft = el.offsetLeft;
      const startTop = el.offsetTop;
      const grab = ev.clientX - el.getBoundingClientRect().left;
      let target = null;
      let moved = false;
      try { head.setPointerCapture(ev.pointerId); } catch (e) {
      if (e.name === "AbortError") return; /* optional */ }
      document.body.classList.add("panel-dragging");
      const onMove = (e) => {
        const dx = e.clientX - startX, dy = e.clientY - startY;
        if (!moved && Math.abs(dx) + Math.abs(dy) < 3) return;
        if (!moved && st.dock) {
          st.dock = null;
          st.h = st.h || 320;
          startLeft = startX - $("stage").getBoundingClientRect().left - Math.min(grab, st.w - 40);
        }
        moved = true;
        const size = stageSize();
        // Keep the title under the pointer when dragging down to the bottom.
        st.x = clamp(startLeft + dx, -Math.min(st.w, size.w) + 80, Math.max(0, size.w - 40));
        st.y = clamp(startTop + dy, 0, Math.max(0, size.h - 24));
        applyPanels();
        el.classList.add("panel-moving");
        placePanel(el, { x: st.x, y: st.y, w: Math.min(st.w, size.w), h: Math.min(st.h, size.h) });
        target = dockTarget(el, e);
        const bounds = $("stage").getBoundingClientRect();
        showDockPreview(kind, target, target === "bottom" ? e.clientX - bounds.left : e.clientY - bounds.top);
      };
      const onUp = (e) => {
        head.removeEventListener("pointermove", onMove);
        head.removeEventListener("pointerup", onUp);
        head.removeEventListener("pointercancel", onUp);
        document.body.classList.remove("panel-dragging");
        el.classList.remove("panel-moving");
        showDockPreview(kind, null);
        if (!moved) return;
        if (target && e.type !== "pointercancel") {
          const bounds = $("stage").getBoundingClientRect();
          dockPanel(kind, target, target === "bottom" ? e.clientX - bounds.left : e.clientY - bounds.top);
        }
        applyPanels();
        savePanels();
      };
      head.addEventListener("pointermove", onMove);
      head.addEventListener("pointerup", onUp);
      head.addEventListener("pointercancel", onUp);
      ev.preventDefault();
    });
  }

  // Free HUDs resize at the corner; docks resize through their inner edge.
  function setupDockResize(kind) {
    const el = panelEl(kind), grip = document.createElement("div");
    grip.className = "panel-dock-resize";
    grip.title = L("拖动调整吸附区域大小");
    el.appendChild(grip);
    grip.addEventListener("pointerdown", ev => {
      const edge = panels[kind].dock;
      if (ev.button !== 0 || !edge || panels[kind].minimized) return;
      const horizontal = edge !== "bottom";
      const start = horizontal ? ev.clientX : ev.clientY;
      const initial = horizontal ? el.offsetWidth : el.offsetHeight;
      const move = e => {
        const delta = ((horizontal ? e.clientX : e.clientY) - start) * (edge === "left" ? 1 : -1);
        const size = stageSize(), total = horizontal ? size.w : size.h;
        const minimum = Math.min(horizontal ? PANEL_MIN_W : PANEL_MIN_H, total * .2);
        const ratio = clamp(initial + delta, minimum, total * (horizontal ? .6 : .65)) / total;
        PANEL_KINDS.filter(k => panels[k].dock === edge && !panels[k].minimized).forEach(k => { panels[k].dockRatio = ratio; });
        applyPanels();
      };
      const stop = () => {
        grip.removeEventListener("pointermove", move);
        grip.removeEventListener("pointerup", stop);
        grip.removeEventListener("pointercancel", stop);
        document.body.classList.remove("panel-dragging"); savePanels();
      };
      grip.setPointerCapture(ev.pointerId);
      grip.addEventListener("pointermove", move);
      grip.addEventListener("pointerup", stop);
      grip.addEventListener("pointercancel", stop);
      document.body.classList.add("panel-dragging");
      ev.preventDefault(); ev.stopPropagation();
    });
  }

  function setupPanelResize(kind) {
    const el = panelEl(kind);
    if (!el) return;
    const grip = el.querySelector(".panel-resize");
    if (!grip) return;
    grip.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0 || panels[kind].dock || panels[kind].minimized) return;
      const st = panels[kind];
      const size = stageSize();
      const startW = el.offsetWidth, startH = el.offsetHeight;
      st.x = el.offsetLeft; st.y = el.offsetTop;
      const startX = ev.clientX, startY = ev.clientY;
      let moved = false;
      try { grip.setPointerCapture(ev.pointerId); } catch (e) {
      if (e.name === "AbortError") return; /* optional */ }
      document.body.classList.add("panel-dragging");
      const onMove = (e) => {
        const dx = e.clientX - startX, dy = e.clientY - startY;
        if (!moved && Math.abs(dx) + Math.abs(dy) < 3) return;
        moved = true;
        st.w = clamp(startW + dx, PANEL_MIN_W, Math.max(PANEL_MIN_W, size.w));
        st.h = clamp(startH + dy, PANEL_MIN_H, Math.max(PANEL_MIN_H, size.h));
        applyPanels();
      };
      const onUp = () => {
        grip.removeEventListener("pointermove", onMove);
        grip.removeEventListener("pointerup", onUp);
        grip.removeEventListener("pointercancel", onUp);
        document.body.classList.remove("panel-dragging");
        if (moved) savePanels();
      };
      grip.addEventListener("pointermove", onMove);
      grip.addEventListener("pointerup", onUp);
      grip.addEventListener("pointercancel", onUp);
      ev.preventDefault();
      ev.stopPropagation();
    });
  }

  function refreshContext() {
    if (!currentTurn) return;
    renderHUD(currentTurn);
    if (map && map.selected >= 0 && !panels.tile.hidden) onSelectTile(map.selected, true);
    if (map) renderNav();
  }

  async function changeLanguage() {
    ++languageSeq;
    const seq = ++replaySeq, selectedSeed = seed;
    ++turnSeq;
    refreshLanguageTables();
    if (compareMode) document.title = L("文明6 · 数据对比");
    else {
      buildLayerToggles();
      $("civ-sort").innerHTML = CIV_SORT_OPTIONS.map(([value, label]) =>
        `<option value="${value}">${label}</option>`).join("");
      $("civ-sort").value = civSort;
      syncSidePanelToggles(stageSize());
    }
    $("tooltip").classList.add("hidden");
    turnCache.clear(); names = {};
    try {
      if (selectedSeed == null) { await loadReplayList(); return; }
      const [info, list] = await Promise.all([
        getReplayJSON(`/api/replay/${selectedSeed}`), getReplayJSON("/api/replays")]);
      if (seq !== replaySeq) return;
      staticInfo = info;
      YIELD_BY_NAME = {};
      for (const [key, meta] of Object.entries(info.yieldMeta || {})) YIELD_BY_NAME[meta.name] = key;
      const select = $("replay-select"); select.innerHTML = "";
      for (const replay of list) {
        const option = document.createElement("option"); option.value = replay.seed;
        option.textContent = `${replay.mapName || "?"} · ${replay.turnMax}${L("回合 · ")}${replay.saveCount}${L("个存档")}` +
          (replay.unsupported ? L(" · 不支持") : "");
        select.appendChild(option);
      }
      select.value = String(selectedSeed);
      if (info.unsupported) showUnsupportedReplay(info);
      else {
        renderReplayMeta(info); renderLayerErrors(info); fillFogPlayers(info.players);
        await loadTurn(currentTurnIndex >= 0 ? currentTurnIndex : currentIndex(), seq);
      }
      if (!compareMode) {
        const shareInfo = await getJSON("/api/share");
        if (seq === replaySeq) { applyShareInfo(shareInfo); setShareLock(!!shareInfo.enabled); }
      }
    } catch (error) {
      if (seq === replaySeq && error.name !== "AbortError") setBanner(L("存档加载失败：") + error.message, true);
    }
  }

  async function doRefresh() {
    if (shareLockNote(L("刷新存档"))) return;
    await fetch("/api/refresh", { method: "POST" });
    await loadReplayList();
  }

  async function loadReplayList(selection = null) {
    const list = await getReplayJSON("/api/replays");
    const sel = $("replay-select"); sel.innerHTML = "";
    if (!list.length) {
      ++replaySeq;
      resetReplayState();
      seed = null;
      sel.innerHTML = L("<option>未找到存档</option>");
      setBanner(L("未找到 .Civ6Save 存档。点击「打开存档」或拖入存档文件、文件夹。"), true);
      return;
    }
    for (const r of list) {
      const o = document.createElement("option");
      o.value = r.seed;
      // v0.39: 不支持的存档（黑名单 MOD / 结社 / 垄断）在列表里先标出来
      o.textContent = `${r.mapName || "?"} · ${r.turnMax}${L("回合 · ")}${r.saveCount}${L("个存档")}`
        + (r.unsupported ? L(" · 不支持") : "");
      sel.appendChild(o);
    }
    // The URL follows the displayed replay/turn, including after a rescan.
    const params = new URLSearchParams(location.search);
    const wantSeed = selection ? selection.seed : parseInt(params.get("seed") || "", 10);
    const wanted = list.find((r) => r.seed === wantSeed);
    if (wanted) sel.value = String(wanted.seed);
    const requestedTurn = selection ? String(selection.turn)
      : wanted || !params.has("seed") ? params.get("turn") || "" : "";
    return loadReplay(wanted ? wanted.seed : list[0].seed, requestedTurn);
  }

  function setBanner(msg, err) {
    const b = $("banner");
    if (!msg) { b.classList.add("hidden"); return; }
    b.textContent = msg; b.className = "banner" + (err ? " err" : ""); b.classList.remove("hidden");
  }

  function locMapSize(s) { return MAPSIZE_ZH[s] || s || "?"; }
  function locGameSpeed(s) { return GAMESPEED_ZH[s] || s || "?"; }

  // v0.39: 不支持的存档 —— 清掉上一局的残留（回合 / 面板 / 搜索 / 迷雾），把画布
  // 交给 ``map.setUnsupported``（中间画叉 + 说明），顶栏给出同样的提示。
  function showUnsupportedReplay(info) {
    const un = info.unsupported || {};
    stopLoadPolling();
    loadstate = null;
    turns = []; currentTurn = null;
    currentTurnIndex = -1;
    turnCache.clear();
    cityTarget = null;
    const slider = $("turn-slider");
    slider.min = 0; slider.max = 0; slider.value = 0; slider.disabled = true;
    $("turn-label").textContent = "—";
    $("replay-meta").textContent =
      `${info.mapName || "?"} · ${locMapSize(info.mapSize)}${L(" · 不支持")}`;
    // v0.39: 不点名 —— 这里也不挂 MOD / DLC 列表（否则等于告诉大家是哪个 MOD 被拦了）
    $("replay-meta").title = "";
    fillFogPlayers([]);
    if (map) map.fog.player = null;
    $("civ-hud").innerHTML = "";
    $("search-count").textContent = "";
    $("search-results").innerHTML = "";
    renderLayerErrors(info);
    if (map) map.setUnsupported(un);
    setBanner(un.message || un.title || L("存档不支持"), true);
  }

  // Clear game-derived data before requesting the new replay. Late responses
  // must also check replaySeq so old prefetches cannot refill this cache.
  function resetReplayState() {
    ++turnSeq;
    mapViewReady = false;
    stopLoadPolling();
    loadstate = null;
    staticInfo = null; turns = []; currentTurn = null; currentTurnIndex = -1;
    turnCache.clear(); names = {}; YIELD_BY_NAME = {};
    ledgerData = null; ledgerKey = ""; ++ledgerSeq;
    Object.keys(expanded).forEach((k) => delete expanded[k]);
    navImage = null; navMeta = null; navView = null;
    cityTarget = null;
    searchResult = { hits: [], total: 0 };
    if (map) map.resetReplay();
    const nav = $("nav");
    nav.getContext("2d").clearRect(0, 0, nav.width, nav.height);
    for (const id of ["civ-hud", "search-results", "search-count", "tile-body", "tile-tabs", "city-body"]) {
      $(id).innerHTML = "";
    }
    $("tile-title").textContent = L("格子");
    $("city-title").textContent = L("城市");
    $("tooltip").classList.add("hidden");
    applyPanels();
    fillFogPlayers([]);
    const slider = $("turn-slider");
    slider.min = 0; slider.max = 0; slider.value = 0; slider.disabled = true;
    $("turn-label").textContent = "—";
    $("replay-meta").textContent = ""; $("replay-meta").title = "";
    renderLayerErrors({});
    renderLoadOverlay();
    hideProgress();
  }

  function renderReplayMeta(info) {
      const versions = info.balanceVersions || {};
      const channelLabel = (row) => ({beta: "Beta", wip: "WIP", alpha: "Alpha", rc: "RC",
        conflict: L("渠道冲突")}[row?.channel] || "");
      const componentLabel = (row) => [L(row.component), channelLabel(row)].filter(Boolean).join(" ");
      let meta = `${info.mapName} · ${locMapSize(info.mapSize)} · ${locGameSpeed(info.gameSpeed)} · ${info.width}×${info.height}`;
      if (info.wrapX) meta += L(" · 左右联通");
      if (info.multiplayer) meta += L(" · 多人");
      // v0.26.1: 平衡 MOD（BBG / CCB）会改写城墙数值，值得写在顶栏
      if (info.balanceMod) {
        const core = (versions.save || []).find(r => r.role === "core" && !r.absent);
        const expansion = (versions.save || []).find(r => r.role === "expansion" && !r.absent);
        meta += `${L(" · 平衡模组 ")}${core ? componentLabel(core) : info.balanceMod}`;
        if (expansion && channelLabel(expansion)) meta += ` · ${componentLabel(expansion)}`;
      }
      $("replay-meta").textContent = meta;
      $("replay-meta").title = (info.mods || []).length
        ? "MOD / DLC：" + info.mods.join("、") : "";
      if (info.balanceMod) {
        const describe = (rows) => (rows || []).length ? rows.map((r) =>
          `${r.absent ? L(r.component) : componentLabel(r)} ${r.absent ? L("未启用") : (r.version || (r.installedVersion ? `${L("安装版本 ")}${r.installedVersion}` : L("未记录")))}`
        ).join("；") : L("未记录");
        const help = document.createElement("span");
        help.className = "balance-version-help";
        help.textContent = "?";
        help.title = "";
        help.tabIndex = 0;
        help.setAttribute("role", "note");
        const message = `${L("数据库版本：")}${describe(versions.database)}${L("\n存档版本：")}${describe(versions.save)}`;
        help.setAttribute("aria-label", message);
        const tip = document.createElement("span");
        tip.className = "balance-version-tip";
        tip.textContent = message;
        help.appendChild(tip);
        $("replay-meta").appendChild(help);
      }
  }

  async function loadReplay(s, requestedTurn = "") {
    const seq = ++replaySeq;
    resetReplayState();
    seed = s;
    setBanner(L("正在加载存档…"));
    try {
      const info = await getReplayJSON(`/api/replay/${s}`);
      if (seq !== replaySeq) return;
      staticInfo = info;
      YIELD_BY_NAME = {};
      for (const k in (info.yieldMeta || {})) {
        const m = info.yieldMeta[k];
        YIELD_BY_NAME[m.name] = k;
      }
      // v0.39: 黑名单 MOD / 结社 / 垄断玩法 —— 整局判为不支持：一个回合都不加载，
      // 画布中间画叉 + 提示（hexmap.js ``setUnsupported``）。
      if (info.unsupported) { showUnsupportedReplay(info); return; }
      $("turn-slider").disabled = false;
      renderReplayMeta(info);
      fillFogPlayers(info.players);
      if (info.layerErrors && info.layerErrors.length) {
        const parts = info.layerErrors.map((e) => `${e.section}${e.offset != null ? "@0x" + e.offset.toString(16) : ""}`);
        setBanner(L("部分解析层不可用（已降级）：") + parts.join("、"), false);
      } else { setBanner(""); }
      renderLayerErrors(info);
      const replayTurns = await getReplayJSON(`/api/replay/${s}/turns`);
      if (seq !== replaySeq) return;
      turns = replayTurns;
      const slider = $("turn-slider");
      slider.min = 0; slider.max = Math.max(0, turns.length - 1); slider.value = 0;
      startLoadState(seq);
      // v0.26.2: 独立对比页可以指定回合；目标回合还没解析完时显示进度条
      const target = targetTurnIndex(requestedTurn.trim());
      if (compareMode || target > 0) await loadTurnWaiting(Math.max(0, target), seq);
      else await loadTurn(0, seq);
      if (seq !== replaySeq) return;
    } catch (e) {
      if (e.name === "AbortError") return;
      if (seq === replaySeq) {
        ++replaySeq;
        resetReplayState();
        setBanner(L("存档加载失败：") + e.message, true);
      }
    }
  }

  // ``?turn=90`` / ``?turn=last`` -> 回合数组下标（``-1`` = 不指定）
  function targetTurnIndex(wantTurn) {
    if (!wantTurn || !turns.length) return -1;
    if (wantTurn === "last") return turns.length - 1;
    const n = parseInt(wantTurn, 10);
    if (!Number.isFinite(n)) return -1;
    const exact = turns.findIndex((t) => t.turn === n);
    if (exact >= 0) return exact;
    let best = 0;                  // 该回合不存在时退到不超过它的最后一个回合
    turns.forEach((t, i) => { if (t.turn <= n) best = i; });
    return best;
  }

  // 等后台解析到目标回合再渲染（独立标签页用，带进度条）
  async function loadTurnWaiting(idx, seq = replaySeq) {
    const started = Date.now();
    for (let i = 0; i < 900; i++) {
      if (seq !== replaySeq) return;
      await refreshLoadState(seq);
      if (seq !== replaySeq) return;
      const loaded = !!(loadstate && loadstate.loaded && loadstate.loaded[idx]);
      const total = (loadstate && loadstate.loaded && loadstate.loaded.length) || turns.length;
      const done = loadstate && loadstate.loaded
        ? loadstate.loaded.filter(Boolean).length : 0;
      showProgress(window.Civ6I18n.format("正在解析存档：第 {turn} 回合{status}（已解析 {done} / {total}）",
        {turn: turns[idx].turn, status: loaded ? L("就绪") : L("等待中"), done, total}), total ? done / total : 0);
      if (loaded) break;
      await new Promise((r) => setTimeout(r, 700));
    }
    if (seq !== replaySeq) return;
    await loadTurn(idx, seq);
    // 数据都在缓存里时进度条会一闪而过，至少留 0.6 秒让人看清
    const rest = 600 - (Date.now() - started);
    if (rest > 0) await new Promise((r) => setTimeout(r, rest));
    if (seq === replaySeq) hideProgress();
  }

  // --- Loading progress ---------------------------------------------------
  function showProgress(text, frac) {
    const box = $("progress");
    if (!box) return;
    box.classList.remove("hidden");
    $("progress-text").textContent = text || "";
    const bar = box.querySelector("i");
    const pct = Math.round(Math.max(0, Math.min(1, frac || 0)) * 100);
    if (bar) bar.style.setProperty("--frac", pct + "%");
  }

  function hideProgress() {
    const box = $("progress");
    if (box) box.classList.add("hidden");
  }

  function fillFogPlayers(players) {
    const sel = $("fog-player"); sel.innerHTML = "";
    for (const p of players) {
      const o = document.createElement("option"); o.value = p.iPlayer; o.textContent = p.civName || ("P" + p.iPlayer);
      sel.appendChild(o);
    }
    if (map && players.length) { map.fog.player = players[0].iPlayer; }
  }
  // --- v0.22 slider load mask --------------------------------------------
  async function startLoadState(seq = replaySeq) {
    stopLoadPolling();
    await refreshLoadState(seq);
    if (seq !== replaySeq) return;
    const tick = async () => {
      if (seq !== replaySeq) return;
      const done = loadstate && !loadstate.loading && loadstate.loaded.every((x) => x);
      if (done) { loadPoller = null; return; }
      await refreshLoadState(seq);
      if (seq !== replaySeq) return;
      loadPoller = setTimeout(tick, 1500);
    };
    loadPoller = setTimeout(tick, 1500);
  }

  function stopLoadPolling() {
    if (loadPoller) { clearTimeout(loadPoller); loadPoller = null; }
  }

  async function refreshLoadState(seq = replaySeq) {
    if (seq !== replaySeq) return;
    let state = null;
    try { state = await getReplayJSON(`/api/replay/${seed}/loadstate`); }
    catch (e) {
      if (e.name === "AbortError") return; /* The current replay can retry on the next poll. */ }
    if (seq !== replaySeq) return;
    loadstate = state;
    renderLoadOverlay();
  }

  function renderLoadOverlay() {
    const ov = $("slider-loadstate"); if (!ov) return;
    ov.innerHTML = "";
    if (!loadstate || !loadstate.loaded || loadstate.loaded.length < 2) return;
    const n = loadstate.loaded.length;
    const seg = (a, b) => {
      const d = document.createElement("div"); d.className = "load-seg";
      d.style.left = (a / (n - 1) * 100) + "%";
      d.style.width = ((b - a + 1) / (n - 1) * 100) + "%";
      ov.appendChild(d);
    };
    let start = null;
    for (let i = 0; i < n; i++) {
      if (!loadstate.loaded[i]) { if (start === null) start = i; }
      else if (start !== null) { seg(start, i); start = null; }
    }
    if (start !== null) seg(start, n - 1);
  }

  // Snap an index to the nearest already-loaded turn (null when none/stale).
  function nearestLoadedIndex(idx) {
    if (!loadstate || !loadstate.loaded || !loadstate.loaded.length) {
      return Math.max(0, Math.min(turns.length - 1, idx));
    }
    const n = loadstate.loaded.length;
    idx = Math.max(0, Math.min(n - 1, idx));
    if (loadstate.loaded[idx]) return idx;
    for (let d = 1; d < n; d++) {
      if (idx - d >= 0 && loadstate.loaded[idx - d]) return idx - d;
      if (idx + d < n && loadstate.loaded[idx + d]) return idx + d;
    }
    return null;
  }

  // v0.28.1: 回合 payload 的 URL 带上 schema 版本号。浏览器对 /turn/N 是带缓存的，
  // 上一次 SCHEMA_VERSION 升级（payload 新增 religions）时，旧结构的 body 一直被复用，
  // 前端只能退回 staticInfo 那份终局列表 —— 于是「第 1 回合就有 4 条信条的拜占庭」。
  // 服务端那头也从 max-age 改成 ETag + no-cache，两道一起堵。
  function turnURL(n) {
    const v = (staticInfo && staticInfo.schema) ? ("?v=" + staticInfo.schema) : "";
    return `/api/replay/${seed}/turn/${n}${v}`;
  }

  async function fetchTurn(idx, seq = replaySeq) {
    if (seq !== replaySeq) return null;
    const t = turns[idx]; if (!t) return null;
    if (turnCache.has(t.turn)) return turnCache.get(t.turn);
    const payload = await getReplayJSON(turnURL(t.turn));
    if (seq !== replaySeq) return null;
    turnCache.set(t.turn, payload);
    if (turnCache.size > TURN_CACHE_MAX) turnCache.delete(turnCache.keys().next().value);
    return payload;
  }

  async function loadTurn(idx, seq = replaySeq) {
    if (seq !== replaySeq) return;
    if (!turns.length) return;
    const snapped = nearestLoadedIndex(idx);
    if (snapped == null) return;
    idx = snapped;
    const request = ++turnSeq;
    $("turn-slider").value = idx;
    const payload = await fetchTurn(idx, seq);
    if (!payload || seq !== replaySeq || request !== turnSeq) return;
    await ensureNames(payload, seq);
    if (seq !== replaySeq || request !== turnSeq) return;
    currentTurn = payload;
    currentTurnIndex = idx;        // v0.40: 旅游业绩要按时间轴找上一个存档
    // Replace rather than push: refresh restores this view without adding a
    // browser-history entry for every slider movement. Ignore stale requests.
    const url = new URL(location.href);
    url.searchParams.set("seed", String(seed));
    url.searchParams.set("turn", String(payload.turn));
    if (url.href !== location.href) history.replaceState(history.state, "", url.href);
    if (map) {
      map.padding = mapPadding();
      map.setData(payload, {
        names, players: staticInfo.players,
        wrapX: staticInfo.wrapX,
        buildingDistrict: staticInfo.buildingDistrict,
        buildingCost: staticInfo.buildingCost,
        luxuryResources: staticInfo.luxuryResources,
        wallDefense: staticInfo.wallDefense,
        yieldMeta: staticInfo.yieldMeta,
        yieldOrder: staticInfo.yieldOrder,
      });
    }
    const maxTurn = turns.length ? turns[turns.length - 1].turn : payload.turn;
    const curTurn = Math.max(0, payload.turn);
    $("turn-label").textContent = `${L("回合 ")}${curTurn} / ${maxTurn}`;
    // v0.27: the search index is per turn, so it is rebuilt right after
    // ``setData``.
    if (map) runSearch();
    applyPanels();
    renderHUD(payload);
    if (map) {
      buildNav(payload);
      if (!map._fittedOnce) { restoreMapView(); map._fittedOnce = true; }
      renderNav();
    }
    refreshCityPanel();
    for (const d of [-2, -1, 1, 2]) {
      const j = idx + d;
      if (j < 0 || j >= turns.length) continue;
      fetchTurn(j, seq).then(() => {
        // v0.40: 上一回合的 payload 回来之后，旅游业绩才算得出来 —— 重画一次
        // （只在还停在同一回合时画，避免翻回合时闪一下旧数据）
        if (seq === replaySeq && request === turnSeq && j === idx - 1 && currentTurn === payload) {
          renderHUD(currentTurn);
        }
      }).catch(() => {});
    }
    if (map && map.selected >= 0 && !panels.tile.hidden) onSelectTile(map.selected, true);
    refreshShareText();             // v0.38: 链接里的 turn 跟着当前回合走
  }

  async function ensureNames(payload, seq = replaySeq) {
    const need = new Set();
    const push = (v) => { if (v != null && v !== -1 && (v >>> 0) !== 0xFFFFFFFF) need.add(hashStr(v)); };
    for (const col of ["terrain", "feature", "resource", "improvement", "district", "wonder",
                       "continent"]) {
      (payload.tiles[col] || []).forEach(push);
    }
    (payload.units || []).forEach((u) => push(u.type));
    // v0.25 (文档 C2): the civ card shows the leader portrait, the age icon, the
    // dedication names, the researched tech / civic lists and the religion zone,
    // so those hashes have to be resolved as well (else they render as hex).
    // NOTE: the leader hash lives on ``staticInfo.players`` (the turn payload has
    // no leader field), so both statics have to be swept as well.
    // v0.28: the religion zone also lists each religion's beliefs (2 to 4
    // belief hashes), so those have to be resolved as well.
    // v0.28.1: the zone reads the *per-turn* list only, so that is the one to
    // sweep (the static list is no longer used by the UI at all).
    (payload.religions || []).forEach((r) => {
      push(r.symbol);
      (r.beliefs || []).forEach(push);
    });
    ((staticInfo && staticInfo.players) || []).forEach((q) => push(q.leader));
    (payload.players || []).forEach((p) => {
      push(p.leader);
      (p.techResearched || []).forEach(push);
      (p.civicResearched || []).forEach(push);
      (p.commemorations || []).forEach(push);
      push(p.pantheon);
      // v0.31: 核武器库存的种类（核装置 / 热核装置）也要能解析出名字与图标
      Object.keys(p.wmd || {}).forEach((h) => push(Number(h)));
      Object.keys(p.resources || {}).forEach((h) => push(Number(h)));
      (p.cities || []).forEach((c) => {
        (c.currentProds || []).forEach(push);
        Object.keys(c.built || {}).forEach(push);
        push(c.governor);
        // v0.34: 总督点过的晋升（类型哈希）也要能解析——表里没有的规则集
        // 至少还能靠 gamedb 快照给出名字，而不是直接显示十六进制。
        (c.governorPromotionHashes || []).forEach(push);
        push(c.religion);   // v0.25: religion icon on the city bar (PLAN B4)
      });
      (p.districts || []).forEach((d) => push(d.type));
      (p.currentTech || []).forEach(push); (p.currentCivic || []).forEach(push);
      (p.policies || []).forEach((slot) => slot.forEach(push));
      push(p.government);
    });
    const missing = [...need].filter((h) => !names[h]);
    const CHUNK = 200;
    for (let i = 0; i < missing.length; i += CHUNK) {
      if (seq !== replaySeq) return;
      const part = missing.slice(i, i + CHUNK).join(",");
      const profile = (staticInfo && (staticInfo.identityProfile || staticInfo.balanceMod)) || "vanilla";
      const res = await getJSON(`/api/gamedb/names?hashes=${part}&profile=${encodeURIComponent(profile.toLowerCase())}`);
      if (seq !== replaySeq) return;
      Object.assign(names, res);
    }
    // Replay-local aliases also feed the map's city religion icons. Reapply
    // after name requests so raw unknown hashes cannot overwrite the aliases.
    for (const [h, fallback] of Object.entries((staticInfo && staticInfo.religionFallbacks) || {})) {
      names[h] = {name: unknownReligionName(fallback.number), type: "", icon: fallback.icon};
    }
  }

  function unknownReligionName(number) {
    return (document.documentElement.lang === "en" ? "Unknown Religion " : "未知宗教") + number;
  }

  function nameOf(hash) {
    if (hash == null || (hash >>> 0) === 0xFFFFFFFF) return "—";
    const e = names[hashStr(hash)];
    return e ? e.name : ("0x" + hashStr(hash));
  }
  function iconOf(hash) { const e = names[hashStr(hash)]; return e && e.icon ? "/assets/icons/" + e.icon : null; }

  function nameHTML(hash) {
    if (hash == null || (hash >>> 0) === 0xFFFFFFFF) return "—";
    const e = names[hashStr(hash)];
    const raw = e ? e.name : ("0x" + hashStr(hash));
    const type = e ? (e.type || "") : "";
    if (raw.indexOf("0x") === 0) return type || raw;
    return showType && type ? `${raw}<span class="en">${type}</span>` : raw;
  }
  function typeTag(str) { return showType && str ? `<span class="en">${str}</span>` : ""; }

  function escapeText(value) {
    return String(value || "").replace(/[&<>"']/g, c =>
      ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  }

  // The same offline glyph catalog covers every captured description.
  function ruleTextHTML(text) {
    const profile = (staticInfo && (staticInfo.identityProfile || staticInfo.balanceMod)) || "vanilla";
    return window.Civ6RuleText.render(text, profile);
  }

  function leaderSkillsHTML(info, ip, prefix = "civ") {
    const key = ip + ":skills", open = !!expanded[key];
    const groups = [[L("文明技能"), "civilization"], [L("领袖技能"), "leader"]];
    return `<div id="${prefix}-skills-${ip}" class="leader-skills${open ? "" : " hidden"}">` +
      groups.map(([label, kind]) => {
        const skills = (info.abilities || {})[kind] || [];
        return `<div class="zone-title">${label}</div>` + (skills.length ? skills.map(s =>
          `<div class="skill-name">${escapeText(s.name)}</div>` +
          `<div class="rule-description">${ruleTextHTML(s.description)}</div>`).join("") :
          L('<div class="muted">尚未采集当前规则集的技能文本。</div>'));
      }).join("") + `</div>`;
  }

  function leaderPortraitHTML(info, ip, portrait, prefix = "civ") {
    const open = !!expanded[ip + ":skills"];
    return `<button type="button" class="leader-trigger" data-skills="${ip}" ` +
      `aria-expanded="${open}" aria-controls="${prefix}-skills-${ip}" ` +
      `${L("title=\"查看文明和领袖技能\" aria-label=\"")}${escapeText(info.leaderName || L("领袖"))}${L("：文明和领袖技能\">")}` +
      `<img class="${prefix === "cmp" ? "cmp-portrait" : "leader-portrait"}" src="${portrait}" alt=""></button>`;
  }

  function wireRuleDetails(box) {
    box.querySelectorAll(".leader-skills").forEach(detail => {
      detail.onclick = ev => ev.stopPropagation();
      detail.onpointerdown = ev => ev.stopPropagation();
    });
    box.querySelectorAll(".leader-trigger").forEach(button => {
      button.onclick = ev => {
        ev.stopPropagation();
        const key = button.dataset.skills + ":skills";
        expanded[key] = !expanded[key];
        button.setAttribute("aria-expanded", String(expanded[key]));
        const detail = box.querySelector('[id="' + button.getAttribute("aria-controls") + '"]');
        if (detail) detail.classList.toggle("hidden", !expanded[key]);
      };
      button.onkeydown = ev => ev.stopPropagation();
      button.onpointerdown = ev => ev.stopPropagation();
    });
    box.querySelectorAll(".policy-card").forEach(detail => {
      detail.ontoggle = () => { expanded[detail.dataset.expandKey] = detail.open; };
    });
  }

  // v0.25 (文档 C): a hash whose name could not be resolved shows "—" instead of
  // a raw hex string (data gaps such as a missing belief / civ-icon entry).
  function nameOrDash(hash) {
    if (hash == null || (hash >>> 0) === 0xFFFFFFFF) return "—";
    const s = nameOf(hash);
    return s.indexOf("0x") === 0 ? "—" : s;
  }

  // v0.34: 总督晋升词条。名字随规则集变（CCB 的「外汇资金」= BBG 的「国际贸易」、
  // CCB 的「住房扩建」= 原版的「自来水工程」），所以表跟着 staticInfo 走，
  // **不并进全局 names**（names 在多次回放之间复用，混进 MOD 译名会串味）；
  // 查不到的晋升退回 nameOf（gamedb 快照）再退回十六进制。
  function govPromoTable() { return (staticInfo && staticInfo.governorPromotions) || null; }

  function govPromoName(h) {
    const t = govPromoTable();
    const hit = t && t.names ? t.names[hashStr(h)] : null;
    return hit || nameOf(h);
  }

  // 该总督的晋升按「城市总督页」顺序（树层级；数据文件里的 promotions 数组顺序）
  // 排好，顺序表里没有的排在最后。
  function govPromoList(govHash, hashes) {
    const t = govPromoTable();
    const seq = (t && t.order && t.order[hashStr(govHash)]) || [];
    const idx = new Map(seq.map((s, i) => [s, i]));
    const rank = (h) => (idx.has(hashStr(h)) ? idx.get(hashStr(h)) : 1e9);
    return (hashes || []).slice()
      .sort((a, b) => rank(a) - rank(b))
      .map((h) => ({ hash: h, name: govPromoName(h) }));
  }

  // 城市面板「总督」一格：`莫克夏` + `晋升：鉴赏家、神圣建筑师`
  function governorCellHTML(c) {
    if (c.governor == null || (c.governor >>> 0) === 0xFFFFFFFF) return "—";
    const items = govPromoList(c.governor, c.governorPromotionHashes);
    if (!items.length) {
      const n = c.governorPromotions || 0;
      return nameOrDash(c.governor) + (n ? `${L("（晋升 ")}${n}）` : "");
    }
    const names = items.map((it) => it.name).join("、");
    return `${nameOrDash(c.governor)}${L("<div class=\"gov-promo\">晋升：")}${names}</div>`;
  }

  // v0.31: 核污染（`tiles.fallout`，每格一个「剩余回合数」，0 = 未受污染）。
  // 核装置炸出的污染从 10 回合起算，每回合减 1；热核装置是 20 回合起算。
  function falloutText(turns) {
    const n = Number(turns) || 0;
    return n > 0 ? (L("剩余 ") + n + L(" 回合")) : L("无");
  }

  // ``tiles.road`` is the zero-based route index (0 = 远古时代道路 … 4 = 铁路),
  // 255 = no route at all; the display names come from ``staticInfo.routeNames``.
  function routeName(index) {
    if (index == null || index === 255 || index < 0) return L("无");
    const table = (staticInfo && staticInfo.routeNames) || {};
    return table[String(index)] || (L("路线 ") + index);
  }

  // v0.25 (文档 C1): continent = the snapshot's CONTINENT_* name
  // (``LOC_<TYPE>_DESCRIPTION``).  0xFFFFFFFF = no continent / open water.
  // v0.27: the 「大陆 N」 number is gone - the panel and the search index only
  // use the name, and an unnamed continent falls back to the bare word 大陆.
  function isContinent(hash) {
    return hash != null && (hash >>> 0) !== 0xFFFFFFFF;
  }

  function continentName(hash) {
    const nm = nameOf(hash);
    return nm.indexOf("0x") === 0 ? "" : nm;
  }

  function continentLabel(hash) {
    if (!isContinent(hash)) return "—";
    return continentName(hash) || L("大陆");
  }

  // 城墙：``wall`` 是城墙等级（0 = 无），``wallDamage`` 是城墙已受伤害；
  // 剩余 = 上限 − 伤害（上限取游戏库 Buildings.OuterDefenseHitPoints = 75）。
  // --- v0.26 城墙 / 城市防御 ------------------------------------------------
  // 上限：该城 `built` 命中的墙建筑里 `order` 最大者的 HP（order 由 build_gamedb
  // 按 Cost 升序编号，BBG 三档同为 75 也能定档）；`built` 里没有墙建筑时退回
  // 「wall 等级 → order」这一档。业主研了钢铁则改用快照里的 STEEL 城市防御值。
  function wallTable() {
    const wd = staticInfo && staticInfo.wallDefense;
    return (wd && wd.buildings) || {};
  }

  function ownerKnowsSteel(iPlayer) {
    const wd = staticInfo && staticInfo.wallDefense;
    if (!wd || wd.steelTech == null) return false;
    const p = ((currentTurn && currentTurn.players) || [])
      .find((x) => x.iPlayer === iPlayer);
    if (!p) return false;
    const steel = wd.steelTech >>> 0;
    return (p.techResearched || []).some((h) => (h >>> 0) === steel);
  }

  // ``{hash, hp, max, steel}`` of the city's strongest wall, or null (no walls).
  function cityWall(iPlayer, city) {
    const table = wallTable();
    const level = Number(city && city.wall) || 0;
    const dmg = Number(city && city.wallDamage) || 0;
    if (!Object.keys(table).length) {
      // snapshot predates the wall table: keep the old "has walls" signal
      return (level > 0 || dmg > 0) ? { hash: null, hp: 0, max: 0, steel: false } : null;
    }
    let best = null;
    const built = (city && city.built) || {};
    for (const k in built) {
      const h = String(parseInt(k, 10) >>> 0);
      const e = table[h];
      if (e && (!best || e.order > best.order)) best = { hash: h, hp: e.hp, order: e.order };
    }
    if (!best && level > 0) {
      for (const h in table) {
        const e = table[h];
        if (e.order === level - 1) { best = { hash: h, hp: e.hp, order: e.order }; break; }
      }
    }
    if (!best) return null;
    const wd = (staticInfo && staticInfo.wallDefense) || {};
    const steel = !!(wd.urbanDefense && ownerKnowsSteel(iPlayer));
    const max = steel ? Number(wd.urbanDefense) : (Number(best.hp) || 0);
    return { hash: best.hash, hp: best.hp, max: max, steel: steel };
  }

  // 剩余 = max(0, 上限 − 已受伤害)；研了钢铁统一显示「城市防御 剩余 / 上限」，
  // 否则显示「墙建筑名 剩余 / 上限」。
  function wallText(iPlayer, city, damage) {
    const w = cityWall(iPlayer, city);
    if (!w) return L("无");
    if (!w.max) return "—";           // pre-v0.26 snapshot without caps
    const rem = Math.max(0, w.max - (Number(damage) || 0));
    if (w.steel) return `${L("城市防御 ")}${rem} / ${w.max}`;
    const name = w.hash ? nameOrDash(parseInt(w.hash, 10)) : "";
    return `${name ? name + " " : ""}${rem} / ${w.max}`;
  }

  // 城市中心以外的区域没有城墙（payload 里也只有市中心带 wall/wallDamage）
  function districtWallText(d, host, iPlayer) {
    if ((d.type >>> 0) !== DISTRICT_CITY_CENTER || !host) return L("无");
    return wallText(iPlayer, host, d.wallDamage);
  }

  function chipHTML(hash) {
    const ic = iconOf(hash);
    return `<span class="chip">${ic ? `<img src="${ic}" alt="">` : ""}${nameOrDash(hash)}</span>`;
  }

  // C2: the pantheon hash resolves through A's belief entries (0xAE817BA9 =
  // 宗教移民 on the sample save); a hash that still has no entry renders as "—"
  // rather than as raw hex (see the README's known limitations).
  function pantheonHTML(hash) {
    if (hash == null || (hash >>> 0) === 0xFFFFFFFF) return "<span class='muted'>—</span>";
    if (nameOf(hash).indexOf("0x") === 0) return "<span class='muted'>—</span>";
    return chipHTML(hash);
  }

  // v0.26: 「已研科技 N / 总数」是详情框里的一行内联展开项（点击才展开 chips），
  // 不再用 hover 弹层。``key`` 与同卡的其它展开项共用一个 ``expanded`` 命名空间。
  function researchedRowHTML(label, list, total, key, iPlayer) {
    const items = list || [];
    const body = items.length
      ? items.map(chipHTML).join("")
      : "<span class='muted'>—</span>";
    const open = !!expanded[iPlayer + ":" + key];
    return `<div class="hud-row inline has-detail" data-row="${key}">` +
      `<span class="hval">${label} ${items.length} / ${total || 0}</span>` +
      `<span class="hcaret">${open ? "▾" : "▸"}</span></div>` +
      `<div class="hud-detail${open ? "" : " hidden"}" data-detail="${key}">${body}</div>`;
  }

  // C2 + v0.28: 该文明创立的宗教（正名 / 图标）以及它的信条 ——
  // ``religions[].beliefs`` 与 ``players[].pantheon`` 同属 belief 哈希空间，
  // 只是信条换不到图标（`assets/icons/` 里没有 belief 素材）。
  // 快照里查不到的 belief 走 ``nameOrDash()`` 显示「—」而不画十六进制，
  // 计数仍按存档里的条数走，所以「信条 2 / 4」能直接看出这个宗教还没补满。
  //
  // v0.28.1: 宗教是**每回合**的状态（创立那回合才有，信条之后慢慢补齐），
  // 所以这里必须用当前回合 payload 的 ``religions``；``staticInfo.religions``
  // 取的是该局**最后一个**存档，早先拿它渲染会让第 1 回合就挂着一个满信条的
  // 宗教。静态那份只保留给 ``religionName()`` 兜底（v0.28.1 前的旧缓存）。
  function religionsNow() {
    // 只认当前回合 payload 的 ``religions``：旧后端 / 旧缓存没有这个字段时，宁可
    // 什么都别显示（「未创立宗教」），也**绝不**退回 ``staticInfo.religions`` ——
    // 那是"最后一个存档"的终局列表，正是第 1 回合就冒出满信条宗教的成因。
    return (currentTurn && currentTurn.religions) || [];
  }

  function religionZoneHTML(p) {
    const founded = religionsNow().filter((r) => r.iPlayer === p.iPlayer);
    const rel = founded.length
      ? founded.map((r) => {
          const ic = iconOf(r.symbol);
          const name = religionName(r.symbol);
          const beliefs = r.beliefs || [];
          const creed = beliefs.length
            ? beliefs.map((h) => `<span class="chip">${nameOrDash(h)}</span>`).join("")
            : "<span class='muted'>—</span>";
          return `<div class="rel-block">` +
            `<span class="chip">${ic ? `<img src="${ic}" alt="">` : ""}${name}</span>` +
            `${L("<div class=\"zone-title\">信条 ")}${beliefs.length} / ${BELIEF_MAX}</div>` +
            `${creed}</div>`;
        }).join("")
      : L("<span class='muted'>未创立宗教</span>");
    return `${L("<div class=\"zone-title\">宗教</div>")}${rel}` +
      `${L("<div class=\"zone-title\">万神殿</div>")}${pantheonHTML(p.pantheon)}`;
  }

  function eraProgressHTML(p) {
    const score = p.eraPoint, normal = p.eraNormalThreshold, golden = p.eraGoldenThreshold;
    if (![score, normal, golden].every(Number.isInteger) ||
        score < 0 || normal < 0 || golden < 0 || normal > golden) return "";
    const targetGolden = score >= normal;
    const reachedGolden = score >= golden;
    const target = targetGolden ? golden : normal;
    const targetAge = targetGolden ? (Number(p.ageState) === 0 ? 3 : 2) : 1;
    const label = AGE_ZH[targetAge];
    const remaining = Math.max(0, target - score);
    return `<span class="era-progress${reachedGolden ? " era-golden" : ""}" ` +
      `${L("title=\"时代分数 ")}${score}${L("；普通阈值 ")}${normal}${L("；黄金阈值 ")}${golden}；` +
      `${reachedGolden ? L("已达到黄金阈值") : `${L("距")}${label}${L("还差 ")}${remaining}${L(" 分")}`}">` +
      `<span>${score}/${target}</span><img class="ci-icon" ` +
      `src="/assets/icons/icon/${AGE_ICON[targetAge]}_Age.png" alt="${label}"></span>`;
  }

  // C2: leader portrait + age + dedications + player / Steam identity, shown
  // under the leader name; the Steam block is skipped for AI (steamId === null).
  function civInfoHTML(p, info) {
    const age = Number(p.ageState);
    const ageIcon = AGE_ICON[age] ? `/assets/icons/icon/${AGE_ICON[age]}_Age.png` : null;
    const dedications = (p.commemorations || []).map(chipHTML).join("");
    let lines = `<div class="ci-line">${ageIcon ? `<img class="ci-icon" src="${ageIcon}" alt="">` : ""}` +
      `<span>${AGE_ZH[age] || "—"}</span>${eraProgressHTML(p)}</div>`;
    lines += `${L("<div class=\"ci-line\"><span class=\"ci-key\">着力点</span>")}` +
      `<span class="ci-val">${dedications || "<span class='muted'>—</span>"}</span></div>`;
    if (info.pseudo) {
      lines += `${L("<div class=\"ci-line\"><span class=\"ci-key\">玩家</span>")}` +
        `<span class="ci-val">${info.pseudo}</span></div>`;
    }
    if (info.steamId) {
      lines += `<div class="ci-line"><span class="ci-key">SteamID</span><span class="ci-val">` +
        `<a href="https://steamcommunity.com/profiles/${info.steamId}" target="_blank" ` +
        `rel="noopener">${info.steamId}</a></span></div>`;
      lines += `${L("<div class=\"ci-line\"><span class=\"ci-key\">社区名</span>")}` +
        `<span class="ci-val steam-name" data-steamid="${info.steamId}">…</span></div>`;
    }
    const portrait = iconOf(info.leader);
    return `<div class="civ-info">` +
      (portrait ? leaderPortraitHTML(info, p.iPlayer, portrait) : "") +
      `<div class="civ-info-body">${lines}</div></div>` + leaderSkillsHTML(info, p.iPlayer);
  }

  // C2: Steam community name.  Try the profile XML directly (5 s, aborted
  // afterwards), fall back to the local proxy, then to "查询失败"; the outcome is
  // remembered per steamid in sessionStorage so a card re-render never re-queries.
  const STEAM_CACHE_PREFIX = "civ6replay.steamName.";
  async function steamName(steamid) {
    const key = STEAM_CACHE_PREFIX + steamid;
    try {
      const cached = sessionStorage.getItem(key);
      if (cached) return cached;
    } catch (e) {
      if (e.name === "AbortError") return; /* sessionStorage may be unavailable */ }
    let name = null;
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 5000);
      try {
        const resp = await fetch(`https://steamcommunity.com/profiles/${steamid}?xml=1`,
          { signal: ctrl.signal });
        if (resp.ok) {
          const txt = await resp.text();
          const m = txt.match(/<steamID>\s*(?:<!\[CDATA\[([\s\S]*?)\]\]>|([^<]*))\s*<\/steamID>/);
          const v = m ? ((m[1] || m[2] || "").trim()) : "";
          if (v) name = v;
        }
      } finally { clearTimeout(timer); }
    } catch (e) {
      if (e.name === "AbortError") return; name = null; }
    if (!name) {
      try {
        const viaProxy = await getJSON(`/api/steam/name/${steamid}`);
        if (viaProxy && viaProxy.name) name = viaProxy.name;
      } catch (e) {
      if (e.name === "AbortError") return; name = null; }
    }
    const out = name || L("查询失败");
    try { sessionStorage.setItem(key, out); } catch (e) {
      if (e.name === "AbortError") return; /* ignore */ }
    return out;
  }

  // C6: the top banner carries the short notice, the left sidebar the details;
  // ``tailWarnings`` are debug-only and never reach the UI.
  function renderLayerErrors(info) {
    const box = $("layer-errors");
    if (!box) return;
    const errs = (info && info.layerErrors) || [];
    if (!errs.length) { box.innerHTML = ""; box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    box.innerHTML = `${L("<h3>解析降级</h3>")}` + errs.map((e) => {
      const off = (e.offset == null) ? "" : ` @0x${(e.offset >>> 0).toString(16)}`;
      return `<div class="layer-err"><b>${e.section}${off}</b>：${e.message || ""}</div>`;
    }).join("");
  }

  // v0.24: yields as icons, three per row (食物 产能 金币 / 科技 文化 信仰);
  // v0.26 the tile panel's 基础产出 reuses the same grid.
  // v0.27: the tile panel drops the zero entries and puts the rest on one line.
  let CITY_YIELD_CELLS;

  function yieldValue(yields, name) {
    return Number((yields || {})[YIELD_BY_NAME[name]]) || 0;
  }

  function yieldCell(name, icon, v) {
    return `<span class="ycell" title="${name}"><img src="${icon}" alt="${name}">` +
      `<b>${fmtNum(v)}</b></span>`;
  }

  function yieldGrid(yields) {
    const cells = CITY_YIELD_CELLS
      .map(([name, icon]) => yieldCell(name, icon, yieldValue(yields, name)))
      .join("");
    return `<div class="yield-grid">${cells}</div>`;
  }

  // 格子面板的「基础产出」：非零项才显示（全零时只留一个「—」），一行排完。
  function tileYieldGrid(yields) {
    const cells = CITY_YIELD_CELLS
      .map(([name, icon]) => [name, icon, yieldValue(yields, name)])
      .filter((cell) => cell[2] !== 0)
      .map(([name, icon, v]) => yieldCell(name, icon, v))
      .join("");
    return `<div class="yield-grid one-line">${cells ||
      `<span class="muted">—</span>`}</div>`;
  }

  function adjacencyYieldHTML(yields) {
    const cells = CITY_YIELD_CELLS.map(([name, icon]) => {
      const value = Number((yields || {})[YIELD_BY_NAME[name]]);
      if (!Number.isFinite(value)) return "";
      const meta = (staticInfo.yieldMeta || {})[YIELD_BY_NAME[name]] || {};
      return `<span class="adjacency-value" title="${name}" style="color:${meta.color || "inherit"}">` +
        `<img src="${icon}" alt="${name}"><b>${value >= 0 ? "+" : ""}${fmtNum(value)}</b></span>`;
    }).join("");
    return cells || '<span class="muted adjacency-zero">0</span>';
  }

  function districtAdjacencyHTML(d) {
    if (d.adjacency == null) return L('<span class="district-adjacency muted" title="相邻加成暂不可用">—</span>');
    const label = d.built === 0 ? L("预计相邻") : L("基础相邻");
    return `<span class="district-adjacency" title="${label}">${adjacencyYieldHTML(d.adjacency)}</span>`;
  }

  function adjacencySourcePanel(d) {
    const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
      c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    let html = L('<div class="adjacency-section"><div class="kv"><div class="k">相邻加成</div>') +
      `<div class="v">${d.adjacency == null ? L('<span class="muted">暂不可用</span>') :
        districtAdjacencyHTML(d) + (d.built === 0 ? L('<span class="muted">（预计）</span>') : '')}</div></div>`;
    if (d.adjacency == null) return html + '</div>';
    html += L('<details class="adjacency-details"><summary>相邻加成来源</summary>');
    const groups = new Map();
    for (const row of (d.adjacencySources || [])) {
      const key = JSON.stringify([row.label, row.origin, row.required, row.rate]);
      if (!groups.has(key)) groups.set(key, {label: row.label, origin: row.origin, required: row.required,
        rate: row.rate, count: 0, yields: {}, tiles: new Set()});
      const group = groups.get(key);
      group.count += Number(row.count) || 0;
      if (row.yield) group.yields[row.yield] = (group.yields[row.yield] || 0) + (Number(row.amount) || 0);
      for (const index of (row.tiles || [])) group.tiles.add(index);
    }
    for (const group of groups.values()) {
      const rate = `${Number(group.rate) >= 0 ? "+" : ""}${fmtNum(Number(group.rate))}`;
      const rule = group.required == null ? '' : group.tiles.size ?
        `${group.count}${L(" 格，每 ")}${group.required}${L(" 格 ")}${rate}` : `${L("单项 ")}${rate}`;
      const coordinates = showCoord ? Array.from(group.tiles)
        .filter(i => Number.isInteger(i) && i >= 0)
        .map(i => `<a href="#" class="adjacency-coordinate" data-jump-i="${i}">` +
          `(${i % currentTurn.width},${Math.floor(i / currentTurn.width)})</a>`) : [];
      html += `<div class="adjacency-source"><div class="adjacency-source-head"><span>${esc(group.label)}</span>` +
        `<span>${adjacencyYieldHTML(group.yields)}</span></div>` +
        `<div class="adjacency-source-note">${esc([group.origin, rule].filter(Boolean).join(" · "))}</div>` +
        (coordinates.length ? `<div class="adjacency-source-note adjacency-coordinates">${coordinates.join("、")}</div>` : '') + '</div>';
    }
    if (!groups.size) html += `<div class="muted adjacency-source-note">${d.adjacencySources == null ?
      L('该回合尚无来源明细') : L('无生效的相邻来源')}</div>`;
    html += L('<div class="adjacency-source-note">未建成的邻接区域不计入；不含政策倍率和普通建筑产出。</div>');
    return html + '</details></div>';
  }

  // ``damage`` is damage *taken*; show remaining HP (upstream: health - damage).
  // v0.25: no more "生命/血量 x/y" wording - the game's health bar (same colours
  // as the map) plus the numbers, so a damaged unit reads at a glance.
  function unitHP(u) {
    const hpMax = u.hpMax || 100;
    const hp = (u.hp == null) ? Math.max(0, hpMax - (Number(u.damage) || 0)) : u.hp;
    return { hp: hp, hpMax: hpMax, ratio: hpMax ? hp / hpMax : 0 };
  }

  function unitHealthHTML(u) {
    const h = unitHP(u);
    if (h.ratio >= 1) return "";
    const cls = h.ratio > 0.6 ? "ok" : (h.ratio > 0.3 ? "warn" : "bad");
    const pct = Math.max(0, Math.min(100, h.ratio * 100));
    return `${L("<span class=\"hp\" title=\"血量 ")}${h.hp}/${h.hpMax}">` +
      `<i class="${cls}" style="width:${pct}%"></i></span>` +
      `<span class="hp-num">${h.hp}/${h.hpMax}</span>`;
  }

  // 普通单位晋升次数 = ``level - 1``；末日机甲按所属玩家已研科技计算四项自动晋升。
  // 机甲自带 +2 等级（GDR_VETERAN_NAME），不能当作晋升次数。
  function unitPromotionCount(u) {
    if ((names[hashStr(u.type)] || {}).type === "UNIT_GIANT_DEATH_ROBOT") {
      const owner = ((currentTurn && currentTurn.players) || [])
        .find((p) => p.iPlayer === u.iPlayer);
      const researched = new Set(((owner && owner.techResearched) || [])
        .map((h) => (names[hashStr(h)] || {}).type));
      return [...GDR_PROMOTION_TECHS].filter((type) => researched.has(type)).length;
    }
    return Math.max(0, (Number(u.level) || 1) - 1);
  }

  // 所有至少晋升一次的单位都显示游戏里的晋升图标（[ICON_PROMOTION]，
  // 见 tools/vendor_promotion_icon.py）；编制星标（军团 / 军队）不走这里。
  function unitPromotionHTML(u) {
    const n = unitPromotionCount(u);
    if (n < 1) return "";
    return `${L("<span class=\"promo\" title=\"晋升 ")}${n}${L(" 次\"><img src=\"")}${ICON_PROMOTION}" alt="">` +
      `<b>${n}</b></span>`;
  }

  function isMilitaryUnit(u) {
    return (u.cat || "mil") === "mil";
  }

  // 单位坐标是可选的非关键信息（顶栏「坐标」勾选后才显示）
  function unitCoordText(u) {
    return showCoord ? ` · (${u.x},${u.y})` : "";
  }

  // --- v0.28.3 观察者（Spectator） -----------------------------------------
  // 「旁观者」模组会给对局塞一个只做观察、不参与游戏的玩家（文明
  // ``CIVILIZATION_SPECTATOR``，游戏内名称 Spectator）。右栏对它一律特殊对待：
  // 文明列表垫底、卡片只留身份、使者按 0 计、不进对比表。
  function isSpectator(info) {
    if (!info) return false;
    if (String(info.civStr || "") === "CIVILIZATION_SPECTATOR") return true;
    // 名录解析不到 TYPE 时按名字兜底（去掉 ``[COLOR_…]…[ENDCOLOR]`` 后再比）
    const name = String(info.civName || "").replace(/\[[^\]]*\]/g, "").trim();
    return name.toLowerCase() === "spectator";
  }
  function isSpectatorPlayer(ip) { return isSpectator(playerInfo(ip)); }

  // 使者表 ``{sender_iPlayer: count}`` 去掉观察者（视为 0 个），其余原样保留。
  // 城邦页的进度条 / 宗主判定与文明卡的「宗主城邦」列表都吃这一份。
  function emissariesOf(p) {
    const em = (p && p.emissaries) || {};
    const out = {};
    for (const k of Object.keys(em)) {
      const ip = parseInt(k, 10);
      const cnt = Number(em[k]) || 0;
      if (cnt > 0 && !isSpectatorPlayer(ip)) out[ip] = cnt;
    }
    return out;
  }

  // --- v0.40 旅游业绩 / 文化胜利进度 --------------------------------------
  // 存档只给「对每个对手累积的旅游业绩」（``players[].tourismByPlayer``），所以
  // 「旅游业绩 / 回合」只能由相邻两个存档的**逐对手增量**算出（÷ 256，定点还原），
  // 再从这一组流量里反推出**没有修正**的那个基准值 —— 就是游戏顶栏 / 世界排名里
  // 那个 GetTourism()（玩家实测：罗马（图拉真）回合 90 的一组流量是
  // 56.5 / 111 / 113 / 56.5 / 55.5 / 56.5 / 84.75，游戏顶栏下一回合是 123，
  // 而 -50%（不同政体）之类的修正正落在那些 56.5 上，所以基准 = 113）。
  // 返回 ``undefined`` = 上一个存档还没到（先显示 …，预取回来后会重画），
  // ``null`` = 没有可算的基准（时间轴上第一个存档 / 没有对手的玩家）。
  function fitTourismBase(flows) {
    const cands = [...new Set(flows.map((v) => Math.round(v * 100) / 100))]
      .sort((a, b) => b - a);
    const need = Math.max(2, Math.ceil(flows.length * 2 / 3));
    for (const base of cands) {
      if (!(base > 0)) continue;
      let hits = 0;
      for (const v of flows) {
        if (TOURISM_MODS.some((m) => Math.abs(v - base * m) <= Math.max(0.025 * base * m, 0.06))) {
          hits++;
        }
      }
      if (hits >= need) return base;
    }
    return Math.max(...flows);
  }

  // ``{base, rows: [{ip, flow, accum}], gap}``；``undefined`` / ``null`` 见上。
  function tourismInfo(ip) {
    const cur = ((currentTurn && currentTurn.players) || [])
      .find((x) => x.iPlayer === ip);
    if (!cur || !cur.tourismByPlayer) return null;
    if (currentTurnIndex <= 0 || !turns.length) return null;
    const prev = turns[currentTurnIndex - 1];
    const prevPayload = turnCache.get(prev.turn);
    if (!prevPayload) return undefined;
    const before = (prevPayload.players || []).find((x) => x.iPlayer === ip);
    if (!before || !before.tourismByPlayer) return null;
    const gap = Math.max(1, (Number(currentTurn.turn) || 0) - (Number(prev.turn) || 0));
    const rows = [];
    for (const key of Object.keys(cur.tourismByPlayer)) {
      const was = Number(before.tourismByPlayer[key]) || 0;
      const now = Number(cur.tourismByPlayer[key]) || 0;
      if (!was || now < was) continue;       // 那时还没认识 / 还没开始攒旅游业绩
      rows.push({ ip: Number(key), flow: (now - was) / TOURISM_FIXED / gap,
                  accum: now / TOURISM_FIXED });
    }
    if (!rows.length) return null;
    return { base: fitTourismBase(rows.map((r) => r.flow)), rows: rows, gap: gap };
  }

  // 「文化」行正中间那个数：一位小数（游戏里也是 ``Round(GetTourism(), 1)``）
  function tourismText(ip) {
    const info = tourismInfo(ip);
    if (info === undefined) return "…";
    if (!info) return "—";
    return fmtNum(Math.round(info.base * 10) / 10);
  }

  // 悬停时把这一组逐文明流量也列出来（口径与游戏文化胜利面板的 tooltip 一致：
  // 「目前」= 本回合流量，「累积」= 存档里的累积值 ÷ 256），方便逐格核对。
  function tourismTitle(ip) {
    const head = L("旅游业绩 / 回合：游戏顶栏那个数。存档只存「对每个对手累积的") +
      L("旅游业绩」，这里用相邻两回合的逐文明增量反推（取能自洽的最大基准）");
    const info = tourismInfo(ip);
    if (!info) return head;
    const lines = info.rows
      .slice()
      .sort((a, b) => b.flow - a.flow)
      .map((r) => `　${(playerInfo(r.ip) || {}).civName || ("P" + r.ip)} ` +
        `${fmtNum(Math.round(r.flow * 10) / 10)}${L("（累积 ")}${fmtNum(Math.round(r.accum))}）`);
    return head + L("\n逐文明：本回合流量（累积 / 256）：\n") + lines.join("\n");
  }

  // 文化胜利进度 = 国际游客 / 需要超过的对手国内游客。分母与游戏
  // （``WorldRankings.lua`` 的 ``NumRequiredTourists``）一致：**对手**（不同队的
  // 存活完整文明）里最高的国内游客 + 1，因为要**超过**对手；城邦 / 蛮族 / 已灭亡
  // 的文明与观察者都不算对手。
  function requiredTourists(ip) {
    const mine = Number((playerInfo(ip) || {}).team);
    const knownTeam = Number.isFinite(mine) && mine !== 0xFFFFFFFF;
    let best = 0;
    for (const q of ((currentTurn && currentTurn.players) || [])) {
      if (q.iPlayer === ip) continue;
      const info = playerInfo(q.iPlayer) || {};
      if ((info.kind || "major") !== "major" || isSpectator(info)) continue;
      if (!(Number(q.cityCount) || 0)) continue;
      if (knownTeam && Number(info.team) === mine) continue;
      best = Math.max(best, Number(q.internalTourist) || 0);
    }
    return best + 1;
  }

  function cultureVictoryHTML(p) {
    const a = Number(p.externalTourist) || 0;
    const b = requiredTourists(p.iPlayer);
    return `${L("<div class=\"zone-title\">文化胜利</div>")}` +
      `<div class="cv-line">${fmtNum(a)} / ${fmtNum(b)}</div>`;
  }

  // --- HUD ---------------------------------------------------------------
  function renderHUD(payload) {
    const box = $("civ-hud"); box.innerHTML = "";
    const players = payload.players || [];
    const states = [], majors = [];
    for (const p of players) {
      const info = playerInfo(p.iPlayer) || {};
      const kind = info.kind || "major";
      if (kind === "free_cities" || kind === "barbarian") continue;
      if (hudTab === "city_state") {
        if (kind === "city_state") states.push({ p, info });
      } else if (kind === "major") {
        majors.push({ p, info });
      }
    }
    if (hudTab === "civ") {
      // v0.26 sort order (城邦页维持既有排序)
      const key = civSortKey(payload);
      majors.sort((a, b) => cmpKey(key(a), key(b)));
      // v0.28.3: 观察者永远垫底（稳定排序，其余文明顺序不变）
      majors.sort((a, b) => (isSpectator(a.info) ? 1 : 0) - (isSpectator(b.info) ? 1 : 0));
      if (!compareMode && panels.right.minimized) {
        renderCompactHUD(payload, majors);
        applyPanels();
        return;
      }
      for (const m of majors) {
        box.appendChild(isSpectator(m.info)
          ? spectatorCard(m.p, m.info) : majorCard(m.p, m.info, payload));
      }
    } else if (hudTab === "compare") {
      // v0.28.3: 观察者不进对比表
      renderCompare(payload, majors.filter((m) => !isSpectator(m.info)));
      syncLedgerControls();
      refreshLedgers();
      return;                      // the compare page fills #civ-hud itself
    }
    if (hudTab === "city_state") {
      // v0.23: living city states first, then flavour order, then the highest
      // envoy count, then the Chinese name (mirrors state.city_state_sort_key)
      // v0.28.3: 观察者的使者视为 0，既不算排序也不绘图
      const key = (s) => cityStateSortKey(s.p.cityCount, s.info.flavour,
        maxEmissary(emissariesOf(s.p)), s.info.civName);
      states.sort((a, b) => cmpKey(key(a), key(b)));
      for (const s of states) box.appendChild(cityStateCard(s.p, s.info));
    }
    if (!box.children.length) {
      const empty = document.createElement("div");
      empty.className = "loading";
      empty.textContent = hudTab === "city_state" ? L("本回合无可显示的城邦") : L("本回合无可显示的文明");
      box.appendChild(empty);
    }
    syncLedgerControls();
    refreshLedgers();
  }

  // --- v0.23 helper table -------------------------------------------------

  // ``army``: 0 / -1 = single unit, 1 = corps / fleet, 2 = army / armada
  function armyLabel(army, sea) {
    if (army === 1) return sea ? L("舰队") : L("军团");
    if (army === 2) return sea ? L("无敌舰队") : L("军队");
    return "";
  }
  function armyStars(army) {
    return army === 1 ? "★★" : (army === 2 ? "★★★" : "");
  }

  // city state suzerain: the sender with a unique highest envoy count >= 3
  function suzerainOf(emissaries) {
    const entries = Object.keys(emissaries || {})
      .map((k) => [parseInt(k, 10), Number(emissaries[k]) || 0])
      .filter((e) => e[1] > 0);
    if (!entries.length) return null;
    const top = Math.max(...entries.map((e) => e[1]));
    if (top < 3) return null;
    const winners = entries.filter((e) => e[1] === top);
    return winners.length === 1 ? winners[0][0] : null;
  }

  function maxEmissary(emissaries) {
    const v = Object.keys(emissaries || {}).map((k) => Number(emissaries[k]) || 0);
    return v.length ? Math.max(...v) : 0;
  }

  // mirrors state.city_state_sort_key: dead last, flavour order, envoys desc, name
  function cityStateSortKey(cityCount, flavour, maxEnv, name) {
    const order = CS_FLAVOUR_ORDER.indexOf(flavour || "");
    return [cityCount ? 0 : 1, order < 0 ? CS_FLAVOUR_ORDER.length : order,
            -maxEnv, name || ""];
  }

  function cmpKey(a, b) {
    for (let i = 0; i < a.length; i++) {
      if (a[i] < b[i]) return -1;
      if (a[i] > b[i]) return 1;
    }
    return 0;
  }

  // v0.26 文明卡排序：楼层 = payload 顺序（默认），其余降序 / 团队升序。
  // v0.26.1：同值的次要关键词固定为「楼层」（payload 顺序），不再按中文名。
  function civSortKey(payload) {
    const order = new Map();
    (payload.players || []).forEach((p, i) => order.set(p.iPlayer, i));
    const yv = (p, name) => Number(((p.yields || {})[YIELD_BY_NAME[name]]) || 0);
    return (m) => {
      const p = m.p, info = m.info || {};
      const floor = order.has(p.iPlayer) ? order.get(p.iPlayer) : 999;
      switch (civSort) {
        case "team": return [Number(info.team) || 0, floor];
        case "science": return [-yv(p, L("科技")), floor];
        case "culture": return [-yv(p, L("文化")), floor];
        case "cities": return [-(Number(p.cityCount) || 0), floor];
        case "production": return [-yv(p, L("产能")), floor];
        case "military": return [-(Number(p.militaryStrength) || 0), floor];
        case "age": return [-(Number(p.ageState) || 0), floor];
        default: return [floor, 0];
      }
    };
  }

  // stock with its per-turn change: ``90(+10)``
  function stockHTML(stock, perTurn) {
    const s = Number(stock) || 0, t = Number(perTurn) || 0;
    return `<span class="${s < 0 || t < 0 ? "neg" : ""}">${fmtNum(s)}` +
      `<span class="pct">(${t >= 0 ? "+" : ""}${fmtNum(t)})</span></span>`;
  }

  function ownedResourcesHTML(p, category, label, showStock) {
    const items = ((staticInfo && staticInfo[category]) || [])
      .filter(h => Number((p.resources || {})[hashStr(h)]) > 0);
    if (!items.length) return "";
    return `<div class="zone-title">${label}</div><div class="resource-inventory">` +
      items.map(h => {
        const name = nameOf(h), icon = iconOf(h);
        const safe = name.replace(/&/g, "&amp;").replace(/"/g, "&quot;")
          .replace(/</g, "&lt;").replace(/>/g, "&gt;");
        return `<span class="resource-item" data-resource="${hashStr(h)}" title="${safe}" tabindex="0" aria-label="${safe}">` +
          (icon ? `<img src="${icon}" alt="${safe}">` : `<span>${safe}</span>`) +
          (showStock ? `<span>${fmtNum(p.resources[hashStr(h)])}</span>` : "") + `</span>`;
      }).join("") + `</div>`;
  }

  function governmentHTML(p) {
    // Saved order: economic, military, diplomatic, wildcard (empty = NONE).
    const slots = p.policySlots || (p.policies || []).map(slot => slot.length);
    return `${L("<div class=\"zone-title\">政体</div>")}${nameHTML(p.government)}` +
      `<div class="policy-slots">` + [[L("军事"), 1], [L("经济"), 0], [L("外交"), 2], [L("通配"), 3]].map(([label, i]) => {
        const cards = ((p.policies || [])[i] || []).filter(h => (h >>> 0) !== 0xffffffff);
        return `<div class="policy-group policy-${i}" data-slot="${i}">` +
          `<div class="zone-title">${label}${L("卡槽 ")}${Number(slots[i]) || 0}</div>` +
          (cards.map(h => {
            const key = p.iPlayer + ":policy:" + hashStr(h), e = names[hashStr(h)] || {};
            return `<details class="policy-card" data-expand-key="${key}"${expanded[key] ? " open" : ""}>` +
              `<summary class="policy-toggle"><span class="chip policy-name">${escapeText(nameOf(h))}` +
              `${showType && e.type ? `<span class="en">${escapeText(e.type)}</span>` : ""}</span>` +
              `<span class="policy-income" aria-hidden="true"></span><span class="policy-caret" aria-hidden="true"></span></summary>` +
              `<div class="rule-description policy-description">${ruleTextHTML(e.description)}</div></details>`;
          }).join("") ||
            `${L("<span class=\"muted\">未挂政策卡</span>")}`) + `</div>`;
      }).join("") + `</div>`;
  }

  function jumpHUDLink(el, ev) {
    ev.preventDefault();
    ev.stopPropagation();
    const city = el.dataset.openCity;
    if (map) map.centerOnTile(Number(el.dataset.i), city == null);
    if (city != null) openCityPanel(Number(el.dataset.openP), Number(city));
  }

  // v0.26: 回到「一行一项」的 9 行 —— 城市 / 军力 / 粮食 / 产能 / 科技 / 文化 /
  // 金币 / 信仰 / 外交，每行一个独立展开箭头；「已研科技 / 市政 N/总数」是行内
  // 可点击展开项，不再是 hover 弹层。
  function majorCard(p, info, payload) {
    const card = document.createElement("div"); card.className = "civ-card";
    const col = cssColor(info.primary, 200);
    const team = Number(info.team);
    const leader = (info.leaderName || "");
    const sub = [leader, Number.isFinite(team) ? `${L("团队 ")}${team + 1}` : ""]
      .filter(Boolean).join(" · ");
    let html = `<div class="head"><span class="swatch" style="background:${col}"></span>
      <span class="name">${info.civName || ("P" + p.iPlayer)}</span>${typeTag(info.civStr)}
      <span class="sub">${sub}</span></div>`;
    html += civInfoHTML(p, info);

    const y = p.yields || {};
    const yv = (n) => Number(y[YIELD_BY_NAME[n]] || 0);
    const food = yv(L("食物")), prod = yv(L("产能")), sci = yv(L("科技")),
          cul = yv(L("文化")), faith = yv(L("信仰"));
    const gold = yv(L("金币")), maint = Number(p.maintenance) || 0;

    const cityDetail = ownedResourcesHTML(p, "luxuryResources", L("奢侈品资源"), false) + ((p.cities || []).map((c) => {
      const i = c.y * payload.width + c.x;
      return `<a href="#" class="city-link" data-i="${i}" data-open-p="${p.iPlayer}" data-open-city="${c.id}">${c.name}<span class="pop">${c.population}</span></a>`;
    }).join("") || L("<span class='muted'>无城市</span>"));
    // military units: icon + name + formation (★ wording) + 血条 / 晋升 / (坐标)
    const milUnits = (payload.units || [])
      .filter((u) => u.iPlayer === p.iPlayer && (u.cat || "mil") === "mil")
      .map((u) => ({ u: u, i: u.y * payload.width + u.x }))
      .sort((a, b) => cmpKey([nameOf(a.u.type), a.u.y, a.u.x],
                             [nameOf(b.u.type), b.u.y, b.u.x]));
    const milDetail = milUnits.length ? milUnits.map((e) => {
      const u = e.u;
      const ic = iconOf(u.type);
      const label = armyLabel(u.army, u.sea);
      return `<div class="mil-line" data-i="${e.i}">${ic ? `<img src="${ic}" alt="">` : ""}` +
        `<b>${nameHTML(u.type)}</b>` +
        (label ? `<span class="stars">${armyStars(u.army)}</span>${label}` : "") +
        `<span class="sub">${unitHealthHTML(u)}${unitPromotionHTML(u)}` +
        `${unitCoordText(u)}</span></div>`;
    }).join("") : L("<span class='muted'>无军事单位</span>");
    // v0.31: 核武器库存 —— 与游戏顶栏同一个口径，只列真正拥有的种类，图标取自
    // 图标字体图集（ICON_Nuclear / ICON_ThermoNuclear，见 vendor_wmd_icons.py）。
    // v0.33: 没有库存就**整块不写**；有库存时并成**一行**（最多两种：核装置 /
    // 热核装置，信息量小，分行只是白占版面）。
    const wmdItems = Object.entries(p.wmd || {})
      .map(([h, n]) => ({ hash: Number(h), n: Number(n) || 0 }))
      .filter((e) => e.n > 0)
      .sort((a, b) => b.n - a.n);
    const milWmd = wmdItems.length
      ? `${L("<div class=\"mil-line wmd-line\"><b class=\"wmd-title\">核武器</b>")}` +
        wmdItems.map((e) => {
          const ic = iconOf(e.hash);
          return `<span class="wmd-item">${ic ? `<img src="${ic}" alt="">` : ""}` +
            `${nameHTML(e.hash)}<span class="sub">×${e.n}</span></span>`;
        }).join("") + `</div>`
      : "";

    // per-city per-turn value, ranked descending (name breaks ties)
    const cityRank = (yieldName) => {
      const key = YIELD_BY_NAME[yieldName];
      const val = (c) => Number((c.yields || {})[key]) || 0;
      const list = (p.cities || []).slice().sort((a, b) =>
        (val(b) - val(a)) || cmpKey([a.name || ""], [b.name || ""]));
      if (!list.length) return L("<span class='muted'>无城市</span>");
      return list.map((c) => {
        const i = c.y * payload.width + c.x;
        return `<a href="#" class="city-link" data-i="${i}" data-open-p="${p.iPlayer}" data-open-city="${c.id}">${c.name}` +
          `<span class="pop">${fmtNum(val(c))}</span></a>`;
      }).join("");
    };

    // v0.40: 「当前研究 / 当前市政」的 chip 上，**已经拿到**尤里卡 / 鼓舞的再加一枚
    // 标记（``boosted`` = 存档 ``boost`` 表为真的那些哈希；两个 current 数组本身
    // 可以有多项 —— 游戏会把排队的下一项一起写进来）。
    const chips = (list, boosted, icon, label) => {
      const hits = new Set((boosted || []).map((h) => hashStr(h)));
      return (list || []).length
        ? list.map((h) => {
            const ic = iconOf(h);
            const mark = hits.has(hashStr(h))
              ? `<img class="boost" src="${icon}" alt="" title="${label}">`
              : "";
            return `<span class="chip">${ic ? `<img src="${ic}" alt="">` : ""}` +
              `${nameHTML(h)}${mark}</span>`;
          }).join("")
        : "<span class='muted'>—</span>";
    };

    const foodDetail = `${L("<div class=\"zone-title\">城市食物（每回合，降序）</div>")}${cityRank(L("食物"))}`;
    const prodDetail = `${L("<div class=\"zone-title\">城市产能（每回合，降序）</div>")}${cityRank(L("产能"))}`;
    // v0.26: 科技 / 文化 / 金币 / 信仰 各自一行；「已研 N / 总数」这一行本身可以
    // 点击展开成 chips（同一张卡共用一份 expanded 状态）。
    const sciDetail =
      `${L("<div class=\"zone-title\">当前研究</div>")}` +
      `${chips(p.currentTech, p.techBoosted, ICON_EUREKA, L("尤里卡已触发"))}` +
      researchedRowHTML(L("已研科技"), p.techResearched, p.techTotal, "tech", p.iPlayer) +
      `${L("<div class=\"zone-title\">城市科技（每回合，降序）</div>")}${cityRank(L("科技"))}`;
    // v0.40: 「文化」行整行正中间 = 旅游业绩 / 回合（与「外交」行的剩余使者同一个
    // 位置）；展开后第一行是文化胜利进度（国际游客 / 需要超过的对手国内游客）。
    const culDetail =
      cultureVictoryHTML(p) +
      `${L("<div class=\"zone-title\">当前市政</div>")}` +
      `${chips(p.currentCivic, p.civicBoosted, ICON_INSPIRATION, L("鼓舞已触发"))}` +
      governmentHTML(p) +
      researchedRowHTML(L("已研市政"), p.civicResearched, p.civicTotal, "civic", p.iPlayer) +
      `${L("<div class=\"zone-title\">城市文化（每回合，降序）</div>")}${cityRank(L("文化"))}`;
    const goldDetail =
      `${L("<div class=\"zone-title\">城市金币（每回合，降序）</div>")}${cityRank(L("金币"))}` +
      `${L("<div class=\"zone-title\">维护费 −")}${fmtNum(maint)}</div>` +
      ledgerHTML(p.iPlayer);
    const faithDetail =
      `${L("<div class=\"zone-title\">城市信仰（每回合，降序）</div>")}${cityRank(L("信仰"))}` +
      religionZoneHTML(p);

    // city states this civ is suzerain of (clickable when they still have cities)
    const suz = [];
    for (const q of (payload.players || [])) {
      const qinfo = playerInfo(q.iPlayer) || {};
      if ((qinfo.kind || "major") !== "city_state") continue;
      // v0.28.3: 观察者的使者按 0 计 —— 它不会成为宗主国
      if (suzerainOf(emissariesOf(q)) !== p.iPlayer) continue;
      suz.push({ iPlayer: q.iPlayer, name: qinfo.civName || ("P" + q.iPlayer),
                 city: (q.cities || [])[0] || null });
    }
    suz.sort((a, b) => cmpKey([a.name], [b.name]));
    const suzHtml = suz.length ? suz.map((s) => {
      if (!s.city) return `<div class="city-link muted">${s.name}</div>`;
      const i = s.city.y * payload.width + s.city.x;
      return `<a href="#" class="city-link" data-i="${i}" data-open-p="${s.iPlayer}" data-open-city="${s.city.id}">${s.name}` +
        `<span class="pop">${s.city.population}</span></a>`;
    }).join("") : L("<span class='muted'>无</span>");
    const diploDetail =
      `${L("<div class=\"zone-title\">宗主城邦</div>")}${suzHtml}` +
      `${L("<div class=\"zone-title\">外交胜利点数 ")}${Number(p.diploPoint) || 0} / ${DIPLO_VICTORY_MAX}</div>`;

    // v0.32: 剩余使者（未派出的使者 = 游戏顶栏外交票旁那个 [ICON_Envoy] N）。
    // 写在「外交」行的折叠状态里、整行水平居中（展开箭头之前），和其它行的
    // 展开箭头互不干扰。
    const envoyTokens = Number(p.envoyTokens) || 0;
    const envoyMid = `<img class="eicon" src="${ICON_ENVOY}${L("\" alt=\"使者\">")}` +
      `<span class="etok">${fmtNum(envoyTokens)}</span>`;
    // v0.40: 旅游业绩（每回合）—— 和上面那一行同一个位置（整行正中间）
    // 存档不存这个数（只存「对每个对手累积的旅游业绩」），所以标题里写清楚它是
    // 「相邻两份存档的差」反推出来的，并把逐文明的流量一并列出来（见 tourismTitle）。
    const tourismMid = `<img class="eicon" src="${ICON_TOURISM}${L("\" alt=\"旅游业绩\" ")}` +
      `title="${tourismTitle(p.iPlayer)}">` +
      `<span class="etok">${tourismText(p.iPlayer)}</span>`;

    const rows = [
      { key: "city", icon: ICON_CITY, value: p.cityCount, detail: cityDetail,
        mid: `<img class="eicon" src="${ICON_POPULATION}${L("\" alt=\"人口\" title=\"人口总数\">")}` +
          `${L("<span class=\"etok\" title=\"人口总数\">")}${(p.cities || []).reduce((sum, c) =>
            sum + (Number(c.population) || 0), 0)}</span>` },
      { key: "mil", icon: ICON_MIL, value: p.militaryStrength,
        detail: ownedResourcesHTML(p, "strategicResources", L("战略资源"), true) + milWmd + milDetail },
      { key: "food", icon: ICON_FOOD, value: fmtNum(food), detail: foodDetail },
      { key: "prod", icon: ICON_PROD, value: fmtNum(prod), detail: prodDetail },
      { key: "sci", icon: ICON_SCI, value: fmtNum(sci), detail: sciDetail },
      { key: "cul", icon: ICON_CUL, value: fmtNum(cul), detail: culDetail,
        mid: tourismMid },
      { key: "gold", icon: ICON_GOLD, value: stockHTML(p.gold, gold - maint),
        detail: goldDetail },
      { key: "faith", icon: ICON_FAITH, value: stockHTML(p.faith, faith),
        detail: faithDetail },
      { key: "diplo", icon: ICON_DIPLO, value: fmtNum(p.diploFavor),
        detail: diploDetail, mid: envoyMid },
    ];
    html += `<div class="hud-rows">`;
    for (const r of rows) {
      const open = !!expanded[p.iPlayer + ":" + r.key];
      html += `<div class="hud-row has-detail" data-row="${r.key}">` +
        `<span class="hcell"><img class="hicon" src="${r.icon}" alt="">` +
        `<span class="hval">${r.value}</span></span>` +
        (r.mid ? `<span class="hmid">${r.mid}</span>` : "") +
        `<span class="hcaret">${open ? "▾" : "▸"}</span></div>`;
      html += `<div class="hud-detail${open ? "" : " hidden"}" data-detail="${r.key}">${r.detail}</div>`;
    }
    html += `</div>`;
    card.innerHTML = html;

    wireLedger(card);
    wireRuleDetails(card);
    card.querySelectorAll(".hud-row.has-detail").forEach((el) => {
      el.onclick = () => {
        const key = el.dataset.row;
        const ek = p.iPlayer + ":" + key;
        expanded[ek] = !expanded[ek];
        const d = card.querySelector(`.hud-detail[data-detail="${key}"]`);
        if (d) d.classList.toggle("hidden", !expanded[ek]);
        const caret = el.querySelector(".hcaret");
        if (caret) caret.textContent = expanded[ek] ? "▾" : "▸";
      };
    });
    card.querySelectorAll(".steam-name[data-steamid]").forEach((el) => {
      const id = el.dataset.steamid;
      steamName(id).then((name) => { el.textContent = name; });
    });
    card.querySelectorAll(".city-link[data-i], .mil-line[data-i]").forEach((el) => {
      el.onclick = (e) => jumpHUDLink(el, e);
    });
    return card;
  }

  // v0.28.3 观察者卡片：只留「文明 / 玩家 id / SteamID / 社区名」——
  // 无颜色块、无领袖名、无团队、无时代与着力点，也没有 9 行对局数据
  // （观察者不参与游戏，产出与城市对它没有意义）。
  function spectatorCard(p, info) {
    const card = document.createElement("div");
    card.className = "civ-card spectator-card";
    let html = `<div class="head"><span class="name">` +
      `${info.civName || ("P" + p.iPlayer)}</span>${typeTag(info.civStr)}` +
      `${L("<span class=\"sub\">观察者</span></div>")}`;
    // 玩家 id：优先存档里的昵称，缺省退到槽位号
    const who = info.pseudo || ("P" + p.iPlayer);
    html += `<div class="civ-info spectator-info"><div class="civ-info-body">` +
      `${L("<div class=\"ci-line\"><span class=\"ci-key\">玩家 id</span>")}` +
      `<span class="ci-val">${who}</span></div>`;
    if (info.steamId) {
      html += `<div class="ci-line"><span class="ci-key">SteamID</span><span class="ci-val">` +
        `<a href="https://steamcommunity.com/profiles/${info.steamId}" target="_blank" ` +
        `rel="noopener">${info.steamId}</a></span></div>` +
        `${L("<div class=\"ci-line\"><span class=\"ci-key\">社区名</span>")}` +
        `<span class="ci-val steam-name" data-steamid="${info.steamId}">…</span></div>`;
    }
    html += `</div></div>`;
    card.innerHTML = html;
    card.querySelectorAll(".steam-name[data-steamid]").forEach((el) => {
      const id = el.dataset.steamid;
      steamName(id).then((name) => { el.textContent = name; });
    });
    return card;
  }

  // --- v0.28 金币流水账（右栏文明卡「金币」明细） ---------------------------
  // 三个指标：打钱总数（付出去）/ 吸钱总数（收进来）/ 净金币交易（两者之差）。
  // 数据来自 /api/gold —— 它读的是**游戏日志**（DiplomacyDeals.log /
  // GameCore.log / Player_Stats.csv），不是存档；指标沿用 elaphantguys_gold_script
  // 的复利 1.036/回合。窗口末回合跟随当前回合，范围有全期 / 近5t / 近10t /
  // 近30t 四档，两项偏好在 localStorage 里记忆。
  const LEDGER_STORE = "civ6replay.ledger";
  let LEDGER_RANGES;
  let ledgerRange = "all", ledgerWeighted = false;
  try {
    const saved = JSON.parse(localStorage.getItem(LEDGER_STORE) || "null") || {};
    // 翻译表在 init() 才建立，先用稳定的范围键恢复偏好。
    if (["all", "5", "10", "30"].includes(saved.range)) ledgerRange = saved.range;
    ledgerWeighted = !!saved.weighted;
  } catch (e) {
      if (e.name === "AbortError") return; /* 坏数据就用默认值 */ }
  let ledgerData = null, ledgerKey = "", ledgerSeq = 0;

  function saveLedgerPrefs() {
    try {
      localStorage.setItem(LEDGER_STORE,
        JSON.stringify({ range: ledgerRange, weighted: ledgerWeighted }));
    } catch (e) {
      if (e.name === "AbortError") return; /* 隐私模式写不进去，忽略 */ }
  }

  function ledgerHTML(ip) {
    const opts = LEDGER_RANGES.map(([v, label]) =>
      `<option value="${v}"${v === ledgerRange ? " selected" : ""}>${label}</option>`).join("");
    // 标题 / 控件 / 表都包在 .ledger 里：核不过（没日志 / 对不上 / 隔夜）时整块隐藏，
    // 只剩一行 .ledger-off-note 提示
    return `<div class="ledger" data-ip="${ip}">` +
      `${L("<div class=\"zone-title\">金币流水（打钱 / 吸钱 / 净金币交易）</div>")}` +
      `<div class="ledger-off-note muted"></div>` +
      `<div class="ledger-ctl">` +
      `<label><input type="checkbox" class="ledger-weight"` +
      `${ledgerWeighted ? " checked" : ""}${L("> 加权</label>")}` +
      `<select class="ledger-range">${opts}</select>` +
      `<span class="ledger-hint"></span></div>` +
      `<div class="ledger-body"><span class="muted">…</span></div></div>`;
  }

  function wireLedger(card) {
    card.querySelectorAll(".ledger").forEach((box) => {
      const w = box.querySelector(".ledger-weight");
      const r = box.querySelector(".ledger-range");
      if (w) w.onchange = () => {
        ledgerWeighted = w.checked; saveLedgerPrefs(); syncLedgerControls(); refreshLedgers();
      };
      if (r) r.onchange = () => {
        ledgerRange = r.value; saveLedgerPrefs(); syncLedgerControls(); refreshLedgers();
      };
    });
  }

  // 同一张指标表出现在每张卡的「金币」明细里，控件状态必须一起走
  function syncLedgerControls() {
    document.querySelectorAll(".ledger").forEach((box) => {
      const w = box.querySelector(".ledger-weight");
      const r = box.querySelector(".ledger-range");
      if (w) w.checked = ledgerWeighted;
      if (r) r.value = ledgerRange;
    });
  }

  async function refreshLedgers() {
    const bodies = [...document.querySelectorAll(".ledger-body")];
    if (!bodies.length) return;
    const end = currentTurn ? (Number(currentTurn.turn) || 0) : 0;
    const key = `${seed}|${ledgerRange}|${ledgerWeighted ? 1 : 0}|${end}`;
    if (ledgerData && key === ledgerKey) { paintLedgers(); return; }   // 同一份结果直接重画
    const seq = ++ledgerSeq;
    let data;
    try {
      // seed 传本局，服务端拿它去核对"日志是不是这一局"；日志目录只允许默认的那个
      data = await getJSON(`/api/gold?seed=${seed || 0}&range=${ledgerRange}`
        + `&weighted=${ledgerWeighted ? 1 : 0}` + (end ? `&end=${end}` : ""));
    } catch (e) {
      if (e.name === "AbortError") return;
      if (seq === ledgerSeq) {
        bodies.forEach((b) => { b.innerHTML = `${L("<span class=\"muted\">日志读取失败：")}${e.message}</span>`; });
      }
      return;
    }
    if (seq !== ledgerSeq) return;         // 期间又切了选项 / 回合，丢掉这次结果
    ledgerData = data; ledgerKey = key;
    paintLedgers();
  }

  function ledgerName(slot) {
    // 优先用复盘自己的文明名（中文），日志里的 ASCII 名只作兜底 —— 同一局的
    // 槽位编号与存档一致，所以能对上
    const info = playerInfo(slot);
    if (info && (info.civName || info.civStr)) return `[${slot}] ${info.civName || info.civStr}`;
    const h = ((ledgerData && ledgerData.humans) || []).find((x) => x.slot === slot);
    return h ? `[${slot}] ${h.name}` : `[${slot}] ?`;
  }

  // 原程序算得出「逐对手流向」却从不显示，这里补上 —— 解决"被谁喂的"
  function ledgerPairsHTML(ip) {
    const pairs = (ledgerData.pairs || []).filter((p) => p.from === ip || p.to === ip);
    if (!pairs.length) return "";
    pairs.sort((a, b) => b.amount - a.amount);
    const lines = pairs.slice(0, 4).map((p) => {
      const gave = p.from === ip;
      const other = gave ? p.to : p.from;
      return `<div class="${gave ? "pos" : "neg"}">` +
        `${gave ? L("给出") : L("收到")} ${fmtNum(p.amount)} ` +
        `${gave ? "→" : "←"} ${ledgerName(other)}` +
        `<span class="muted">（${p.periods}${L(" 期）</span></div>")}`;
    }).join("");
    return `${L("<div class=\"ledger-pairs\">逐对手：")}${lines}</div>`;
  }

  function paintLedgers() {
    if (!ledgerData) return;
    const wraps = [...document.querySelectorAll(".ledger")];
    if (!ledgerData.ok) {
      // 核不过就整块隐藏（标题 / 开关 / 表都不显示），只留这一行
      const tip = `${L("只能在本局游戏刚跑完时查看金币流水（")}${ledgerData.reason || L("没有日志")}）`;
      const where = [ledgerData.logDir, ...(ledgerData.tried || []).slice(0, 3)]
        .filter(Boolean).join("\n");
      wraps.forEach((w) => {
        w.classList.add("ledger-off");
        const note = w.querySelector(".ledger-off-note");
        if (note) { note.textContent = tip; note.title = where; }
        const body = w.querySelector(".ledger-body");
        if (body) body.innerHTML = "";        // 别把上一次的表留在 DOM 里
      });
      return;
    }
    wraps.forEach((w) => w.classList.remove("ledger-off"));
    const bodies = wraps.map((w) => w.querySelector(".ledger-body")).filter(Boolean);
    const rows = ledgerData.players || [];
    const rowHTML = (r, ip) => {
      const cls = r.net > 0 ? "pos" : (r.net < 0 ? "neg" : "");
      return `<tr${r.slot === ip ? ' class="me"' : ""}><td>${ledgerName(r.slot)}</td>` +
        `<td>${fmtNum(r.sent)}</td><td>${fmtNum(r.received)}</td>` +
        `<td class="${cls}">${r.net > 0 ? "+" : ""}${fmtNum(r.net)}</td></tr>`;
    };
    const head = `${L("<tr><th>玩家</th><th>打钱</th><th>吸钱</th><th>净</th></tr>")}`;
    const win = ledgerData.range === "all"
      ? `${L("第 1t–第 ")}${ledgerData.endTurn}t`
      : `${L("第 ")}${ledgerData.startTurn}${L("t–第 ")}${ledgerData.endTurn}t`;
    const note = `${L("窗口 ")}${win}${L(" · 日志第 ")}${ledgerData.logTurn}t · ${ledgerData.payments}${L(" 期")}` +
      (ledgerData.weighted ? L(" · 已加权") : "") +
      (ledgerData.endClamped ? `${L(" · 日志只到第 ")}${ledgerData.logTurn}t` : "");
    for (const b of bodies) {
      const wrap = b.closest(".ledger");
      const ip = Number(wrap ? wrap.dataset.ip : NaN);
      b.innerHTML = `<table class="ledger-t">${head}` +
        rows.map((r) => rowHTML(r, ip)).join("") + `</table>` +
        ledgerPairsHTML(ip) + `<div class="ledger-foot">${note}</div>`;
    }
  }

  // --- v0.26.1 对比页 ------------------------------------------------------
  // 横排所有玩家（一列一位），每行一项数据；表头可拖动排序（记忆在
  // ``civ6replay.civOrder``），点数据行展开该行的详细列，
  // 同一行的格子由 CSS grid 的行高自动对齐（短的对齐长的），便于横向比对。
  let CIV_ROW_LABELS;
  const CMP_LABEL_W = 80, CMP_COMPACT_W = 80;
  const cmpCompact = readCmpCompact();
  let cmpExpanded = {};
  let cmpOrder = [];        // 当前对比页的列顺序（iPlayer）
  let cmpRowKeys = [];      // 当前对比页的行顺序（row key）
  let civOrder = readCivOrder();
  let cmpRowOrder = readCmpRowOrder();

  function compactHUDRowHTML(key, value, icon) {
    return `<div class="hud-row" data-row="${key}">` +
      `<img class="hicon" src="${icon}" alt="${CIV_ROW_LABELS[key]}" title="${CIV_ROW_LABELS[key]}">` +
      `<span class="hval">${value}</span></div>`;
  }

  function renderCompactHUD(payload, majors) {
    const box = $("civ-hud");
    if (!majors.length) {
      const empty = document.createElement("div");
      empty.className = "loading"; empty.textContent = L("本回合无可显示的文明");
      box.appendChild(empty);
      return;
    }
    // Read the same primary values as the full HUD, then discard every detail
    // and interaction. Spectators keep their identity and have no game values.
    const cards = majors.map(m => isSpectator(m.info) ? null : majorCard(m.p, m.info, payload));
    const grid = document.createElement("div");
    grid.className = "cmp-grid mini-grid";
    grid.dataset.columns = String(majors.length);
    grid.style.gridTemplateColumns = `repeat(${majors.length}, ${CMP_COMPACT_W}px)`;
    const add = (className, col, row) => {
      const el = document.createElement("div"); el.className = className;
      el.style.gridColumn = String(col); el.style.gridRow = String(row);
      grid.appendChild(el); return el;
    };
    majors.forEach((m, c) => {
      const head = add("cmp-head compact", c + 1, 1);
      head.dataset.ip = String(m.p.iPlayer);
      head.title = [m.info.civName, m.info.leaderName, isSpectator(m.info) ? L("观察者") : ""].filter(Boolean).join(" · ");
      const portrait = iconOf(m.info.leader);
      head.innerHTML = `<span class="hrow">` +
        (portrait ? `<img class="cmp-portrait" src="${portrait}" alt="${m.info.leaderName || L("领袖头像")}">` : "") + `</span>`;
    });
    const icons = [ICON_CITY, ICON_MIL, ICON_FOOD, ICON_PROD, ICON_SCI, ICON_CUL, ICON_GOLD, ICON_FAITH, ICON_DIPLO];
    Object.keys(CIV_ROW_LABELS).forEach((key, ri) => {
      majors.forEach((m, c) => {
        const valueRow = cards[c]?.querySelector(`.hud-rows > .hud-row[data-row="${key}"]`);
        const value = !valueRow ? "—" : key === "gold" || key === "faith" ? cmpStockHTML(m.p, key)
          : valueRow.querySelector(".hval").innerHTML;
        const cell = add("cmp-cell compact", c + 1, ri + 2);
        cell.dataset.ip = String(m.p.iPlayer); cell.dataset.row = key;
        cell.innerHTML = compactHUDRowHTML(key, value, icons[ri]);
      });
    });
    const scroll = document.createElement("div"); scroll.className = "cmp-scroll";
    scroll.appendChild(grid); box.appendChild(scroll);
  }

  function readCmpCompact() {
    try {
      const saved = JSON.parse(localStorage.getItem("civ6replay.cmpCompact.v1") || "{}");
      return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
    } catch (e) {
      if (e.name === "AbortError") return; return {}; }
  }

  function isCmpCompact(ip) {
    return Array.isArray(cmpCompact[seed]) && cmpCompact[seed].includes(ip);
  }

  function compareColumns(order) {
    const labelWidth = window.Civ6I18n.language === "en" ? 148 : CMP_LABEL_W;
    return [labelWidth + "px"].concat(order.map(ip =>
      isCmpCompact(ip) ? CMP_COMPACT_W + "px" : "minmax(0, 1fr)")).join(" ");
  }

  function toggleCmpColumn(ip) {
    const compact = new Set(Array.isArray(cmpCompact[seed]) ? cmpCompact[seed] : []);
    if (compact.has(ip)) compact.delete(ip); else compact.add(ip);
    cmpCompact[seed] = [...compact];
    try { localStorage.setItem("civ6replay.cmpCompact.v1", JSON.stringify(cmpCompact)); }
    catch (e) {
      if (e.name === "AbortError") return; /* keep the preference for this page */ }
    const scroll = $("civ-hud").querySelector(".cmp-scroll");
    const x = scroll?.scrollLeft || 0, y = scroll?.scrollTop || 0;
    if (currentTurn) renderHUD(currentTurn);
    const next = $("civ-hud").querySelector(".cmp-scroll");
    if (next) { next.scrollLeft = x; next.scrollTop = y; }
  }

  function cmpStockHTML(p, key) {
    const gold = key === "gold";
    const stock = Number(gold ? p.gold : p.faith) || 0;
    const rate = (Number((p.yields || {})[YIELD_BY_NAME[gold ? L("金币") : L("信仰")]]) || 0) -
      (gold ? Number(p.maintenance) || 0 : 0);
    return `${L("<span class=\"cmp-stock\" title=\"库存 / 每回合")}${gold ? L("净收入") : L("产出")}">` +
      `<span class="${stock < 0 ? "neg" : ""}">${fmtNum(stock)}</span>` +
      `<span class="pct${rate < 0 ? " neg" : ""}">(${rate >= 0 ? "+" : ""}${fmtNum(rate)})</span></span>`;
  }

  // v0.27: 数据行的顺序也可以调（关心什么就往上挪），记忆在
  // ``civ6replay.cmpRowOrder``；没记过的行按「城市 / 军力 / 粮食 …」原顺序跟上。
  function readCmpRowOrder() {
    try {
      const raw = JSON.parse(localStorage.getItem("civ6replay.cmpRowOrder") || "[]");
      return Array.isArray(raw) ? raw.filter((v) => typeof v === "string") : [];
    } catch (e) {
      if (e.name === "AbortError") return; return []; }
  }

  function saveCmpRowOrder() {
    try { localStorage.setItem("civ6replay.cmpRowOrder", JSON.stringify(cmpRowOrder)); }
    catch (e) {
      if (e.name === "AbortError") return; /* storage may be unavailable */ }
  }

  function orderRows(natural, saved) {
    const out = saved.filter((k) => natural.indexOf(k) >= 0);
    for (const k of natural) if (out.indexOf(k) < 0) out.push(k);
    return out;
  }

  function readCivOrder() {
    try {
      const raw = JSON.parse(localStorage.getItem("civ6replay.civOrder") || "[]");
      return Array.isArray(raw) ? raw.filter((v) => typeof v === "number") : [];
    } catch (e) {
      if (e.name === "AbortError") return; return []; }
  }

  function saveCivOrder() {
    try { localStorage.setItem("civ6replay.civOrder", JSON.stringify(civOrder)); }
    catch (e) {
      if (e.name === "AbortError") return; /* storage may be unavailable */ }
  }

  // 拖拽过的顺序优先，其余按 payload 顺序（＝楼层）
  function orderedMajors(majors, payload) {
    const rank = new Map(), floor = new Map();
    civOrder.forEach((ip, i) => rank.set(ip, i));
    (payload.players || []).forEach((p, i) => floor.set(p.iPlayer, i));
    const keyOf = (m) => (rank.has(m.p.iPlayer)
      ? rank.get(m.p.iPlayer) : 1000 + (floor.get(m.p.iPlayer) || 0));
    return majors.slice().sort((a, b) => keyOf(a) - keyOf(b));
  }

  function renderCompare(payload, majors) {
    const box = $("civ-hud");
    box.innerHTML = "";
    const list = orderedMajors(majors, payload);
    if (!list.length) {
      const empty = document.createElement("div");
      empty.className = "loading";
      empty.textContent = L("本回合无可对比的文明");
      box.appendChild(empty);
      return;
    }
    cmpOrder = list.map((m) => m.p.iPlayer);
    // Data-specific guidance stays with the comparison grid.
    const tools = document.createElement("div");
    tools.className = "cmp-tools";
    tools.innerHTML =
      `${L("<span class=\"cmp-hint\">点击领袖格：收缩 / 恢复该列；点击数据行：展开 / 收起详细列。上下拖行、左右拖列，松开前预览，Esc 取消；布局会记住。</span>")}` +
      `${L("<span class=\"cmp-note\">窄列显示图标与基本数值；金币、信仰分两行：库存 / 每回合变化。</span>")}`;
    box.appendChild(tools);
    // 每位玩家一张隐藏卡片（复用文明页的 9 行渲染），再按行拆进网格
    const cards = list.map((m) => ({ m: m, card: majorCard(m.p, m.info, payload) }));
    const rowKeys = orderRows(
      [...cards[0].card.querySelectorAll(".hud-rows > .hud-row")].map((r) => r.dataset.row),
      cmpRowOrder);
    cmpRowKeys = rowKeys;
    const grid = document.createElement("div");
    grid.className = "cmp-grid";
    grid.style.gridTemplateColumns = compareColumns(cmpOrder);
    grid.innerHTML =
      `${L("<div class=\"cmp-label cmp-corner\" style=\"grid-column:1;grid-row:1\">文明 / 数据</div>")}`;
    list.forEach((m, c) => {
      const col = c + 2;
      const team = Number(m.info.team);
      const civCol = cssColor(m.info.primary, 220);
      const portrait = iconOf(m.info.leader);
      const compact = isCmpCompact(m.p.iPlayer);
      grid.innerHTML +=
        `<div class="cmp-head${compact ? " compact" : ""}" data-ip="${m.p.iPlayer}" style="grid-column:${col};grid-row:1" ` +
        `role="button" tabindex="0" aria-expanded="${!compact}" ` +
        `${L("title=\"点击")}${compact ? L("恢复该列详情") : L("收缩该列，显示图标与基本数值")}${L("；左右拖动调整文明顺序\">")}` +
        `<span class="hrow">` +
        (portrait ? (compact
          ? `<img class="cmp-portrait" src="${portrait}" alt="">`
          : leaderPortraitHTML(m.info, m.p.iPlayer, portrait, "cmp")) : "") +
        `<span class="n" style="color:${civCol}">${m.info.civName || ("P" + m.p.iPlayer)}</span>` +
        `</span>` +
        `<span class="t">${[m.info.leaderName || "", Number.isFinite(team) ? `${L("团队 ")}${team + 1}` : ""]
          .filter(Boolean).join(" · ")}</span>` +
        `<span class="hint">${compact ? L("点击恢复详情") : L("点击收缩数据")}</span>` +
        (compact ? "" : leaderSkillsHTML(m.info, m.p.iPlayer, "cmp")) + `</div>`;
    });
    rowKeys.forEach((key, ri) => {
      const row = ri + 2;
      const first = cards[0].card.querySelector(`.hud-row[data-row="${key}"]`);
      const icon = first && first.querySelector("img.hicon");
      grid.innerHTML +=
        `<div class="cmp-label" data-row="${key}${L("\" title=\"上下拖动调整顺序；点击展开 / 收起详细列（窄列保持基本数值）\" style=\"grid-column:1;grid-row:")}${row}">` +
        (icon ? `<img src="${icon.getAttribute("src")}" alt="">` : "") +
        `<span>${CIV_ROW_LABELS[key] || key}</span>` +
        `<span class="caret">${cmpExpanded[key] ? "▾" : "▸"}</span></div>`;
      cards.forEach((entry, c) => {
        const compact = isCmpCompact(entry.m.p.iPlayer);
        const cell = document.createElement("div");
        cell.className = "cmp-cell" + (compact ? " compact" : cmpExpanded[key] ? " open" : "");
        cell.dataset.row = key;
        cell.dataset.ip = String(entry.m.p.iPlayer);
        cell.style.gridColumn = String(c + 2);
        cell.style.gridRow = String(row);
        const valueRow = entry.card.querySelector(`.hud-row[data-row="${key}"]`);
        const detail = entry.card.querySelector(`.hud-detail[data-detail="${key}"]`);
        if (compact && valueRow) {
          const value = key === "gold" || key === "faith" ? cmpStockHTML(entry.m.p, key) :
            valueRow.querySelector(".hval").innerHTML;
          cell.innerHTML = compactHUDRowHTML(key, value, valueRow.querySelector(".hicon").getAttribute("src"));
        } else if (valueRow) cell.appendChild(valueRow);
        if (detail && !compact) {
          detail.classList.toggle("hidden", !cmpExpanded[key]);
          cell.appendChild(detail);
        }
        grid.appendChild(cell);
      });
    });
    const scroll = document.createElement("div");
    scroll.className = "cmp-scroll";
    scroll.appendChild(grid);
    box.appendChild(scroll);
    wireCompare(grid);
  }

  function toggleCmpBand(key) {
    const on = !cmpExpanded[key];
    cmpExpanded[key] = on;
    document.querySelectorAll(`.cmp-cell[data-row="${key}"]`).forEach((cell) => {
      if (cell.classList.contains("compact")) return;
      cell.classList.toggle("open", on);
      const detail = cell.querySelector(`:scope > .hud-detail[data-detail="${key}"]`);
      if (detail) detail.classList.toggle("hidden", !on);
      const caret = cell.querySelector(".hud-row .hcaret");
      if (caret) caret.textContent = on ? "▾" : "▸";
    });
    document.querySelectorAll(`.cmp-label[data-row="${key}"] .caret`).forEach((el) => {
      el.textContent = on ? "▾" : "▸";
    });
  }

  function moveCivTo(fromIp, toIp) {
    const from = cmpOrder.indexOf(fromIp), to = cmpOrder.indexOf(toIp);
    if (from < 0 || to < 0 || from === to) return;
    cmpOrder.splice(from, 1);
    cmpOrder.splice(to, 0, fromIp);
    civOrder = cmpOrder.slice();
    saveCivOrder();
    if (currentTurn) renderHUD(currentTurn);     // 重建对比页
  }

  // 拖动数据行后保存顺序（刷新 / 重开都保持）。
  function moveCmpRow(key, delta) {
    const keys = cmpRowKeys.slice();
    const from = keys.indexOf(key), to = from + delta;
    if (from < 0 || to < 0 || to >= keys.length) return;
    keys.splice(from, 1);
    keys.splice(to, 0, key);
    cmpRowOrder = keys;
    saveCmpRowOrder();
    if (currentTurn) renderHUD(currentTurn);     // 重建对比页
  }

  function wireCompare(grid) {
    wireRuleDetails(grid);
    // 收缩列只保留数值；详细列的同一数据行一起展开 / 收起。
    grid.querySelectorAll(".cmp-cell").forEach((cell) => {
      cell.querySelector(".hud-row").onclick = () => {
        if (!cell.classList.contains("compact")) toggleCmpBand(cell.dataset.row);
      };
    });
    grid.querySelectorAll(".cmp-label[data-row]").forEach((label) => {
      label.onclick = () => toggleCmpBand(label.dataset.row);
    });
    grid.querySelectorAll(".cmp-head").forEach(head => {
      head.onclick = () => toggleCmpColumn(Number(head.dataset.ip));
      head.onkeydown = ev => {
        if (ev.target !== head) return;
        if (ev.key !== "Enter" && ev.key !== " ") return;
        ev.preventDefault();
        toggleCmpColumn(Number(head.dataset.ip));
        $("civ-hud").querySelector(`.cmp-head[data-ip="${head.dataset.ip}"]`)?.focus();
      };
    });
    // 详情里的折叠项（已研科技 / 已研市政）在自己那格里展开
    grid.querySelectorAll(".cmp-cell .hud-detail .hud-row.has-detail").forEach((row) => {
      row.onclick = (ev) => {
        ev.stopPropagation();
        const box = row.parentElement;
        const detail = box && box.querySelector(`.hud-detail[data-detail="${row.dataset.row}"]`);
        if (!detail) return;
        const open = detail.classList.contains("hidden");
        detail.classList.toggle("hidden", !open);
        const caret = row.querySelector(".hcaret");
        if (caret) caret.textContent = open ? "▾" : "▸";
      };
    });
    // 城市 / 单位链接跳转（与文明页同一套）
    grid.querySelectorAll(".city-link[data-i], .mil-line[data-i]").forEach((el) => {
      el.onclick = (ev) => jumpHUDLink(el, ev);
    });
    // Move the complete band in the live grid without rebuilding its detail
    // nodes. Hit regions remain at their original positions to avoid jitter.
    const bindDrag = (handle, axis, key) => {
      let suppressClick = false;
      handle.addEventListener("click", e => {
        if (!suppressClick) return;
        e.preventDefault(); e.stopImmediatePropagation();
      }, true);
      handle.addEventListener("pointerdown", ev => {
        if (ev.button !== 0 || ev.target.closest("button")) return;
        suppressClick = false;
        const horizontal = axis === "column";
        const original = (horizontal ? cmpOrder : cmpRowKeys).slice();
        const from = original.indexOf(key);
        const anchors = original.map(value => grid.querySelector(horizontal
          ? `.cmp-head[data-ip="${value}"]` : `.cmp-label[data-row="${value}"]`));
        const scroller = grid.parentElement;
        const startScroll = horizontal ? scroller.scrollLeft : scroller.scrollTop;
        const centers = anchors.map(el => {
          const r = el.getBoundingClientRect();
          return horizontal ? r.left + r.width / 2 : r.top + r.height / 2;
        });
        const start = horizontal ? ev.clientX : ev.clientY;
        let pointer = start, moved = false, target = from, frame = null, done = false;
        const band = [...grid.children].filter(el => horizontal
          ? Number(el.dataset.ip) === key : el.dataset.row === key);
        const layout = order => {
          if (horizontal) grid.style.gridTemplateColumns = compareColumns(order);
          const ranks = new Map(order.map((value, i) => [String(value), i + 2]));
          for (const el of grid.children) {
            const value = horizontal ? el.dataset.ip : el.dataset.row;
            if (!ranks.has(value)) continue;
            if (horizontal) el.style.gridColumn = ranks.get(value);
            else el.style.gridRow = ranks.get(value);
          }
        };
        const preview = () => {
          const scroll = horizontal ? scroller.scrollLeft : scroller.scrollTop;
          const coord = pointer + scroll - startScroll;
          target = centers.reduce((best, center, i) =>
            Math.abs(center - coord) < Math.abs(centers[best] - coord) ? i : best, 0);
          const order = original.slice();
          order.splice(from, 1); order.splice(target, 0, key);
          layout(order);
          grid.dataset.previewAxis = axis;
        };
        const tick = () => {
          if (!grid.isConnected) { finish(false); return; }
          const r = scroller.getBoundingClientRect();
          const near = horizontal ? r.left : r.top, far = horizontal ? r.right : r.bottom;
          const delta = pointer < near + 28 ? -12 : pointer > far - 28 ? 12 : 0;
          if (horizontal) scroller.scrollLeft += delta;
          else scroller.scrollTop += delta;
          preview();
          frame = requestAnimationFrame(tick);
        };
        const move = e => {
          pointer = horizontal ? e.clientX : e.clientY;
          if (!moved && Math.abs(pointer - start) < 5) return;
          if (!moved) {
            moved = true; suppressClick = true;
            band.forEach(el => el.classList.add("cmp-preview"));
            document.body.classList.add("panel-dragging");
            frame = requestAnimationFrame(tick);
          }
          preview();
        };
        const finish = commit => {
          if (done) return;
          done = true;
          cancelAnimationFrame(frame);
          handle.removeEventListener("pointermove", move);
          handle.removeEventListener("pointerup", up);
          handle.removeEventListener("pointercancel", cancel);
          handle.removeEventListener("lostpointercapture", cancel);
          document.removeEventListener("keydown", escape);
          if (handle.hasPointerCapture(ev.pointerId)) handle.releasePointerCapture(ev.pointerId);
          band.forEach(el => el.classList.remove("cmp-preview"));
          document.body.classList.remove("panel-dragging");
          delete grid.dataset.previewAxis;
          if (moved && commit && target !== from) {
            const x = scroller.scrollLeft, y = scroller.scrollTop;
            if (horizontal) moveCivTo(key, original[target]);
            else moveCmpRow(key, target - from);
            const next = $("civ-hud").querySelector(".cmp-scroll");
            if (next) { next.scrollLeft = x; next.scrollTop = y; }
          } else layout(original);
        };
        const up = () => finish(true), cancel = () => finish(false);
        const escape = e => { if (e.key === "Escape") { e.preventDefault(); finish(false); } };
        handle.setPointerCapture(ev.pointerId);
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", up);
        handle.addEventListener("pointercancel", cancel);
        handle.addEventListener("lostpointercapture", cancel);
        document.addEventListener("keydown", escape);
        ev.preventDefault();
      });
    };
    grid.querySelectorAll(".cmp-head").forEach(head => bindDrag(head, "column", Number(head.dataset.ip)));
    grid.querySelectorAll(".cmp-label[data-row], .cmp-cell > .hud-row").forEach(handle =>
      bindDrag(handle, "row", handle.dataset.row));
  }

  // 城邦页：主色块 + 中文城邦名 + 类型环；城市行与头部可跳转。
  function cityStateCard(p, info) {
    const card = document.createElement("div"); card.className = "civ-card cs-card";
    // v0.26.1: 去掉颜色方框，改用带色的文明名（城邦主色是黑色，取更亮的那个）
    const col = cityStateTint(info);
    const sec = cssColor(info.secondary, 240);
    const dead = p.cityCount === 0;
    // v0.24: the city-state's own city / population is irrelevant here, so the
    // card only carries the head (也作为跳转入口) plus the envoy rows.
    const c0 = (p.cities || [])[0];
    let html = `<div class="head${dead ? "" : " clickable"}" data-jump="1">` +
      `<span class="name tinted" style="color:${col}">${info.civName || ("P" + p.iPlayer)}</span>` +
      `${typeTag(info.civStr)}` +
      (dead ? `${L("<span class=\"dead\">已灭亡</span>")}` : "") +
      `<span class="sub cs-flavour" style="color:${sec}"><span class="ring"></span>${info.flavour || "—"}</span></div>`;
    // v0.28.3: 观察者的使者按 0 计 —— 不画它的行 / 进度条
    const em = emissariesOf(p);
    const entries = Object.keys(em).map((k) => [parseInt(k, 10), em[k]]).sort((a, b) => b[1] - a[1]);
    if (!entries.length) {
      html += `${L("<div class=\"emissaries\"><div class=\"no-emissary\">无使者</div></div>")}`;
    } else {
      // v0.23: flag the suzerain (unique highest envoy count >= 3)
      const suz = suzerainOf(em);
      const max = entries[0][1] || 1;
      html += `<div class="emissaries">`;
      for (const [ip, cnt] of entries) {
        const pinfo = playerInfo(ip) || {};
        const pc = cssColor(pinfo.primary, 160);
        const pct = Math.min(100, (cnt / max) * 100);
        const mark = ip === suz ? `${L("<span class=\"suz\">（宗主国）</span>")}` : "";
        // v0.33: 文明名回到默认文字色 —— 深色面板上，主色里的深蓝 / 紫
        // （美国、罗马…）几乎看不见；颜色只留给进度条。
        html += `<div class="emissary">
          <span class="who">${playerName(ip)}${typeTag(pinfo.civStr)}${mark}</span>
          <span class="bar"><i style="width:${pct}%;background:${pc}"></i></span>
          <span class="val">${cnt}<img class="eicon" src="${ICON_ENVOY}" alt=""></span></div>`;
      }
      html += `</div>`;
    }
    card.innerHTML = html;
    if (c0 && !dead) {
      const jump = () => map.centerOnTile(c0.y * currentTurn.width + c0.x);
      const h = card.querySelector(".head.clickable");
      if (h) h.onclick = jump;
    }
    return card;
  }

  // 城邦主色是黑色，直接用会看不见 —— 取主 / 副色里更亮的那个
  function cityStateTint(info) {
    const prim = info && info.primary, sec = info && info.secondary;
    if (!prim) return cssColor(sec, 220);
    if (!sec) return cssColor(prim, 220);
    const lum = (c) => 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2];
    return cssColor(lum(prim) >= lum(sec) ? prim : sec, 230);
  }

  function cssColor(arr, def) {
    if (!arr) return `rgb(${def},${def},${def})`;
    return `rgb(${(arr[0]*255)|0},${(arr[1]*255)|0},${(arr[2]*255)|0})`;
  }

  // --- v0.26 navigation bar (was the minimap) ------------------------------
  // The whole map is painted once per turn into an offscreen image; every
  // ``view`` event only blits it and draws the visible-world rectangle (bright,
  // with a light frame) plus the dimming outside of it, so following a pan /
  // zoom costs one small composite instead of re-rasterising the map.
  let navImage = null, navMeta = null, navView = null;
  const NAV_W = 460;                        // offscreen resolution (px)

  function buildNav(payload) {
    const w = payload.width, h = payload.height;
    const worldW = w + 0.5, worldH = (h - 1) * HEX_R * 1.5 + 2 * HEX_R;
    const navH = Math.max(24, Math.round(NAV_W * worldH / worldW));
    // ``pxW``/``pxH`` are the *canvas* resolution: every world <-> nav mapping
    // uses those, never the element's CSS size (the canvas is a fixed-size
    // bitmap that CSS only scales).
    navMeta = { worldW: worldW, worldH: worldH, width: w, height: h,
                pxW: NAV_W, pxH: navH };
    const cv = document.createElement("canvas");
    cv.width = NAV_W; cv.height = navH;
    const ctx = cv.getContext("2d");
    ctx.fillStyle = "#0b0e13"; ctx.fillRect(0, 0, NAV_W, navH);
    const sx = NAV_W / worldW, sy = navH / worldH;
    const cw = Math.max(1, Math.ceil(sx)), ch = Math.max(1, Math.ceil(sy * HEX_R * 1.5));
    for (let i = 0; i < payload.tiles.terrain.length; i++) {
      const x = i % w, y = (i / w) | 0;
      const info = names[hashStr(payload.tiles.terrain[i])];
      ctx.fillStyle = HexMap.terrainColor(info && info.type);
      const x0 = (y % 2 ? x + 0.5 : x) * sx;
      const y0 = (worldH - (y * HEX_R * 1.5 + HEX_R)) * sy;
      ctx.fillRect(x0 - cw / 2, y0 - ch / 2, cw, ch);
    }
    navImage = cv;
    const el = $("nav");
    el.width = NAV_W; el.height = navH;
    renderNav();
  }

  // nav *canvas* pixel -> world coordinates (click-jump / drag-pan / hit test)
  function navToWorld(px, py) {
    if (!navMeta) return null;
    return { wx: px / navMeta.pxW * navMeta.worldW,
             wy: py / navMeta.pxH * navMeta.worldH };
  }

  function renderNav() {
    const el = $("nav");
    if (!el || !navImage || !navMeta || !map) return;
    const ctx = el.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, el.width, el.height);
    ctx.drawImage(navImage, 0, 0);
    const v = map.viewRect();
    const sx = el.width / navMeta.worldW, sy = el.height / navMeta.worldH;
    const x0 = Math.max(0, v.x0 * sx), x1 = Math.min(el.width, v.x1 * sx);
    const y0 = Math.max(0, v.y0 * sy), y1 = Math.min(el.height, v.y1 * sy);
    const bw = Math.max(1, x1 - x0), bh = Math.max(1, y1 - y0);
    // dim everything outside the visible rectangle, then frame the rectangle
    ctx.fillStyle = "rgba(5,8,12,.55)";
    ctx.fillRect(0, 0, el.width, y0);
    ctx.fillRect(0, y1, el.width, Math.max(0, el.height - y1));
    ctx.fillRect(0, y0, x0, bh);
    ctx.fillRect(x1, y0, Math.max(0, el.width - x1), bh);
    ctx.strokeStyle = "rgba(255,255,255,.92)";
    ctx.lineWidth = Math.max(1, el.width / 220);
    ctx.strokeRect(x0, y0, bw, bh);
    navView = { x0: x0, y0: y0, x1: x1, y1: y1 };
  }

  function wireNav() {
    const el = $("nav");
    let dragging = false, start = null, camStart = null;
    el.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0 || !navMeta || !map.payload) return;
      const r = el.getBoundingClientRect();
      const px = (ev.clientX - r.left) / r.width * el.width;
      const py = (ev.clientY - r.top) / r.height * el.height;
      if (navView && px >= navView.x0 && px <= navView.x1
                   && py >= navView.y0 && py <= navView.y1) {
        // inside the box: pan the map along with the pointer
        const wpt = navToWorld(px, py);
        dragging = true; start = wpt;
        camStart = { x: map.camX, y: map.camY };
        try { el.setPointerCapture(ev.pointerId); } catch (e) {
      if (e.name === "AbortError") return; /* optional */ }
        el.style.cursor = "grabbing";
      } else {
        // outside: jump so that point ends up in the middle of the map
        const wpt = navToWorld(px, py);
        map.lookAt(wpt.wx, wpt.wy);
      }
      ev.preventDefault();
    });
    el.addEventListener("pointermove", (ev) => {
      if (!dragging || !start) return;
      const r = el.getBoundingClientRect();
      const px = (ev.clientX - r.left) / r.width * el.width;
      const py = (ev.clientY - r.top) / r.height * el.height;
      const wpt = navToWorld(px, py);
      // v0.27: the box follows the pointer - the camera centre moves *with* the
      // drag (v0.26 moved it the other way, so the view ran away from the cursor)
      map.lookAt(camStart.x + (wpt.wx - start.wx), camStart.y + (wpt.wy - start.wy));
    });
    const stop = () => { dragging = false; start = null; el.style.cursor = "grab"; };
    el.addEventListener("pointerup", stop);
    el.addEventListener("pointercancel", stop);
  }

  function step(d) {
    const idx = nearestLoadedIndex(currentIndex() + d);
    if (idx != null) loadTurn(idx);
  }
  function currentIndex() { return parseInt($("turn-slider").value, 10) || 0; }

  function onKeyDown(e) {
    const tag = e.target && e.target.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (e.key === "ArrowLeft") { step(e.shiftKey ? -10 : -1); e.preventDefault(); }
    else if (e.key === "ArrowRight") { step(e.shiftKey ? 10 : 1); e.preventDefault(); }
  }
  // --- v0.25 (文档 C4) left-sidebar search ---------------------------------
  // The current turn is indexed client-side: one text blob per tile built from
  // the resolved Chinese names of everything on it (terrain / feature / resource
  // / improvement / district type / wonder / units / city / owner civ / continent).
  const SEARCH_LIMIT = 200;

  function searchTileTerms(i, distType, cityName, unitTypes, tt) {
    const terms = [], raw = [];
    // ``terms`` is de-duplicated for display, ``raw`` keeps every occurrence so
    // the hit list can rank a tile that matched through several items higher
    // (the tile of a city named like the query matches both 城市名 and 归属文明名).
    const add = (value) => {
      if (!value || value === "—" || value.indexOf("0x") === 0) return;
      raw.push(value);
      if (terms.indexOf(value) < 0) terms.push(value);
    };
    const addName = (h) => add(nameOrDash(h));
    addName(tt.terrain[i]);
    addName(tt.feature[i]);
    addName(tt.resource[i]);
    addName(tt.improvement[i]);
    addName(tt.wonder[i]);
    const dt = distType.get(i);
    if (dt != null) add(districtTypeName(dt));
    const cn = cityName.get(i);
    if (cn) add(cn);
    if (tt.owner[i] >= 0) add(playerName(tt.owner[i]));
    if (isContinent(tt.continent[i])) add(continentName(tt.continent[i]));
    const units = unitTypes.get(i);
    if (units) for (const t of units) addName(t);
    return { terms: terms, raw: raw };
  }

  // 查询语法（v0.26）：「或 | 或 || or」分隔 OR 组，「且 | 与 | & | && | and」连接同一
  // 组内的 AND 词，「!」/「not」否定紧随其后的词。组内肯定词要全中、否定词要全不中
  // 才算组命中，组间取或；没有连接符就是普通的包含匹配（词里可以带空格，如大陆名）。
  const SEARCH_OR = /\s*(?:或|\|\||\|)\s*|\s+or\s+/i;
  const SEARCH_AND = /\s*(?:且|与|&&|&)\s*|\s+and\s+/i;

  function parseSearchQuery(text) {
    const groups = [];
    for (const part of String(text || "").split(SEARCH_OR)) {
      const pos = [], neg = [];
      for (let term of part.split(SEARCH_AND)) {
        term = term.trim();
        if (!term) continue;
        let negative = false;
        if (term.charAt(0) === "!") {
          negative = true; term = term.slice(1).trim();
        } else if (/^not\s+/i.test(term)) {
          negative = true; term = term.replace(/^not\s+/i, "").trim();
        }
        if (!term) continue;
        (negative ? neg : pos).push(term.toLowerCase());
      }
      if (pos.length || neg.length) groups.push({ pos: pos, neg: neg });
    }
    return groups;
  }

  // 组命中 = 每个肯定词都能在格子的词条里找到，且没有任何否定词命中（组间或）。
  function searchGroupsMatch(groups, terms) {
    const lc = terms.map((t) => t.toLowerCase());
    for (const g of groups) {
      if (!g.pos.every((n) => lc.some((t) => t.indexOf(n) >= 0))) continue;
      if (g.neg.some((n) => lc.some((t) => t.indexOf(n) >= 0))) continue;
      return true;
    }
    return false;
  }

  function runSearch() {
    searchQuery = ($("search-input").value || "").trim();
    searchExclude = ($("search-exclude").value || "").trim();
    const groups = parseSearchQuery(searchQuery);
    const excluded = parseSearchQuery(searchExclude);
    if (!currentTurn || !groups.length) {
      searchResult = { hits: [], total: 0 };
      renderSearchResults();
      if (map) map.setSearchHits(null);
      return;
    }
    const tt = currentTurn.tiles, w = currentTurn.width;
    const distType = new Map(), cityName = new Map(), unitTypes = new Map();
    for (const p of (currentTurn.players || [])) {
      for (const d of (p.districts || [])) distType.set(d.y * w + d.x, d.type);
      for (const c of (p.cities || [])) cityName.set(c.y * w + c.x, c.name);
    }
    for (const u of (currentTurn.units || [])) {
      const i = u.y * w + u.x;
      if (!unitTypes.has(i)) unitTypes.set(i, new Set());
      unitTypes.get(i).add(u.type);
    }
    const matches = [], ids = [];
    for (let i = 0; i < tt.terrain.length; i++) {
      const info = searchTileTerms(i, distType, cityName, unitTypes, tt);
      if (!info.terms.length) continue;
      if (excluded.length && searchGroupsMatch(excluded, info.terms)) continue;
      const lc = info.terms.map((t) => t.toLowerCase());
      const lcRaw = info.raw.map((t) => t.toLowerCase());
      let matched = null, weight = 0;
      for (const group of groups) {
        if (!group.pos.every((n) => lc.some((t) => t.indexOf(n) >= 0))) continue;
        if (group.neg.some((n) => lc.some((t) => t.indexOf(n) >= 0))) continue;
        if (!matched) matched = [];
        for (const t of info.terms) {
          const lt = t.toLowerCase();
          if (group.pos.some((n) => lt.indexOf(n) >= 0) && matched.indexOf(t) < 0) {
            matched.push(t);
          }
        }
        weight = Math.max(weight, group.pos.reduce(
          (n, needle) => n + lcRaw.filter((t) => t.indexOf(needle) >= 0).length, 0));
      }
      if (!matched) continue;
      ids.push(i);
      matches.push({ i: i, names: matched, weight: weight });
    }
    // The list is capped, so order it by relevance - the more searched items a
    // tile matched, the higher it ranks - then by tile order.
    matches.sort((a, b) => (b.weight - a.weight) || (a.i - b.i));
    searchResult = { hits: matches.slice(0, SEARCH_LIMIT), total: matches.length };
    renderSearchResults();
    map.setSearchHits(new Set(ids));
  }

  function renderSearchResults() {
    const box = $("search-results"), cnt = $("search-count");
    if (!box) return;
    box.innerHTML = "";
    if (cnt) {
      if (!searchQuery) cnt.textContent = searchExclude ? L("请先填写包含条件") : "";
      else cnt.textContent = searchResult.total
        ? `${L("共 ")}${searchResult.total}${L(" 处")}` +
          (searchResult.total > searchResult.hits.length
            ? `${L("（显示前 ")}${searchResult.hits.length}）` : "")
        : L("无匹配");
    }
    const w = currentTurn ? currentTurn.width : 0;
    for (const h of searchResult.hits) {
      const x = w ? (h.i % w) : h.i, y = w ? Math.floor(h.i / w) : 0;
      const row = document.createElement("div");
      row.className = "search-hit";
      row.innerHTML = `<span class="coord">(${x},${y})</span>` +
        `<span class="what">${h.names.join("、")}</span>`;
      row.onclick = () => { map.centerOnTile(h.i); onSelectTile(h.i); };
      box.appendChild(row);
    }
  }

  // --- v0.25 (文档 C5) save-directory modal --------------------------------
  let savedirDefault = "", savedirParent = null;
  let saveSourceBusy = false;

  function saveSourceLocked() {
    return !shareLocal || shareLockNote(L("打开存档")) || saveSourceBusy;
  }

  function setSaveSourceBusy(on) {
    saveSourceBusy = on;
    for (const id of ["savedir-ok", "savedir-pick", "savedir-file", "savedir-folder"])
      $(id).disabled = on;
  }

  async function importSaveFiles(files, kind) {
    if (saveSourceLocked()) return;
    const saves = Array.from(files).filter(file => /\.civ6save$/i.test(file.name));
    if (!saves.length) { setBanner(L("未找到 .Civ6Save 存档。"), true); return; }
    setSaveSourceBusy(true);
    setBanner(L("正在读取存档…"));
    try {
      const form = new FormData();
      for (const file of saves) form.append("saves", file, file.name);
      const response = await fetch(window.Civ6I18n.url("/api/saves/import?kind=" + kind),
        { method: "POST", body: form });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || String(response.status));
      $("savedir-modal").classList.add("hidden");
      await loadReplayList(body.selection);
    } catch (error) {
      setBanner(L("存档加载失败：") + error.message, true);
    } finally {
      setSaveSourceBusy(false);
    }
  }

  // A directory reader can return only one batch per call (often 100 entries).
  async function collectSaveEntry(entry, files) {
    if (entry.isFile) {
      if (/\.civ6save$/i.test(entry.name))
        files.push(await new Promise((resolve, reject) => entry.file(resolve, reject)));
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        if (!batch.length) break;
        for (const child of batch) await collectSaveEntry(child, files);
      }
    }
  }

  function wireSaveDrop() {
    let depth = 0;
    const overlay = $("save-drop-overlay");
    const isFiles = event => Array.from(event.dataTransfer?.types || []).includes("Files");
    document.addEventListener("dragenter", event => {
      if (!isFiles(event)) return;
      event.preventDefault(); ++depth;
      if (shareLocal && !saveSourceBusy && !shareState?.enabled) overlay.classList.remove("hidden");
    });
    document.addEventListener("dragover", event => {
      if (!isFiles(event)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = shareLocal && !saveSourceBusy && !shareState?.enabled ? "copy" : "none";
    });
    document.addEventListener("dragleave", event => {
      if (!isFiles(event)) return;
      if (--depth <= 0) { depth = 0; overlay.classList.add("hidden"); }
    });
    window.addEventListener("blur", () => { depth = 0; overlay.classList.add("hidden"); });
    document.addEventListener("drop", async event => {
      if (!isFiles(event)) return;
      event.preventDefault(); depth = 0; overlay.classList.add("hidden");
      if (saveSourceLocked()) return;
      // Capture both entries and fallback files before yielding: the browser
      // protects the drag data store as soon as the drop handler returns.
      const items = Array.from(event.dataTransfer.items || []).filter(item => item.kind === "file");
      const entries = items.map(item => item.webkitGetAsEntry?.());
      const fallback = Array.from(event.dataTransfer.files);
      try {
        const files = [];
        const useEntries = entries.length && entries.every(Boolean);
        if (useEntries) for (const entry of entries) await collectSaveEntry(entry, files);
        else files.push(...fallback);
        const directory = entries.some(entry => entry?.isDirectory) || files.length > 1;
        await importSaveFiles(files, directory ? "directory" : "file");
      } catch (error) { setBanner(L("存档加载失败：") + error.message, true); }
    });
  }

  function wireSaveDirModal() {
    wireSaveDrop();
    $("savedir-input").addEventListener("keydown", event => {
      if (event.key === "Enter") confirmSaveDir();
    });
    for (const [button, input, kind] of [["savedir-file", "save-file-input", "file"],
      ["savedir-folder", "save-folder-input", "directory"]]) {
      $(button).onclick = () => { if (!saveSourceLocked()) $(input).click(); };
      $(input).onchange = async () => {
        const files = Array.from($(input).files);
        $(input).value = "";
        if (files.length) await importSaveFiles(files, kind);
      };
    }
    $("savedir-close").onclick = () => $("savedir-modal").classList.add("hidden");
    $("savedir-cancel").onclick = () => $("savedir-modal").classList.add("hidden");
    $("savedir-ok").onclick = confirmSaveDir;
    $("savedir-use-default").onclick = () => { $("savedir-input").value = savedirDefault; };
    // v0.26: the OS folder dialog (Windows only; a 501 keeps the manual box)
    $("savedir-pick").onclick = async () => {
      const revision = languageSeq;
      const btn = $("savedir-pick");
      btn.disabled = true;
      try {
        const resp = await fetch(window.Civ6I18n.url("/api/savedir/pick"), { method: "POST" });
        const body = await resp.json().catch(() => ({}));
        if (revision !== languageSeq) return;
        if (!resp.ok) {
          showSaveDirError(body.detail || (L("无法打开目录选择框（HTTP ") + resp.status + "）"));
          return;
        }
        if (body.path) {
          $("savedir-input").value = body.path;
          $("savedir-error").classList.add("hidden");
        }
      } catch (e) {
      if (e.name === "AbortError") return;
        showSaveDirError(L("无法打开目录选择框：") + e.message);
      } finally {
        btn.disabled = false;
      }
    };
    $("savedir-parent").onclick = () => {
      if (!savedirParent) return;
      $("savedir-input").value = savedirParent;
      loadSaveDirTree(savedirParent).catch((e) => showSaveDirError(L("无法读取目录：") + e.message));
    };
    $("savedir-modal").addEventListener("click", (e) => {
      if (e.target === $("savedir-modal")) $("savedir-modal").classList.add("hidden");
    });
  }

  function showSaveDirError(msg) {
    const box = $("savedir-error");
    box.textContent = msg;
    box.classList.remove("hidden");
  }

  async function openSaveDirModal() {
    if (shareLockNote(L("存档目录"))) return;
    $("savedir-modal").classList.remove("hidden");
    $("savedir-error").classList.add("hidden");
    $("savedir-tree").innerHTML = "";
    try {
      const cur = await getJSON("/api/savedir");
      savedirDefault = cur.default || "";
      $("savedir-current").textContent = cur.current || "—";
      $("savedir-default").textContent = savedirDefault || "—";
      $("savedir-input").value = cur.current || "";
      await loadSaveDirTree(cur.browse || cur.current);
    } catch (e) {
      if (e.name === "AbortError") return;
      showSaveDirError(L("无法读取目录信息：") + e.message);
    }
  }

  // one level of ``/api/browse``; sub-directories expand lazily on demand
  async function loadSaveDirTree(path) {
    const box = $("savedir-tree");
    const res = await getJSON("/api/browse?path=" + encodeURIComponent(path || ""));
    savedirParent = res.parent || null;
    box.innerHTML = "";
    const title = document.createElement("div");
    title.className = "dir-title";
    title.textContent = res.path || L("本机盘符");
    if (!res.path) title.dataset.i18n = "本机盘符";
    box.appendChild(title);
    for (const d of res.dirs) box.appendChild(saveDirNode(d, 0));
  }

  function saveDirNode(dir, depth) {
    const node = document.createElement("div");
    node.className = "dir-node";
    const row = document.createElement("div");
    row.className = "dir-row";
    row.style.paddingLeft = (10 + depth * 14) + "px";
    const caret = document.createElement("span");
    caret.className = "caret";
    caret.textContent = "▸";
    const name = document.createElement("span");
    name.className = "dir-name";
    name.textContent = dir.name;
    row.appendChild(caret); row.appendChild(name);
    if (dir.hasSaves) {
      const flag = document.createElement("span");
      flag.className = "dir-flag";
      flag.textContent = L("含存档");
      flag.dataset.i18n = "含存档";
      row.appendChild(flag);
    }
    name.onclick = () => { $("savedir-input").value = dir.path; };
    const kids = document.createElement("div");
    kids.className = "dir-kids hidden";
    caret.onclick = async (e) => {
      e.stopPropagation();
      if (kids.dataset.loaded === "1") {
        kids.classList.toggle("hidden");
        caret.textContent = kids.classList.contains("hidden") ? "▸" : "▾";
        return;
      }
      try {
        const res = await getJSON("/api/browse?path=" + encodeURIComponent(dir.path));
        kids.innerHTML = "";
        for (const c of res.dirs) kids.appendChild(saveDirNode(c, depth + 1));
        kids.dataset.loaded = "1";
        kids.classList.remove("hidden");
        caret.textContent = "▾";
      } catch (err) {
        showSaveDirError(L("无法读取目录：") + err.message);
      }
    };
    node.appendChild(row); node.appendChild(kids);
    return node;
  }

  async function confirmSaveDir() {
    if (saveSourceLocked()) return;
    const path = $("savedir-input").value.trim();
    if (!path) { showSaveDirError(L("请输入或从目录树选择路径")); return; }
    setSaveSourceBusy(true);
    try {
      const resp = await fetch(window.Civ6I18n.url("/api/savedir"), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path }),
      });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        showSaveDirError(body.detail || (L("切换失败（HTTP ") + resp.status + "）"));
        return;
      }
      $("savedir-modal").classList.add("hidden");
      await loadReplayList(body.selection);
    } catch (e) {
      if (e.name === "AbortError") return;
      showSaveDirError(L("切换失败：") + e.message);
    } finally {
      setSaveSourceBusy(false);
    }
  }

  // --- v0.38 共享 -----------------------------------------------------------
  // 共享由后端真正另起一个对外监听器（见 civ6replay/share.py）；前端只负责挑选
  // 写进链接的地址、拼分享文案，并把「刷新存档 / 存档目录」锁掉。
  let SHARE_KIND_ZH;
  let SHARE_SOURCE_ZH;
  let SHARE_GROUPS;

  let shareState = null, shareHost = null, sharePort = null, shareBusy = false;
  // 当前页面是不是从本机（127.0.0.1 / ::1）打开的 —— 不是的话这是「被共享的那一页」：
  // 没有刷新 / 存档目录（那是主机的事），共享按钮改成复制当前回合的链接。
  let shareLocal = true;

  function wireShareModal() {
    $("btn-share").onclick = () => {
      if (!shareLocal) { copyViewerLink(); return; }
      if (shareState && shareState.enabled) stopShare(); else startShare();
    };
    $("share-close").onclick = () => $("share-modal").classList.add("hidden");
    $("share-done").onclick = () => $("share-modal").classList.add("hidden");
    $("share-stop").onclick = stopShare;
    // 关掉对话框后还能回来看看链接（不改共享状态）
    $("btn-share-link").onclick = () => {
      $("share-modal").classList.remove("hidden");
      applyShareInfo(shareState);
      refreshShareText();
    };
    $("share-copy").onclick = copyShareText;
    $("share-apply").onclick = () => applyShare();
    $("share-rescan").onclick = () => refreshShareProbe({ remote: true });
    $("share-host").onchange = () => { $("share-host-input").value = ""; applyShare(); };
    $("share-modal").addEventListener("click", (e) => {
      if (e.target === $("share-modal")) $("share-modal").classList.add("hidden");
    });
  }

  // 刷新页面后恢复按钮与锁定态；非本机访客的共享按钮置灰
  async function initShare() {
    let info = null;
    try { info = await getJSON("/api/share"); } catch (e) {
      if (e.name === "AbortError") return; return; }
    shareLocal = !!info.isLocal;
    if (!shareLocal) {
      // 访客页（被共享的那一页）：刷新存档 / 存档目录整条删掉 —— 那是主机上的操作
      $("btn-refresh").classList.add("hidden");
      $("btn-savedir").classList.add("hidden");
    }
    setShareLock(!!info.enabled);
    if (info.enabled) {                 // 刷新页面后把对话框内容也恢复出来
      shareState = info;
      applyShareInfo(info);
    }
  }

  // 共享中：顶上那两个按钮变灰但**仍然可点**，点一下说明为什么按不动
  function shareLockNote(what) {
    if (!shareState || !shareState.enabled) return false;
    const where = shareState.base ? `（${shareState.base}${L(" 正在被别人看着）")}` : "";
    setBanner(`${L("共享中已锁定「")}${what}」${where}：`
              + L("主机一改，别人看到的就不是同一局了。先点顶栏「停止共享」再操作。"), true);
    return true;
  }

  function setShareLock(on) {
    const btn = $("btn-share");
    // 访客页的共享按钮是「复制链接」（复制当前回合，方便刷新回同一个局面）
    btn.textContent = !shareLocal ? L("复制链接") : (on ? L("停止共享") : L("共享"));
    btn.classList.toggle("active", on && shareLocal);
    btn.title = !shareLocal ? L("复制当前回合的复盘链接")
               : (on ? L("停止共享（点击即关闭对外监听并解锁）") : L("共享复盘"));
    // 锁定用的是「变灰但仍可点」，不能用 disabled —— 那样点上去一点反馈都没有
    for (const id of ["btn-refresh", "btn-savedir"]) $(id).classList.toggle("btn-blocked", on);
    $("btn-refresh").title = on ? L("共享中已锁定（点击看原因）") : L("重新扫描存档");
    $("btn-savedir").title = on ? L("共享中已锁定（点击看原因）") : L("打开存档文件或文件夹");
    // 访客页面没有共享开关，自然也不给「链接」入口
    $("btn-share-link").classList.toggle("hidden", !on || !shareLocal);
    if (on) $("savedir-modal").classList.add("hidden");
  }

  async function startShare() {
    if (shareBusy) return;
    shareBusy = true;
    $("share-modal").classList.remove("hidden");
    $("share-state").textContent = L("正在启动共享监听…");
    $("share-reach").textContent = L("正在检测…");
    let info = null;
    try {
      info = await postJSON("/api/share/start", {});
      applyShareInfo(info);
      setShareLock(true);
    } catch (e) {
      if (e.name === "AbortError") return;
      $("share-state").textContent = L("启动失败：") + e.message;
    } finally {
      shareBusy = false;
    }
    // 网卡层没找到公网 IP 时才去问云元数据 / 外部回显（约 1-3 秒）
    if (info) await refreshShareProbe({ remote: true });
  }

  async function stopShare() {
    if (shareBusy) return;
    shareBusy = true;
    try { await postJSON("/api/share/stop", {}); } catch (e) {
      if (e.name === "AbortError") return; /* 后端已停 */ }
    shareState = null; shareHost = null; sharePort = null;
    setShareLock(false);
    $("share-modal").classList.add("hidden");
    shareBusy = false;
  }

  // 「应用」/ 切换候选地址：地址只改文案，端口变了后端才会重绑监听
  async function applyShare() {
    if (shareBusy) return;
    const typed = $("share-host-input").value.trim();
    const host = typed || $("share-host").value || "";
    const body = {};
    if (host) body.host = host;
    const rawPort = $("share-port-input").value.trim();
    if (rawPort) {
      const n = parseInt(rawPort, 10);
      if (!Number.isFinite(n) || n < 1 || n > 65535) {
        $("share-state").textContent = L("端口要是 1-65535 的数字。");
        return;
      }
      body.port = n;
    }
    shareBusy = true;
    $("share-state").textContent = L("正在应用…");
    try {
      applyShareInfo(await postJSON("/api/share/start", body));
      setShareLock(true);
    } catch (e) {
      if (e.name === "AbortError") return;
      $("share-state").textContent = L("应用失败：") + e.message;
    } finally {
      shareBusy = false;
    }
  }

  async function refreshShareProbe({ remote }) {
    if (shareBusy) return;
    shareBusy = true;
    if (remote) $("share-reach").textContent = L("正在检测本机地址（含云元数据 / 外部回显）…");
    try {
      const q = new URLSearchParams();
      if (shareHost) q.set("host", shareHost);
      if (sharePort) q.set("port", sharePort);
      if (remote) q.set("remote", "1");
      const info = await getJSON("/api/share/probe?" + q.toString());
      applyShareInfo(info);
      setShareLock(!!info.enabled);
    } catch (e) {
      if (e.name === "AbortError") return;
      $("share-reach").textContent = L("检测失败：") + e.message;
    } finally {
      shareBusy = false;
    }
  }

  function applyShareInfo(info) {
    if (!info) return;
    shareState = info;
    if (info.host) shareHost = info.host;
    if (info.port) sharePort = info.port;
    const kind = SHARE_KIND_ZH[info.kind] || info.kind;
    const src = SHARE_SOURCE_ZH[info.source] || info.source;
    $("share-state").textContent = info.base
      ? `${info.enabled ? L("共享中") : L("未共享")} · ${info.base}（${kind}，${src}）`
      : `${info.enabled ? L("共享中") : L("未共享")} · ${kind}`;
    $("share-reach").textContent = (info.reach && info.reach.detail) || "—";
    $("share-note").textContent = info.note || "";
    renderShareHosts(info.candidates || []);
    if (document.activeElement !== $("share-port-input")) {
      $("share-port-input").value = info.port || "";
    }
    $("share-port-input").placeholder = String(info.port || L("端口"));
    $("share-text").value = composeShareText(info);
    $("share-stop").disabled = !info.enabled;
  }

  function renderShareHosts(cands) {
    const sel = $("share-host");
    const keep = shareHost || sel.value;
    sel.innerHTML = "";
    let found = false;
    for (const [kind, label] of SHARE_GROUPS) {
      const group = cands.filter((c) => c.kind === kind);
      if (!group.length) continue;
      const og = document.createElement("optgroup");
      og.label = label;
      for (const c of group) {
        const opt = document.createElement("option");
        opt.value = c.ip;
        opt.textContent = c.label || c.ip;
        if (c.ip === keep) found = true;
        og.appendChild(opt);
      }
      sel.appendChild(og);
    }
    if (!found && keep) {                // 手填 / 探测到的地址也留在列表里
      const opt = document.createElement("option");
      opt.value = keep;
      opt.textContent = keep + " · " +
        (SHARE_KIND_ZH[(shareState && shareState.kind) || ""] || L("当前"));
      sel.appendChild(opt);
    }
    if (keep) sel.value = keep;
  }

  function composeShareText(info) {
    if (!info || !info.base) return L("尚未检测到可用地址：请从上面选一个，或手填 ip:端口。");
    const q = [];
    if (seed != null) q.push("seed=" + seed);
    if (currentTurn && currentTurn.turn != null) {
      q.push("turn=" + Math.max(0, currentTurn.turn));
    }
    const url = info.base + "/" + (q.length ? "?" + q.join("&") : "");
    let text = `${L("复盘链接 ")}${url}${L("，可在浏览器中查看")}`;
    if (info.hint) text += "\n" + info.hint;      // UU 场景的额外提醒
    return text;
  }

  // 换回合时链接里的 turn 跟着变（对话框开着才算）
  function refreshShareText() {
    if (!shareState || !shareState.enabled) return;
    if ($("share-modal").classList.contains("hidden")) return;
    $("share-text").value = composeShareText(shareState);
  }

  // 剪贴板：优先 navigator.clipboard；访客页跑在 http://<ip>:<port> 上不是安全上下文，
  // 那里根本没有 navigator.clipboard，所以必须有 execCommand 这条退路。
  async function copyText(text) {
    const value = text || "";
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try { await navigator.clipboard.writeText(value); return true; } catch (e) {
      if (e.name === "AbortError") return; /* 走退路 */ }
    }
    const box = document.createElement("textarea");
    box.value = value;
    box.setAttribute("readonly", "readonly");
    box.style.position = "fixed";
    box.style.left = "-9999px";
    document.body.appendChild(box);
    let ok = false;
    try { box.select(); ok = document.execCommand("copy"); } catch (e) {
      if (e.name === "AbortError") return; ok = false; }
    document.body.removeChild(box);
    window.getSelection().removeAllRanges();
    return ok;
  }

  async function copyShareText() {
    const ok = await copyText($("share-text").value);
    $("share-copied").textContent = ok ? L("已复制") : L("复制失败，请手动选中复制");
    setTimeout(() => { $("share-copied").textContent = ""; }, 2000);
  }

  // 访客页的「复制链接」：用**本页自己的地址**（就是对方真正能打开的那个）加上
  // 当前对局与回合 —— 对方拿到链接打开是这个局面，自己刷新也能回到同一回合。
  async function copyViewerLink() {
    const q = [];
    if (seed != null) q.push("seed=" + seed);
    if (currentTurn && currentTurn.turn != null) {
      q.push("turn=" + Math.max(0, currentTurn.turn));
    }
    const url = location.origin + location.pathname + (q.length ? "?" + q.join("&") : "");
    const btn = $("btn-share");
    const ok = await copyText(url);
    btn.textContent = ok ? L("已复制") : L("复制失败");
    btn.title = ok ? url : L("复制失败，请手动从地址栏复制");
    setTimeout(() => {
      btn.textContent = L("复制链接");
      btn.title = L("复制当前回合的复盘链接");
    }, 1600);
  }

  // --- tile / city lookups ------------------------------------------------
  function districtAt(i) {
    const w = currentTurn.width;
    for (const p of (currentTurn.players || [])) {
      for (const d of (p.districts || [])) {
        if (d.y * w + d.x === i) return { d, iPlayer: p.iPlayer };
      }
    }
    return null;
  }
  function cityById(iPlayer, cityId) {
    const p = (currentTurn.players || []).find((x) => x.iPlayer === iPlayer);
    return p ? (p.cities || []).find((c) => c.id === cityId) : null;
  }
  function districtTypeName(dh) {
    const h = dh >>> 0;
    if (h === DISTRICT_CITY_CENTER) return L("市中心");
    if (h === DISTRICT_WONDER) return L("奇观");
    return nameOf(h);
  }
  // v0.25 (文档 C1): the district on a tile, by its *type* (``tiles.district``
  // holds the district id, not the type hash, so the id must be looked up).
  function districtTypeAt(i) {
    const found = districtAt(i);
    return found ? districtTypeName(found.d.type) : null;
  }
  // Only districts with positive HitPoints in the rules snapshot have HP.
  function districtHPMax(d) {
    const caps = (staticInfo && staticInfo.districtHitPoints) || {};
    const hash = hashStr(d.type);
    if (Object.prototype.hasOwnProperty.call(caps, hash)) return Math.max(0, Number(caps[hash]) || 0);
    return (d.type >>> 0) === DISTRICT_CITY_CENTER ? CITY_CENTER_HP : 0;
  }

  function districtHPText(d) {
    const max = districtHPMax(d);
    return `${Math.max(0, max - (Number(d.damage) || 0))} / ${max}`;
  }
  // v0.23: ``city.built`` maps {building hash: tile index}, so buildings are
  // grouped by their actual tile instead of a guessed host district.
  function builtAt(city, i) {
    const built = city.built || {};
    const out = [];
    for (const k in built) if (built[k] === i) out.push(parseInt(k, 10));
    return out;
  }

  function tileWonderStatus(i, tt, found) {
    const hash = tt.wonder[i];
    if (hash == null || (hash >>> 0) === 0xFFFFFFFF) return "";
    const host = (found && cityById(found.iPlayer, found.d.cityId)) || cityById(tt.owner[i], tt.city[i]);
    if (host) return (host.built || {})[hashStr(hash)] === i ? L("已建成") : L("建造中");
    return found && found.d.built === 0 ? L("建造中") : "";
  }

  function tileWonderHTML(i, tt, found) {
    const hash = tt.wonder[i];
    if (hash == null || (hash >>> 0) === 0xFFFFFFFF) return "";
    const status = tileWonderStatus(i, tt, found);
    return nameHTML(hash) + (status ? `<span class="dstat${status === L("建造中") ? " wip" : ""}">（${status}）</span>` : "");
  }
  // v0.30: the game pillages a district layer by layer - the topmost building
  // first, the district itself last - so a district can be intact while some of
  // its buildings are already pillaged.  ``city.pillagedBuildings`` carries the
  // hashes the save flags (``pCityBuildings:IsPillaged``); fall back to the host
  // district's own flag for payloads cached before v0.30.
  function pillagedBuildingSet(city) {
    const list = city && city.pillagedBuildings;
    if (Array.isArray(list)) return new Set(list.map((h) => h >>> 0));
    return new Set();
  }
  function isBuildingPillaged(city, hash, district) {
    if (city && Array.isArray(city.pillagedBuildings)) {
      return pillagedBuildingSet(city).has(hash >>> 0);
    }
    return !!(district && district.pillage === 1);
  }
  function onHoverTile(ev) {
    const tip = $("tooltip");
    // v0.25 (PLAN B4): the map reports the city status bar as its own hit
    // target, so one handler owns #tooltip and the two tooltips cannot fight.
    if (ev && ev.city) { cityTooltip(ev); return; }
    if (!ev || ev.i < 0 || !currentTurn) { tip.classList.add("hidden"); return; }
    const tt = currentTurn.tiles;
    const lines = [nameOf(tt.terrain[ev.i])];
    if ((tt.feature[ev.i] >>> 0) !== 0xFFFFFFFF) lines.push(L("地貌: ") + nameOf(tt.feature[ev.i]));
    if ((tt.resource[ev.i] >>> 0) !== 0xFFFFFFFF) lines.push(L("资源: ") + nameOf(tt.resource[ev.i]));
    if ((tt.improvement[ev.i] >>> 0) !== 0xFFFFFFFF) {
      let s = L("改良: ") + nameOf(tt.improvement[ev.i]);
      if ((tt.flags[ev.i] & 2)) s += L("（被掠夺）");
      lines.push(s);
    }
    const dist = districtAt(ev.i);
    if (dist) {
      const d = dist.d;
      if ((d.type >>> 0) !== DISTRICT_WONDER) {
        const host = cityById(dist.iPlayer, d.cityId);
        const st = d.built === 0 ? L("建设中") : (d.pillage === 1 ? L("被掠夺") : L("已建成"));
        let s = L("区域: ") + nameOf(d.type) + "（" + st + "）";
        // v0.25 (文档 C1): 血量 (max − damage), same wording as the city panel
        if (districtHPMax(d)) s += L(" 血量 ") + districtHPText(d);
        if (d.wall) s += L(" 城墙 ") + districtWallText(d, host, dist.iPlayer);
        lines.push(s);
        if (d.adjacency != null) {
          const positive = Object.entries(d.adjacency).filter(([, v]) => v > 0);
          const label = d.built === 0 ? L("预计相邻") : L("基础相邻");
          lines.push(label + ": " + (positive.length ? positive.map(([yh, v]) =>
            (((staticInfo.yieldMeta || {})[yh] || {}).name || nameOf(Number(yh))) +
              " +" + v).join("、") : "0"));
        }
        const bl = host ? builtAt(host, ev.i) : [];
        if (bl.length) {
          // v0.30: mark the buildings that are pillaged *individually* (the
          // district flag alone would mislabel an intact-but-stripped district)
          lines.push(L("建筑: ") + bl.map((bh) => nameOf(bh) +
                     (isBuildingPillaged(host, bh, d) ? L("（被掠夺）") : ""))
                     .join("、"));
        }
      }
    }
    if ((tt.wonder[ev.i] >>> 0) !== 0xFFFFFFFF) {
      const status = tileWonderStatus(ev.i, tt, dist);
      lines.push(L("奇观: ") + nameOf(tt.wonder[ev.i]) + (status ? `（${status}）` : ""));
    }
    if (tt.owner[ev.i] >= 0) lines.push(L("归属: ") + playerName(tt.owner[ev.i]));
    tip.innerHTML = lines.join("<br>");
    tip.style.left = (ev.x + 14) + "px"; tip.style.top = (ev.y + 14) + "px";
    tip.classList.remove("hidden");
  }

  // 城市状态条 tooltip: 名称 / 人口 / 城墙 / 主流宗教 / 当前生产。v0.26 起条上不再
  // 有盾牌，城墙读数（含钢铁后的「城市防御」）统一由 ``wallText`` 给出。
  function cityTooltip(ev) {
    const tip = $("tooltip");
    const p = (currentTurn.players || []).find((x) => x.iPlayer === ev.city.iPlayer);
    const c = p && (p.cities || []).find((x) => x.id === ev.city.cityId);
    if (!c) { tip.classList.add("hidden"); return; }
    const lines = [`<b>${c.name || "?"}</b>`, L("人口 ") + c.population];
    if (cityWall(ev.city.iPlayer, c)) {
      lines.push(L("城墙 ") + wallText(ev.city.iPlayer, c, c.wallDamage));
    }
    if (c.religion != null && (c.religion >>> 0) !== 0xFFFFFFFF) {
      lines.push(L("主流宗教: ") + religionName(c.religion));
    }
    const prod = (c.currentProds || [])[0];
    if (prod != null) lines.push(L("当前生产: ") + nameOf(prod));
    tip.innerHTML = lines.join("<br>");
    tip.style.left = (ev.x + 14) + "px"; tip.style.top = (ev.y + 14) + "px";
    tip.classList.remove("hidden");
  }

  // Replay aliases take precedence for unknown religions; recognized religions
  // retain the current turn's custom name or their identity name.
  function religionName(hash) {
    const h = hash >>> 0;
    const fallback = staticInfo && staticInfo.religionFallbacks && staticInfo.religionFallbacks[hashStr(h)];
    if (fallback) return unknownReligionName(fallback.number);
    const found = religionsNow().find((r) => (r.symbol >>> 0) === h);
    return (found && found.name) ? found.name : nameOf(h);
  }

  function playerInfo(i) {
    return (staticInfo.players || []).find((x) => x.iPlayer === i) || null;
  }
  function playerName(i) {
    const p = playerInfo(i);
    return p ? (p.civName || ("P" + i)) : ("P" + i);
  }
  function playerPrimary(i) { const p = playerInfo(i); return cssColor(p && p.primary, 200); }

  // ``keepHidden`` is used by the turn / 文案 refresh paths: a tile the user
  // explicitly closed must stay closed (only a real click re-opens the panel).
  async function onSelectTile(i, keepHidden) {
    if (!currentTurn) return;
    const seq = replaySeq, payload = currentTurn;
    let adjacencyOpen = !!$("tile-body").querySelector("details.adjacency-details")?.open;
    const tt = currentTurn.tiles;
    const followContinent = !keepHidden && map && map.continentHighlight != null;
    if (followContinent) {
      // Keep the lens open while selecting tiles, including passing over open
      // water; only a tile with a continent changes the highlighted region.
      if (isContinent(tt.continent[i])) map.setContinentHighlight(tt.continent[i]);
      activeTab = "terrain";
    }
    if (!keepHidden) openPanel("tile");
    $("tile-title").textContent = `${L("格子 #")}${i}  (${i % currentTurn.width}, ${(i / currentTurn.width) | 0})`;
    const tabs = [[L("信息"), "terrain"], [L("产出"), "yields"], [L("区域"), "district"], [L("单位"), "units"]];
    const keys = tabs.map((t) => t[1]);
    if (keys.indexOf(activeTab) < 0) activeTab = "terrain";
    const tabsBox = $("tile-tabs"); tabsBox.innerHTML = "";
    const body = $("tile-body");
    const render = async () => {
      const previousAdjacency = body.querySelector("details.adjacency-details");
      if (previousAdjacency) adjacencyOpen = previousAdjacency.open;
      tabsBox.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === activeTab));
      const html = await renderTab(activeTab, i, tt);
      if (seq !== replaySeq || currentTurn !== payload) return;
      body.innerHTML = html;
      const adjacencyDetails = body.querySelector("details.adjacency-details");
      if (adjacencyDetails) {
        adjacencyDetails.open = adjacencyOpen;
        adjacencyDetails.ontoggle = () => {
          if (adjacencyDetails.isConnected) adjacencyOpen = adjacencyDetails.open;
        };
      }
      wireTileLinks(body);
      if (followContinent) body.querySelector(".continent-luxuries:not(.hidden)")
        ?.scrollIntoView({ block: "nearest" });
    };
    for (const [label, key] of tabs) {
      const b = document.createElement("button"); b.textContent = label; b.dataset.tab = key;
      b.onclick = () => { activeTab = key; render(); };
      tabsBox.appendChild(b);
    }
    render();
  }
  // Links inside the tile panel: the owner city (opens the city panel) and the
  // continent entry (toggles the continent highlight; a second click clears it).
  function wireTileLinks(body) {
    body.querySelectorAll("a.adjacency-coordinate[data-jump-i]").forEach((a) => {
      a.onclick = (e) => {
        e.preventDefault();
        const index = Number(a.dataset.jumpI);
        if (!Number.isInteger(index) || index < 0 || index >= currentTurn.width * currentTurn.height) return;
        map.centerOnTile(index);
        onSelectTile(index);
      };
    });
    body.querySelectorAll("a.city-link[data-open-p]").forEach((a) => {
      a.onclick = (e) => {
        e.preventDefault();
        openCityPanel(parseInt(a.dataset.openP, 10), parseInt(a.dataset.openC, 10));
      };
    });
    body.querySelectorAll("a.continent-link[data-cont]").forEach((a) => {
      a.onclick = (e) => {
        e.preventDefault();
        const hash = parseInt(a.dataset.cont, 10) >>> 0;
        const next = (map.continentHighlight === hash) ? null : hash;
        map.setContinentHighlight(next);
        refreshContinentLinks(body);
        if (next != null) body.querySelector(`.continent-luxuries[data-cont="${next}"]`)
          ?.scrollIntoView({ block: "nearest" });
      };
    });
    refreshContinentLinks(body);
  }

  function refreshContinentLinks(body) {
    const selected = map.continentHighlight;
    body.querySelectorAll("a.continent-link[data-cont]").forEach((a) => {
      a.classList.toggle("active", selected != null && (Number(a.dataset.cont) >>> 0) === selected);
    });
    body.querySelectorAll(".continent-luxuries[data-cont]").forEach((line) => {
      const hash = Number(line.dataset.cont) >>> 0;
      const active = selected != null && hash === selected;
      line.classList.toggle("hidden", !active);
      line.innerHTML = active ? continentLuxuryHTML(hash) : "";
    });
  }

  function continentLuxuryHTML(hash) {
    const types = map.continentLuxuryResources(hash).slice(0, 4);
    if (!types.length) return L('<span class="muted">无陆地奢侈品</span>');
    return types.map((h) => {
      const icon = iconOf(h);
      return `<span class="continent-luxury">${icon ? `<img src="${icon}" alt="" width="18" height="18">` : ""}${nameHTML(h)}</span>`;
    }).join("");
  }

  async function renderTab(key, i, tt) {
    if (key === "terrain") {
      const rows = [
        [L("地形"), terrainNameHTML(tt.terrain[i], tt.continent[i])],
        [L("地貌"), fmtName(tt.feature[i])],
        [L("资源"), fmtName(tt.resource[i])],
        [L("改良"), fmtName(tt.improvement[i]) + (((tt.improvement[i] >>> 0) !== 0xFFFFFFFF && (tt.flags[i] & 2)) ? L(" <span class='muted'>（被掠夺）</span>") : "")],
        [L("道路"), routeName(tt.road[i])],
        [L("魅力"), String(tt.appeal[i])],
        // v0.31: 核污染 —— 剩余回合数（0 = 未受污染，显示「无」）
        [L("污染"), falloutText(tt.fallout ? tt.fallout[i] : 0)],
        [L("河流"), (tt.riverBits[i] & 0xFF) ? ((tt.riverBits[i] & 0xFF) + L(" 边")) : L("无")],
        [L("悬崖"), tt.cliffBits[i] ? L("有") : L("无")],
        [L("归属"), tt.owner[i] >= 0 ? playerName(tt.owner[i]) : "—"],
        [L("所属城市"), cityLinkHTML(tt.owner[i], tt.city[i])],
        [L("区域"), districtTypeAt(i) || "—"],
        [L("大陆"), continentHTML(tt.continent[i])],
      ];
      let html = '<div class="kv">';
      for (const [k, v] of rows) html += `<div class="k">${k}</div><div class="v">${v}</div>`;
      html += "</div>";
      return html;
    }
    if (key === "yields") return tileYieldPanel((currentTurn.tileYields || [])[i]);
    if (key === "units") {
      const list = (currentTurn.units || []).filter((u) => (u.y * currentTurn.width + u.x) === i);
      if (!list.length) return L("<div class='loading'>无单位</div>");
      return list.map((u) => {
        const ic = iconOf(u.type);
        const cat = CAT_ZH[u.cat] || L("军事");
        const label = armyLabel(u.army, u.sea);
        const details = [playerName(u.iPlayer), unitHealthHTML(u) + unitPromotionHTML(u),
          label ? `<span class="stars">${armyStars(u.army)}</span>${label}` : "",
          isMilitaryUnit(u) && u.fortified ? L("驻守") : "",
          showCoord ? `(${u.x},${u.y})` : ""].filter(Boolean).join(" · ");
        return `<div class="unit-line"><span class="swatch" style="background:${playerPrimary(u.iPlayer)}"></span>${ic ? `<img src="${ic}" width="18" height="18">` : ""}
          <span><b>${nameHTML(u.type)}</b><span class="cat">${cat}</span></span>
          <span class="sub">${details}</span></div>`;
      }).join("");
    }
    if (key === "district") {
      const found = districtAt(i);
      const wonder = tileWonderHTML(i, tt, found);
      const wonderRow = wonder ? `${L("<div class=\"kv\"><div class=\"k\">奇观</div><div class=\"v\">")}${wonder}</div></div>` : "";
      if (!found) return wonderRow;
      const d = found.d;
      const isWonderMarker = (d.type >>> 0) === DISTRICT_WONDER;
      if (isWonderMarker) return wonderRow;
      const status = d.built === 0 ? L("建设中") : (d.pillage === 1 ? L("被掠夺") : L("已建成"));
      const host = cityById(found.iPlayer, d.cityId);
      const rows = [
        [L("区域"), nameHTML(d.type)],
        [L("状态"), status],
        [L("所属城市"), host ? host.name : ("#" + d.cityId)],
        [L("归属"), playerName(found.iPlayer)],
      ];
      if (districtHPMax(d)) {
        rows.push([L("血量"), districtHPText(d)], [L("城墙"), districtWallText(d, host, found.iPlayer)]);
      }
      let html = '<div class="kv">';
      for (const [k, v] of rows) html += `<div class="k">${k}</div><div class="v">${v}</div>`;
      html += "</div>";
      const bl = host ? builtAt(host, i) : [];
      html += adjacencySourcePanel(d);
      html += `${L("<div style=\"margin-top:8px\">建筑：")}`;
      if (!bl.length) html += L("<span class='muted'>无</span>");
      else {
        html += bl.map((bh) => {
          const ic = iconOf(bh);
          // v0.30: per-building pillage state instead of "every building of a
          // pillaged district"
          const mark = isBuildingPillaged(host, bh, d)
            ? `${L("<span class=\"bld-pillaged\">（被掠夺）</span>")}` : "";
          return `<span class="chip">${ic ? `<img src="${ic}">` : ""}${nameHTML(bh)}${mark}</span>`;
        }).join("");
      }
      html += "</div>";
      if (wonderRow) html += `<div style="margin-top:6px">${wonderRow}</div>`;
      return html;
    }
    return "";
  }

  function fmtName(h) {
    if ((h >>> 0) === 0xFFFFFFFF) return "—";
    return nameHTML(h);
  }

  // 存档中的海岸与湖泊共用 TERRAIN_COAST；只在地形字段按大陆区分名称。
  function terrainNameHTML(h, continent) {
    const info = names[hashStr(h)];
    if (!info || info.type !== "TERRAIN_COAST") return fmtName(h);
    const label = isContinent(continent) ? L("湖泊") : L("海岸");
    return label + typeTag(info.type);
  }

  // v0.25 (文档 C1): 所属城市 - the tile carries the owner and the city *id*, so
  // the name has to be looked up in that player's city list; clickable when found.
  function cityLinkHTML(owner, cityId) {
    if (owner == null || owner < 0 || cityId == null || cityId < 0) return "—";
    const c = cityById(owner, cityId);
    if (!c) return "#" + cityId;
    return `<a href="#" class="city-link inline" data-open-p="${owner}" ` +
      `data-open-c="${cityId}">${c.name}</a>`;
  }

  // v0.25 (文档 C1): 大陆 - the name links to the continent highlight; the same
  // link clears it again (0xFFFFFFFF is not a continent).
  // v0.27: no more "大陆 N" numbering - the label is the name itself.
  function continentHTML(hash) {
    if (!isContinent(hash)) return "—";
    const h = hash >>> 0;
    return `<a href="#" class="continent-link" data-cont="${h}">${continentLabel(h)}</a>` +
      `<div class="continent-luxuries hidden" data-cont="${h}"></div>`;
  }

  function tileYieldPanel(record) {
    const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    record = record || { status: "unavailable", missing: [L("该回合尚无产出计算结果")], breakdown: [] };
    const partial = record.status === "partial";
    let html = `<div class="sec-title">${partial ? L("已计算产出") : L("单元格产出")}` +
      `${L("<span class=\"note\">（未计灾害额外产出）</span></div>")}`;
    if (record.status !== "unavailable") html += tileYieldGrid(record.yields);
    if ((record.missing || []).length) {
      html += `<div class="tile-yield-note">${record.status === "unavailable" ? L("暂不可用：") : L("尚未完整计算：")}` +
        record.missing.map(esc).join("；") + "</div>";
    }
    if ((record.breakdown || []).length) {
      html += `${L("<div class=\"tile-yield-details\"><div class=\"sec-title\">产出来源</div>")}`;
      const sources = new Map();
      for (const row of record.breakdown) {
        const key = JSON.stringify([row.source, row.sourceType || row.type || row.name || ""]);
        if (!sources.has(key)) sources.set(key, {
          source: row.source, name: row.name || "", yields: {}, notes: new Set(),
        });
        const group = sources.get(key);
        if (row.yield) group.yields[row.yield] = (group.yields[row.yield] || 0) + (Number(row.amount) || 0);
        if (row.note) group.notes.add(row.note);
      }
      const excluded = (group) => !Object.values(group.yields).some((amount) => amount !== 0) &&
        ([...group.notes].some((note) => note.includes(L("不计入"))) || group.source.includes(L("不计入")));
      const groups = [...sources.values()].sort((a, b) => Number(excluded(a)) - Number(excluded(b)));
      for (const group of groups) {
        const numeric = Object.keys(group.yields).length ? tileYieldGrid(group.yields) : "";
        const note = [...group.notes].join("；");
        html += `<div class="tile-yield-source${excluded(group) ? " excluded" : ""}"><span>${esc(group.source)}${group.name ? " · " + esc(group.name) : ""}` +
          `${note ? "（" + esc(note) + "）" : ""}</span>${numeric}</div>`;
      }
      html += "</div>";
    }
    return html;
  }

  // --- city panel ---------------------------------------------------------
  function onCitySelect(ev) {
    openCityPanel(ev.iPlayer, ev.cityId);
  }

  // Find a city by (owner, id); when the city changed hands the same id under a
  // different owner wins, so a turn change keeps showing it ("换主则用新业主").
  function findCity(iPlayer, cityId) {
    const pls = (currentTurn && currentTurn.players) || [];
    const own = pls.find((x) => x.iPlayer === iPlayer);
    const c = own && (own.cities || []).find((x) => x.id === cityId);
    if (c) return { iPlayer: iPlayer, city: c };
    for (const p of pls) {
      const other = (p.cities || []).find((x) => x.id === cityId);
      if (other) return { iPlayer: p.iPlayer, city: other };
    }
    return null;
  }

  function openCityPanel(iPlayer, cityId) {
    if (!currentTurn) return;
    const found = findCity(iPlayer, cityId);
    if (!found) return;
    cityTarget = { iPlayer: found.iPlayer, cityId: cityId };
    renderCityPanel(found.iPlayer, found.city);
    openPanel("city");
    // v0.24: tint the city's own tiles on the map while its panel is open
    if (map) map.setCityHighlight(found.iPlayer, found.city.id);
  }

  function renderCityPanel(iPlayer, c) {
    const p = (currentTurn.players || []).find((x) => x.iPlayer === iPlayer);
    if (!p) return;
    $("city-title").textContent = c.name + " · " + playerName(iPlayer);
    $("city-body").innerHTML = cityPanelHTML(p, c);
    // v0.25: 拥有区域 / 拥有奇观的条目可以跳转到对应格子（v0.26 去掉可见的「↗ 跳转」）
    $("city-body").querySelectorAll("[data-jump-i]").forEach((el) => {
      el.onclick = () => {
        const i = parseInt(el.dataset.jumpI, 10);
        if (!map) return;
        map.centerOnTile(i);
        onSelectTile(i);
      };
    });
  }

  // v0.26: 拖回合 / 换回合后，打开着的城市面板按 (iPlayer, cityId) 用当前 payload
  // 重渲；暂不存在时保留面板和目标，清空内容，之后恢复到同一座城市。
  function refreshCityPanel() {
    if (panels.city.hidden) return;
    const found = cityTarget && findCity(cityTarget.iPlayer, cityTarget.cityId);
    if (!found) {
      $("city-title").textContent = L("城市");
      $("city-body").innerHTML = "";
      if (map) map.setCityHighlight(null, null);
      return;
    }
    cityTarget.iPlayer = found.iPlayer;
    renderCityPanel(found.iPlayer, found.city);
    if (map) map.setCityHighlight(found.iPlayer, found.city.id);
  }

  function cityPanelHTML(p, c) {
    // v0.34: 总督一栏不再只写「晋升 N」，而是列出真正点过的词条名。
    const gov = governorCellHTML(c);
    // v0.24: ``damage`` is damage *taken* (0 = untouched), so show what is left
    const hp = Math.max(0, 200 - (Number(c.damage) || 0));
    let html = `${L("<div class=\"kv\">\n      <div class=\"k\">城市</div><div class=\"v\">")}${c.name}${L("</div>\n      <div class=\"k\">归属</div><div class=\"v\">")}${playerName(p.iPlayer)}${L("</div>\n      <div class=\"k\">人口</div><div class=\"v\">")}${c.population}${L("</div>\n      <div class=\"k\">总督</div><div class=\"v\">")}${gov}${L("</div>\n      <div class=\"k\">血量</div><div class=\"v\">")}${hp}${L(" / 200</div>\n      <div class=\"k\">城墙</div><div class=\"v\">")}${wallText(p.iPlayer, c, c.wallDamage)}${L("</div>\n      <div class=\"k\">宗教</div><div class=\"v\">")}${religionCellHTML(c.religion)}</div>
    </div>`;
    html += ownedResourcesHTML(p, "luxuryResources", L("玩家拥有的奢侈品资源"), false);
    html += `${L("<div class=\"sec-title\">产出</div>")}${yieldGrid(c.yields)}`;
    html += `${L("<div class=\"sec-title\">生产队列</div>")}`;
    const prods = (c.currentProds || []);
    html += prods.length ? prods.map((ph) => {
      const ic = iconOf(ph);
      return `<span class="chip">${ic ? `<img src="${ic}">` : ""}${nameHTML(ph)}</span>`;
    }).join("") : L("<span class='muted'>无</span>");
    // v0.24: districts the city owns (including unfinished / specialized ones
    // such as the aqueduct) with their buildings nested, then its wonders.
    html += `${L("<div class=\"sec-title\">拥有区域</div>")}${cityDistrictsHTML(p, c)}`;
    html += `${L("<div class=\"sec-title\">拥有奇观</div>")}${cityWondersHTML(p, c)}`;
    return html;
  }

  // 城市主流宗教（``city.religion`` 与 ``religions[].symbol`` 同一哈希空间）
  function religionCellHTML(hash) {
    if (hash == null || (hash >>> 0) === 0xFFFFFFFF) {
      return L("<span class='muted'>无主流宗教</span>");
    }
    const ic = iconOf(hash);
    return `<span class="chip">${ic ? `<img src="${ic}" alt="">` : ""}` +
      `${religionName(hash)}</span>`;
  }

  // "type（状态）" chip suffix used by the district / wonder groups
  function districtStatus(d) {
    if (d.built === 0) return `${L("<span class=\"dstat wip\">（建设中）</span>")}`;
    if (d.pillage === 1) return `${L("<span class=\"dstat bad\">（被掠夺）</span>")}`;
    return `${L("<span class=\"dstat\">（已建成）</span>")}`;
  }

  // v0.30: ``pillaged`` is the host city's set of pillaged building hashes; a
  // chip is marked when that building is pillaged even if the district is not
  // (the game pillages one layer at a time - buildings first, district last).
  function buildingChips(list, pillaged) {
    if (!list.length) return L("<span class='muted'>无建筑</span>");
    return list.map((bh) => {
      const ic = iconOf(bh);
      const mark = (pillaged && pillaged.has(bh >>> 0))
        ? `${L("<span class=\"bld-pillaged\">（被掠夺）</span>")}` : "";
      return `<span class="chip">${ic ? `<img src="${ic}">` : ""}${nameHTML(bh)}${mark}</span>`;
    }).join("");
  }

  function cityDistrictsHTML(p, c) {
    const w = currentTurn.width;
    const list = (p.districts || [])
      .filter((d) => d.cityId === c.id && (d.type >>> 0) !== DISTRICT_WONDER)
      .sort((a, b) => {
        const ac = (a.type >>> 0) === DISTRICT_CITY_CENTER ? 0 : 1;
        const bc = (b.type >>> 0) === DISTRICT_CITY_CENTER ? 0 : 1;
        return (ac - bc) || cmpKey([nameOf(a.type)], [nameOf(b.type)]);
      });
    if (!list.length) return L("<span class='muted'>无</span>");
    const pillaged = pillagedBuildingSet(c);
    return list.map((d) => {
      const ic = iconOf(d.type);
      const i = d.y * w + d.x;
      // a wonder tile is listed under 拥有奇观 instead of as a building row
      const bl = builtAt(c, i).filter(
        (bh) => (currentTurn.tiles.wonder[i] >>> 0) !== (bh >>> 0));
      // v0.25: 每条区域都能点开对应格子（跳转 + 选中）
      return `<div class="bld-group jumpable" data-jump-i="${i}" ` +
        `${L("title=\"跳转到 (")}${d.x},${d.y})"><div class="bld-dist">` +
        `${ic ? `<img src="${ic}">` : ""}${nameHTML(d.type)}${districtStatus(d)}` +
        districtAdjacencyHTML(d) +
        `</div>` +
        `<div class="bld-items">${buildingChips(bl, pillaged)}</div></div>`;
    }).join("");
  }

  function cityWondersHTML(p, c) {
    const t = currentTurn.tiles;
    const wonder = t.wonder || [], owner = t.owner || [], cityCol = t.city || [];
    const built = c.built || {};
    const rows = [];
    for (let i = 0; i < wonder.length; i++) {
      const h = wonder[i];
      if ((h >>> 0) === 0xFFFFFFFF) continue;
      if (owner[i] !== p.iPlayer || cityCol[i] !== c.id) continue;
      rows.push({ h: h, done: built[hashStr(h)] !== undefined, i: i });
    }
    if (!rows.length) return L("<span class='muted'>无</span>");
    return rows.map(({ h, done, i }) => {
      const ic = iconOf(h);
      const x = i % currentTurn.width, y = Math.floor(i / currentTurn.width);
      return `<div class="bld-group jumpable" data-jump-i="${i}" ` +
        `${L("title=\"跳转到 (")}${x},${y})"><div class="bld-dist">${ic ? `<img src="${ic}">` : ""}` +
        `${nameHTML(h)}<span class="dstat${done ? "" : " wip"}">（${done ? L("已建成") : L("建造中")}）</span>` +
        `</div></div>`;
    }).join("");
  }

  window.addEventListener("DOMContentLoaded", () => init().catch(error => {
    if (error.name !== "AbortError") setBanner(L("存档加载失败：") + error.message, true);
  }));
})();
