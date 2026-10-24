/* Civ6 hex map renderer (Canvas 2D, no dependencies). */
(function (global) {
  "use strict";
  const L = value => window.Civ6I18n ? window.Civ6I18n.text(value) : value;

  const R = 0.5 / Math.cos(Math.PI / 6); // ~0.57735 (hex radius / width)
  const SQRT = R;
  const MAX_SCALE = 135;
  const MIN_SCALE = MAX_SCALE * 0.2;
  const DEFAULT_SCALE = MAX_SCALE * 0.4;

  const TERRAIN_COLORS = [
    ["GRASS", "#6f9b4a"],
    ["PLAINS", "#a8a24a"],
    ["DESERT", "#e0d08a"],
    ["TUNDRA", "#b9c0b0"],
    ["SNOW", "#eef2f5"],
    ["MOUNTAIN", "#8a8378"],
    ["COAST", "#3f7fb0"], ["OCEAN", "#2b5f8f"], ["LAKE", "#3f7fb0"],
  ];

  const LAYERS = [
    ["terrain", "\u5730\u5f62"], ["grid", "六边形边界"],
    ["feature", "\u5730\u8c8c"], ["owner", "\u5f52\u5c5e"],
    ["improvement", "\u6539\u826f"],
    // v0.31: 核污染标记（每格一个「剩余回合」的绿色三叶符号），可单独开关
    ["fallout", "\u6c61\u67d3"],
    ["road", "\u9053\u8def"],
    ["district", "\u533a\u57df/\u57ce\u5e02"], ["resource", "\u8d44\u6e90"],
    ["yield", "产出"],
    ["unit", "\u5355\u4f4d"], ["river", "\u6cb3\u6d41"], ["fog", "\u8ff7\u96fe"],
  ];

  // hex vertices V0..V5 (screen space, y down): V0 top, V1 upper-right,
  // V2 lower-right, V3 bottom, V4 lower-left, V5 upper-left.
  // River mask bits: 0=NE(V0-V1) 1=E(V1-V2) 2=SE(V2-V3)
  //                  3=SW(V3-V4) 4=W(V4-V5) 5=NW(V5-V0)   (upstream order)
  const RIVER_EDGE = [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 0]];
  // Border (iLine) bit order is 0=SE 1=E 2=NE 3=NW 4=W 5=SW -> RIVER_EDGE index
  const BORDER_EDGE = [2, 1, 0, 5, 4, 3];
  // neighbour offset (dx, dy) per border bit for even rows (upstream
  // ComputeCityLine); on odd rows dx +1 whenever dy != 0.
  const BORDER_OFFSET = [[0, -1], [1, 0], [0, 1], [-1, 1], [-1, 0], [-1, -1]];

  const RIVER_OUTER = "rgba(62,48,10,.8)";
  const RIVER_INNER = "rgba(30,90,130,.8)";

  const NONE = 0xFFFFFFFF;
  const CONTINENT_HUES = [35, 280, 100, 10, 235, 60, 325, 145];
  const PLOT_YIELD_ICONS = [
    [619730924, "Food"], [3139030538, "Production"], [3076612938, "Gold"],
    [981596331, "Science"], [3946796520, "Culture"], [2131725942, "Faith"],
  ];
  const DISTRICT_WONDER = 0x62F1B509;
  const ADJACENCY_ICONS = {
    619730924: "Food.png", 3139030538: "Production.png", 3076612938: "gold.png",
    981596331: "Science.png", 3946796520: "Culture.png", 2131725942: "Faith.png",
  };

  // --- v0.25 routes (``tiles.road``) ---------------------------------------
  // ``road`` is the game's *zero-based* ``Routes`` index, not a level:
  // 0 = ancient road / 1 = medieval / 2 = industrial / 3 = modern /
  // 4 = railroad (Gathering Storm only); 255 = no route at all.  A city centre
  // carries route 0 from the turn it is founded, so 0 has to be drawn (see
  // PLAN A4 for the save-file evidence).  ``roadLvl`` is a constant per route
  // (0/1/4/5/0) and must never be used as a level.
  const ROAD_NONE = 255;
  const ROAD_WIDTH = 0.06;                   // x scale, matching the river nib
  // Upstream Viewer.cpp ships ``roadColors[4]`` (it predates railroads);
  // indices 0-3 are those four, brightened a step, and 4 is the added
  // railroad tone.  Railroads deliberately break the light-to-light ramp:
  // they are dark steel grey so the sleeper pattern reads as rails.
  const ROAD_COLORS = [
    "rgba(45,80,126,.92)",     // 0 远古时代道路
    "rgba(112,134,160,.92)",   // 1 古典时代道路
    "rgba(172,182,194,.92)",   // 2 工业时代道路
    "rgba(228,228,228,.92)",   // 3 现代道路
    "rgba(72,78,90,.95)",      // 4 铁路 (unused for the rails themselves, v0.26)
  ];
  const ROAD_FALLBACK = ROAD_COLORS.length - 1;
  // v0.26 铁路: a white base line with equal-length black dashes on top (the
  // sleeper pattern was too fine to read at low zoom, and the dark steel line
  // vanished against dark terrain).
  const RAIL_WHITE = "#f4f4f4";
  const RAIL_BLACK = "#15191f";
  const RAIL_DASH = 0.085;                   // dash length = gap length, x scale

  // city centre HP (walls are shown relative to it, see ``_wallInfo``)
  const CITY_CENTER_HP = 200;

  // v0.21 unit icons: one icon per (category, owner) group.  Order follows the
  // in-game stacking slots; offsets come from the upstream Viewer.cpp
  // ``groupPos`` table (tile coordinates, divided by 180 -> fraction of width).
  // v0.29: "air" is a front-end only slot (aircraft keep the military category
  // in the payload); it sorts last so a flight never displaces the ground units.
  const CAT_ORDER = ["mil", "civ", "sup", "trade", "rel", "air"];
  const GROUP_POS = [
    [0, 0],
    [-40, 0, 40, 0],
    [-40, -20, 40, -20, 0, 40],
    [-40, -20, 40, -20, -40, 40, 40, 40],
    [-40, -20, 40, -20, -40, 40, 40, 40, 0, 80],
    [-40, -20, 40, -20, -40, 40, 40, 40, -40, 80, 40, 80],
  ];
  const TINT_SIZE = 48;      // internal silhouette resolution (px)
  const TINT_OFF = 2;        // outline offset in the silhouette canvas (px)

  function terrainKey(type) {
    let t = (type || "").toUpperCase();
    if (t.endsWith("_MOUNTAIN")) return "MOUNTAIN";
    if (t.endsWith("_HILLS")) t = t.slice(0, -6);
    return t;
  }

  // ``unit.army``: 0 / -1 = single unit, 1 = corps / fleet, 2 = army / armada
  function armyNorm(army) { return army === 1 ? 1 : (army === 2 ? 2 : 0); }

  // stars drawn above the icon: corps/fleet -> two, army/armada -> three,
  // single unit -> none (``army`` already normalised to 0/1/2)
  function starCount(army) { return army ? army + 1 : 0; }

  function terrainColor(type) {
    const t = terrainKey(type);
    for (const [key, col] of TERRAIN_COLORS) {
      if (t.indexOf(key) >= 0) return col;
    }
    return "#557";
  }

  function HexMap(canvas, opts) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.scale = DEFAULT_SCALE;
    this.camX = 0; this.camY = 0;
    this.dpr = window.devicePixelRatio || 1;
    this.payload = null;
    this.meta = null;      // {names, players, wrapX, cities, buildingDistrict,
                           //  wallDefense, buildingCost}
    this.width = 0; this.height = 0;
    this.wrapX = false;
    this.layers = {};
    for (const [k] of LAYERS) this.layers[k] = true;
    this.layers.yield = false;
    this.fog = { enabled: false, player: null };
    this.selected = -1;
    this.hover = -1;
    this.images = new Map();
    this._tintCache = new Map();
    this._starCache = new Map();
    this._greyCache = new Map();   // v0.36 greyed building textures
    this._gridlessCache = new Map(); // terrain / feature textures without baked-in rims
    this._badgeCache = new Map();  // v0.36 hammer / flame tile badges
    this._falloutCache = null;   // v0.31 cleaned-up fallout marker bitmap
    this._cityRects = [];
    this._linesFor = null; this._linesCache = null;
    // v0.39: 不支持的存档（黑名单 MOD / 结社 / 垄断玩法）——见 drawUnsupported
    this.unsupported = null;
    this.cityHighlight = null;   // {iPlayer, cityId} - highlighted city range
    this.continentHighlight = null;   // continent hash (v0.25 B2)
    this.searchHits = null;           // Set<tile index> (v0.25 B3)
    this._hoverCity = null;           // "iPlayer:cityId" of the hovered bar (B4)
    this._luxFor = null; this._lux = null;   // luxury-resource lookup cache
    this._continentsFor = null; this._continents = null;
    // v0.26: ``view`` fires after every paint (and camera change) so the
    // navigation canvas can follow the visible world rectangle.
    this._handlers = { select: [], hover: [], cityselect: [], view: [] };
    this._bind();
  }

  HexMap.prototype.on = function (evt, cb) { this._handlers[evt].push(cb); };
  HexMap.prototype._emit = function (evt, arg) { this._handlers[evt].forEach((f) => f(arg)); };

  HexMap.prototype.resetReplay = function () {
    this.payload = null; this.meta = null; this.unsupported = null;
    this.width = 0; this.height = 0; this.wrapX = false;
    this.selected = -1; this.hover = -1; this._hoverCity = null;
    this.cityHighlight = null; this.continentHighlight = null; this.searchHits = null;
    this.fog.player = null;
    this._cityRects = []; this._linesFor = null; this._linesCache = null;
    this._luxFor = null; this._lux = null;
    this._continentsFor = null; this._continents = null;
    this._builtByCity = new Map(); this._districtByTile = new Map();
    this._fitted = false; this._fittedOnce = false;
    this.draw();
  };

  HexMap.prototype.setData = function (payload, meta) {
    this.unsupported = null;      // v0.39: 回到正常存档，撤掉那个叉
    this.payload = payload;
    this.meta = meta || this.meta;
    this.width = payload.width; this.height = payload.height;
    this.wrapX = !!(this.meta && this.meta.wrapX);
    // search hits belong to the turn they were computed on; app.js re-runs the
    // query after ``setData`` (PLAN B3/C4)
    this.searchHits = null;
    this._linesFor = null; this._linesCache = null;
    this._continentsFor = null; this._continents = null;
    this._indexBuilt();
    if (!this._fitted) { this.centerView(); this._fitted = true; }
    this.draw();
  };

  // v0.23: city ``built`` is ``{building hash: tile index}``; index those maps
  // by ``iPlayer:cityId`` and record which district sits on each tile so
  // wonders / buildings can be placed (and dimmed) exactly.
  HexMap.prototype._indexBuilt = function () {
    this._builtByCity = new Map();
    this._districtByTile = new Map();
    const pls = this.payload.players || [];
    for (const pl of pls) {
      for (const c of (pl.cities || [])) {
        this._builtByCity.set(pl.iPlayer + ":" + c.id, c.built || {});
      }
      for (const d of (pl.districts || [])) {
        const i = d.y * this.width + d.x;
        const prev = this._districtByTile.get(i);
        const built = Number(d.built) || 0;
        // a real district wins over the synthetic DISTRICT_WONDER marker
        if (!prev || (prev.type >>> 0) === DISTRICT_WONDER) {
          this._districtByTile.set(i, { type: d.type >>> 0, pillage: d.pillage,
                                        // v0.36: 建造中的区域（``built === 0``）要在
                                        // 地图上盖「锤子」角标，所以这一位也留下来
                                        built: built,
                                        adjacency: d.adjacency,
                                        iPlayer: pl.iPlayer, cityId: d.cityId });
          continue;
        }
        if (d.pillage === 1) prev.pillage = 1;
        // a built duplicate outranks an unbuilt one on the same tile
        if (built) prev.built = built;
      }
    }
  };

  // built map of the city owning tile ``i`` (via owner + city columns)
  HexMap.prototype._builtOfTile = function (i) {
    const tiles = this.payload.tiles;
    const iPlayer = tiles.owner[i], cityId = tiles.city[i];
    if (iPlayer == null || iPlayer < 0 || cityId == null || cityId < 0) return null;
    return this._builtByCity.get(iPlayer + ":" + cityId) || null;
  };
  HexMap.prototype.worldW = function () { return this.width + 0.5; };

  HexMap.prototype.fit = function () {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const worldW = this.worldW(), worldH = (this.height - 1) * R * 1.5 + 2 * R;
    // Docked panels are only honoured here - the map itself never
    // resizes when a panel is shown, hidden, dragged or resized (``padding`` is
    // set by app.js right before an explicit fit).
    const pad = this.padding || { left: 0, right: 0 };
    const vw = Math.max(80, w - (pad.left || 0) - (pad.right || 0));
    const vh = Math.max(80, h - (pad.bottom || 0));
    const sx = vw / worldW, sy = vh / worldH;
    this.scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, Math.min(sx, sy) * 0.96));
    this.centerView();
  };

  // Start a new replay at the current zoom, centred between the docked panels.
  HexMap.prototype.centerView = function () {
    const worldW = this.worldW(), worldH = (this.height - 1) * R * 1.5 + 2 * R;
    const pad = this.padding || { left: 0, right: 0 };
    // centre the world inside the *uncovered* strip, not the whole canvas
    this.camX = worldW / 2 - 0.25 - ((pad.left || 0) - (pad.right || 0)) / (2 * this.scale);
    this.camY = worldH / 2 + (pad.bottom || 0) / (2 * this.scale);
    this._wrapCam();
    this.draw();
  };

  // World rectangle currently visible on the canvas (v0.26 navigation box).
  HexMap.prototype.viewRect = function () {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const a = this.toWorld(0, 0), b = this.toWorld(w, h);
    const worldW = this.worldW(), worldH = (this.height - 1) * R * 1.5 + 2 * R;
    return {
      x0: Math.max(0, Math.min(a.wx, b.wx)),
      y0: Math.max(0, Math.min(a.wy, b.wy)),
      x1: Math.min(worldW, Math.max(a.wx, b.wx)),
      y1: Math.min(worldH, Math.max(a.wy, b.wy)),
      worldW: worldW, worldH: worldH,
    };
  };

  // Navigation-canvas neighbour: move the camera to a world point (the nav
  // canvas reports ``wx``/``wy``) and repaint.
  HexMap.prototype.lookAt = function (wx, wy) {
    if (!this.payload) return;
    this.camX = wx; this.camY = wy;
    this._wrapCam();
    this.draw();
  };

  HexMap.prototype._wrapCam = function () {
    if (!this.wrapX) return;
    const W = this.worldW();
    this.camX = ((this.camX % W) + W) % W;
  };

  HexMap.prototype.center = function (i) {
    const x = i % this.width, y = (i / this.width) | 0;
    const x0 = (y % 2 === 0) ? x : x + 0.5;
    const y0 = y * R * 1.5;
    const worldH = (this.height - 1) * R * 1.5 + 2 * R;
    return { cx: x0, cy: worldH - R - y0 };
  };

  HexMap.prototype.toScreen = function (cx, cy) {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    return { sx: (cx - this.camX) * this.scale + w / 2,
             sy: (cy - this.camY) * this.scale + h / 2 };
  };
  HexMap.prototype.toWorld = function (sx, sy) {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    return { wx: (sx - w / 2) / this.scale + this.camX,
             wy: (sy - h / 2) / this.scale + this.camY };
  };

  HexMap.prototype.visible = function (p, w, h) {
    const m = this.scale * 1.5;
    return !(p.sx < -m || p.sy < -m || p.sx > w + m || p.sy > h + m);
  };

  // Screen positions for a tile: with wrapX enabled the tile is drawn up to
  // three times (x, x-width, x+width) so the left/right seam wraps.
  HexMap.prototype.screensOf = function (i, w, h) {
    const c = this.center(i);
    const out = [];
    const offs = this.wrapX ? [-1, 0, 1] : [0];
    for (const k of offs) {
      const p = this.toScreen(c.cx + k * this.width, c.cy);
      if (this.visible(p, w, h)) out.push(p);
    }
    return out;
  };

  HexMap.prototype.nearest = function (sx, sy) {
    const { wx, wy } = this.toWorld(sx, sy);
    const worldH = (this.height - 1) * R * 1.5 + 2 * R;
    const W = this.width;
    const yGuess = (worldH - R - wy) / (R * 1.5);
    let xg = wx;
    if (this.wrapX) xg = ((xg % W) + W) % W;
    let best = -1, bestD = Infinity;
    for (let dy = -2; dy <= 2; dy++) {
      const y = Math.round(yGuess) + dy;
      if (y < 0 || y >= this.height) continue;
      for (let dx = -2; dx <= 2; dx++) {
        let x = Math.round(xg) + dx;
        if (this.wrapX) x = ((x % W) + W) % W;
        else if (x < 0 || x >= W) continue;
        const c = this.center(y * W + x);
        let ddx = c.cx - wx;
        if (this.wrapX) ddx -= Math.round(ddx / W) * W;
        const ddy = c.cy - wy;
        const d = ddx * ddx + ddy * ddy;
        if (d < bestD) { bestD = d; best = y * W + x; }
      }
    }
    return best;
  };

  HexMap.prototype.centerOnTile = function (i, select = true) {
    const c = this.center(i);
    this.camX = c.cx; this.camY = c.cy;
    this._wrapCam();
    this.selected = i;
    this.draw();
    if (select) this._emit("select", i);
  };

  HexMap.prototype._img = function (url) {
    if (!url) return null;
    let img = this.images.get(url);
    if (!img) {
      img = new Image();
      img.onload = () => this._scheduleDraw();
      img.src = url;
      this.images.set(url, img);
    }
    return img.complete && img.naturalWidth ? img : null;
  };

  // The source terrain and feature PNGs already contain a dark hexagonal rim.
  // Hiding the canvas stroke alone leaves that rim visible. Extend the nearby
  // interior pixels across the rim, keeping the rest of the texture unchanged.
  HexMap.prototype._tileTexture = function (url) {
    const img = this._img(url);
    if (!img || this.layers.grid) return img;
    let cv = this._gridlessCache.get(url);
    if (cv) return cv;
    cv = document.createElement("canvas");
    const w = cv.width = img.naturalWidth, h = cv.height = img.naturalHeight;
    const c = cv.getContext("2d");
    c.drawImage(img, 0, 0);
    const rec = c.getImageData(0, 0, w, h);
    const src = new Uint8ClampedArray(rec.data), dst = rec.data;
    // The rims are 3–5 pixels wide on the bundled ~186×215 textures.
    const inner = 0.93;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const nx = (x + 0.5 - w / 2) / (w / 2);
        const ny = (y + 0.5 - h / 2) / (h / 2);
        const radius = Math.max(Math.abs(nx), Math.abs(ny) + Math.abs(nx) / 2);
        const k = (y * w + x) * 4;
        if (radius > 1) { dst[k + 3] = 0; continue; }
        if (radius <= inner) continue;
        const ratio = inner / radius;
        const ix = Math.min(w - 1, Math.max(0, Math.floor(w / 2 + nx * ratio * w / 2)));
        const iy = Math.min(h - 1, Math.max(0, Math.floor(h / 2 + ny * ratio * h / 2)));
        const j = (iy * w + ix) * 4;
        for (let ch = 0; ch < 4; ch++) dst[k + ch] = src[j + ch];
      }
    }
    c.putImageData(rec, 0, 0);
    this._gridlessCache.set(url, cv);
    return cv;
  };

  // coalesce redraws so a burst of icon onload events paints once per frame
  HexMap.prototype._scheduleDraw = function () {
    if (this._drawPending) return;
    this._drawPending = true;
    const run = () => { this._drawPending = false; this.draw(); };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(run);
    else setTimeout(run, 16);
  };
  HexMap.prototype.iconURL = function (hash) {
    const info = this.nameInfo(hash);
    return info && info.icon ? "/assets/icons/" + info.icon : null;
  };
  // ``district/<stem>.png`` -> grey variant path (built==0 / pillaged).
  HexMap.prototype._greyURL = function (url) {
    if (!url) return null;
    return url.replace("/district/", "/district/GREY/");
  };

  HexMap.prototype.hexPath = function (ctx, sx, sy, s) {
    const r = SQRT * s, half = 0.5 * s;
    ctx.beginPath();
    ctx.moveTo(sx, sy - r);
    ctx.lineTo(sx + half, sy - r / 2);
    ctx.lineTo(sx + half, sy + r / 2);
    ctx.lineTo(sx, sy + r);
    ctx.lineTo(sx - half, sy + r / 2);
    ctx.lineTo(sx - half, sy - r / 2);
    ctx.closePath();
  };

  // vertices for one tile in screen pixels
  HexMap.prototype.vertices = function (sx, sy, s) {
    const r = SQRT * s, half = 0.5 * s;
    return [
      [sx, sy - r], [sx + half, sy - r / 2], [sx + half, sy + r / 2],
      [sx, sy + r], [sx - half, sy + r / 2], [sx - half, sy - r / 2],
    ];
  };

  function roundRect(ctx, x, y, w, h, r) {
    r = Math.min(r, h / 2, w / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  HexMap.prototype.draw = function () {
    const cv = this.canvas, ctx = this.ctx;
    const w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== w * this.dpr || cv.height !== h * this.dpr) {
      cv.width = w * this.dpr; cv.height = h * this.dpr;
    }
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    // v0.39: 不支持的存档没有可画的东西 —— 只在画布中间画个叉 + 说明
    if (this.unsupported) { this.drawUnsupported(w, h); return; }
    if (!this.payload) return;
    this._wrapCam();
    this._cityRects = [];
    this.drawTerrain();
    // 泛滥平原等地貌贴图带有不透明底色和格边，必须先画，避免覆盖河流与桥梁。
    this.drawFeatures();
    // 河流先于道路绘制，让跨河桥梁盖在水面上。
    this.drawRivers();
    // 道路压在地形、地貌与河流之上；区域 / 城市 / 改良 / 资源仍在道路上面。
    // 道路是画在格心之间的长线，原来压在图标上时，白色现代道路横穿地块会盖住
    // 区域与改良图标，太遮挡视线。
    this.drawRoads();
    this.drawContinentHighlight();
    this.drawCityHighlight();
    // v0.37: 格边上的线（河流、归属边界、同城虚线）都在图标层下方。
    // 区域与改良的贴图几乎铺满整格，这些线原来压在图标外缘上（线沿格边走，正好把
    // 图标切掉一圈）；三者之间的先后保持不变，所以河流照样不会盖住归属边界。
    this.drawBorders();
    this.drawCityDashes();
    this.drawImprovements();
    this.drawFallout();
    this.drawResources();
    this.drawDistricts();
    this.drawBuildings();
    this.drawWonders();
    this.drawCities();
    this.drawUnits();
    this.drawPlotYields();
    this.drawAdjacency();
    this.drawSearchHighlight();
    this.drawSelectedHover();
    this.drawContinentLabels();
    this.drawFog();
    this._emit("view", this.viewRect());
  };
  // --- v0.39: 不支持的存档（黑名单 MOD / 结社 / 垄断玩法） -----------------
  // 判定的来源是后端 ``static_info.unsupported``；这类存档一个回合都没解析，
  // 所以画布上不画地图，只在正中画一个大叉 + 说明文字。
  HexMap.prototype.setUnsupported = function (info) {
    this.unsupported = info || {};
    this.payload = null;
    this.selected = -1; this.hover = -1;
    this._cityRects = []; this._linesFor = null; this._linesCache = null;
    this.searchHits = null;
    this.draw();
  };

  // 按画布宽度折行（中文按字切，够用）：返回真正要画的每一行
  function wrapText(ctx, text, maxWidth) {
    const out = [];
    let line = "";
    for (const ch of Array.from(String(text || ""))) {
      const next = line + ch;
      if (line && ctx.measureText(next).width > maxWidth) { out.push(line); line = ch; }
      else { line = next; }
    }
    if (line) out.push(line);
    return out;
  }

  HexMap.prototype.drawUnsupported = function (w, h) {
    const ctx = this.ctx, info = this.unsupported || {};
    ctx.save();
    // 背景跟 .stage 同色：画布已清空，不留上一局的残影
    ctx.fillStyle = "#0b0e13";
    ctx.fillRect(0, 0, w, h);
    const cx = w / 2, cy = h / 2;
    // 叉的大小跟着画布走（画布很大的时候别只剩一小点）
    const r = Math.max(46, Math.min(w, h) * 0.15);
    ctx.strokeStyle = "#d9534f";
    ctx.lineWidth = Math.max(6, r * 0.16);
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(cx - r, cy - r); ctx.lineTo(cx + r, cy + r);
    ctx.moveTo(cx + r, cy - r); ctx.lineTo(cx - r, cy + r);
    ctx.stroke();

    const font = "-apple-system, 'Segoe UI', 'Microsoft YaHei', system-ui, sans-serif";
    const maxWidth = Math.max(160, w - 80);
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    const titleSize = Math.max(16, Math.min(26, Math.round(w / 34)));
    ctx.font = `600 ${titleSize}px ${font}`;
    ctx.fillStyle = "#f2f4f8";
    let y = cy + r + titleSize;
    for (const line of wrapText(ctx, info.title || L("存档不支持"), maxWidth)) {
      ctx.fillText(line, cx, y);
      y += titleSize + 8;
    }
    const bodySize = Math.max(13, Math.min(18, Math.round(w / 48)));
    ctx.font = `${bodySize}px ${font}`;
    ctx.fillStyle = "#b9c1cf";
    y += 2;
    for (const raw of (info.lines || [])) {
      for (const line of wrapText(ctx, raw, maxWidth)) {
        ctx.fillText(line, cx, y);
        y += bodySize + 8;
      }
    }
    ctx.restore();
  };

  // --- layers -------------------------------------------------------------
  HexMap.prototype.drawTerrain = function () {
    if (!this.layers.terrain) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale, r = SQRT * s;
    const terrain = this.payload.tiles.terrain;
    for (let i = 0; i < terrain.length; i++) {
      const info = this.nameInfo(terrain[i]);
      const img = this._tileTexture(this.iconURL(terrain[i]));
      for (const p of this.screensOf(i, w, h)) {
        if (img) {
          ctx.drawImage(img, p.sx - s / 2, p.sy - r, s, 2 * r);
        } else {
          this.hexPath(ctx, p.sx, p.sy, s);
          ctx.fillStyle = terrainColor(info && info.type);
          ctx.fill();
        }
        if (this.layers.grid) {
          this.hexPath(ctx, p.sx, p.sy, s);
          ctx.strokeStyle = "rgba(0,0,0,.25)"; ctx.lineWidth = 1; ctx.stroke();
        }
      }
    }
  };

  HexMap.prototype.drawFeatures = function () {
    if (!this.layers.feature) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale, r = SQRT * s;
    const feature = this.payload.tiles.feature;
    for (let i = 0; i < feature.length; i++) {
      const f = feature[i];
      if ((f >>> 0) === NONE) continue;
      const img = this._tileTexture(this.iconURL(f));
      if (!img) continue;
      for (const p of this.screensOf(i, w, h)) {
        ctx.drawImage(img, p.sx - s / 2, p.sy - r, s, 2 * r);
      }
    }
  };

  // v0.24: while a city is selected, tint every tile that city owns so its
  // territory is obvious at a glance (the city center tile included).
  HexMap.prototype.setCityHighlight = function (iPlayer, cityId) {
    this.cityHighlight = (iPlayer == null || cityId == null)
      ? null : { iPlayer: iPlayer, cityId: cityId };
    if (this.payload) this.draw();
  };

  HexMap.prototype.drawCityHighlight = function () {
    const hl = this.cityHighlight;
    if (!hl || !this.layers.owner) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    const tiles = this.payload.tiles;
    const fill = this._alpha(this.playerColor(hl.iPlayer), 0.38);
    ctx.save();
    ctx.lineWidth = Math.max(1.6, s * 0.075);
    ctx.strokeStyle = "rgba(255,255,255,.95)";
    for (let i = 0; i < tiles.city.length; i++) {
      if (tiles.city[i] !== hl.cityId || tiles.owner[i] !== hl.iPlayer) continue;
      for (const p of this.screensOf(i, w, h)) {
        this.hexPath(ctx, p.sx, p.sy, s);
        ctx.fillStyle = fill;
        ctx.fill();
        ctx.stroke();
      }
    }
    ctx.restore();
  };

  // Selecting a continent opens the continent lens: tinted regions, outer
  // boundaries and names for all continents; selected luxury tiles stay pink.
  // ``hash`` is a ``tiles.continent`` value; 0xFFFFFFFF (open water, no
  // continent) never matches because no link is offered for it.
  HexMap.prototype.setContinentHighlight = function (hash) {
    this.continentHighlight = (hash == null) ? null : (hash >>> 0);
    if (this.payload) this.draw();
  };

  HexMap.prototype._luxurySet = function () {
    const arr = this.meta && this.meta.luxuryResources;
    if (!arr || !arr.length) return null;
    if (this._luxFor !== arr) {
      this._luxFor = arr;
      this._lux = new Set(arr.map((v) => v >>> 0));
    }
    return this._lux;
  };

  // Water luxuries in lakes share the continent hash but do not belong to its
  // land luxury pool. Keep all matching tiles highlighted; exclude water only
  // from the distinct types listed in the tile panel.
  HexMap.prototype.continentLuxuryResources = function (hash) {
    const lux = this._luxurySet();
    if (hash == null || (hash >>> 0) === 0xFFFFFFFF || !this.payload || !lux) return [];
    const tiles = this.payload.tiles, result = new Set();
    const cont = tiles.continent || [], res = tiles.resource || [];
    const water = tiles.water || [], terrain = tiles.terrain || [];
    const names = (this.meta && this.meta.names) || {};
    for (let i = 0; i < cont.length; i++) {
      if ((cont[i] >>> 0) !== (hash >>> 0) || res[i] == null || !lux.has(res[i] >>> 0)) continue;
      const info = names[String(terrain[i] >>> 0)];
      if (water[i] === 1 || (info && (info.type === "TERRAIN_COAST" || info.type === "TERRAIN_OCEAN"))) continue;
      result.add(res[i] >>> 0);
    }
    return [...result];
  };

  HexMap.prototype._continentNeighbor = function (i, k) {
    // The legacy owner-border helper always wraps X. Continent boundaries also
    // need to respect maps whose left and right edges do not touch.
    const x = i % this.width, y = (i / this.width) | 0;
    const dx = BORDER_OFFSET[k][0] + (BORDER_OFFSET[k][1] !== 0 && (y & 1) ? 1 : 0);
    if (!this.wrapX && (x + dx < 0 || x + dx >= this.width)) return -1;
    return this.neighborIndex(i, k);
  };

  HexMap.prototype.continentRegions = function () {
    if (this._continentsFor === this.payload && this._continentsWrap === this.wrapX && this._continents) return this._continents;
    const cont = this.payload.tiles.continent || [];
    const hashes = [...new Set(cont.filter(h => h != null && (h >>> 0) !== NONE).map(h => h >>> 0))].sort((a, b) => a - b);
    const colors = new Map(hashes.map((hash, i) => [hash, CONTINENT_HUES[i % CONTINENT_HUES.length]]));
    const seen = new Uint8Array(cont.length), regions = [];
    for (let i = 0; i < cont.length; i++) {
      if (seen[i] || cont[i] == null || (cont[i] >>> 0) === NONE) continue;
      const hash = cont[i] >>> 0, tiles = [i], edges = [];
      seen[i] = 1;
      for (let j = 0; j < tiles.length; j++) {
        const index = tiles[j];
        for (let k = 0; k < 6; k++) {
          const ni = this._continentNeighbor(index, k);
          if (ni < 0 || cont[ni] == null || (cont[ni] >>> 0) !== hash) edges.push([index, k]);
          else if (!seen[ni]) { seen[ni] = 1; tiles.push(ni); }
        }
      }
      regions.push({ hash, tiles, edges, hue: colors.get(hash) });
    }
    this._continentsFor = this.payload; this._continentsWrap = this.wrapX;
    return this._continents = regions;
  };

  HexMap.prototype.drawContinentHighlight = function () {
    const hl = this.continentHighlight;
    if (hl == null || !this.payload) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    const tiles = this.payload.tiles;
    const res = tiles.resource || [];
    const lux = this._luxurySet();
    const regions = this.continentRegions();
    ctx.save();
    for (const region of regions) {
      const selected = region.hash === hl;
      for (const i of region.tiles) {
        ctx.fillStyle = selected && lux && res[i] != null && lux.has(res[i] >>> 0)
          ? "rgba(255,105,180,.70)" : selected ? "rgba(64,196,210,.30)" : `hsla(${region.hue},65%,65%,.22)`;
        for (const p of this.screensOf(i, w, h)) {
          this.hexPath(ctx, p.sx, p.sy, s);
          ctx.fill();
        }
      }
    }
    // Draw the selected outline last so shared edges retain its emphasis.
    ctx.lineJoin = "round";
    for (const selected of [false, true]) for (const region of regions) {
      if ((region.hash === hl) !== selected) continue;
      ctx.beginPath();
      for (const [i, k] of region.edges) for (const p of this.screensOf(i, w, h)) {
        const v = this.vertices(p.sx, p.sy, s), [a, b] = RIVER_EDGE[BORDER_EDGE[k]];
        ctx.moveTo(v[a][0], v[a][1]); ctx.lineTo(v[b][0], v[b][1]);
      }
      ctx.strokeStyle = "rgba(20,25,35,.80)"; ctx.lineWidth = Math.max(2.5, s * .09); ctx.stroke();
      ctx.strokeStyle = selected ? "rgba(255,255,255,.95)" : `hsl(${region.hue},65%,72%)`;
      ctx.lineWidth = Math.max(selected ? 1.8 : 1.2, s * (selected ? .045 : .03)); ctx.stroke();
    }
    ctx.restore();
  };

  HexMap.prototype.drawContinentLabels = function () {
    if (this.continentHighlight == null || !this.payload) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const size = Math.max(12, Math.min(22, this.scale * .48));
    const pad = this.padding || {};
    const left = pad.left || 0, right = w - (pad.right || 0), bottom = h - (pad.bottom || 0);
    const occupied = [];
    ctx.save(); ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.lineJoin = "round"; ctx.lineWidth = 3.5;
    // Reserve label space for the selected continent first.
    const regions = this.continentRegions().slice().sort((a, b) =>
      Number(b.hash === this.continentHighlight) - Number(a.hash === this.continentHighlight));
    for (const region of regions) {
      const selected = region.hash === this.continentHighlight;
      const info = this.nameInfo(region.hash);
      const text = ((info && info.name && !info.name.startsWith("0x")) ? info.name : L("大陆")) + (selected ? L("（已选）") : "");
      ctx.font = `${selected ? 700 : 600} ${size}px "Microsoft YaHei", sans-serif`;
      const labelWidth = ctx.measureText(text).width + 12, labelHeight = size + 10;
      // Place names on visible continent tiles, rather than a bounding-box
      // center that may lie in the sea. Wrapped copies get separate labels.
      const copies = new Map();
      for (const i of region.tiles) {
        const c = this.center(i), base = this.toScreen(c.cx, c.cy);
        for (const p of this.screensOf(i, w, h)) {
          if (p.sx < left + labelWidth / 2 || p.sx > right - labelWidth / 2 || p.sy < labelHeight / 2 || p.sy > bottom - labelHeight / 2) continue;
          const copy = this.wrapX ? Math.round((p.sx - base.sx) / (this.width * this.scale)) : 0;
          if (!copies.has(copy)) copies.set(copy, []);
          copies.get(copy).push(p);
        }
      }
      for (const points of copies.values()) {
        const cx = points.reduce((sum, p) => sum + p.sx, 0) / points.length;
        const cy = points.reduce((sum, p) => sum + p.sy, 0) / points.length;
        points.sort((a, b) => ((a.sx - cx) ** 2 + (a.sy - cy) ** 2) - ((b.sx - cx) ** 2 + (b.sy - cy) ** 2));
        for (const p of points) {
          const box = { x: p.sx - labelWidth / 2, y: p.sy - labelHeight / 2, w: labelWidth, h: labelHeight };
          if (occupied.some(b => box.x < b.x + b.w && box.x + box.w > b.x && box.y < b.y + b.h && box.y + box.h > b.y)) continue;
          ctx.strokeStyle = "rgba(15,22,30,.9)"; ctx.strokeText(text, p.sx, p.sy);
          ctx.fillStyle = selected ? "#ffe08a" : "#f4f7fb"; ctx.fillText(text, p.sx, p.sy);
          occupied.push(box); break;
        }
      }
    }
    ctx.restore();
  };

  // v0.25 (PLAN B3) search highlight: a set of tile indices from the left
  // sidebar.  Independent of selection/hover, drawn just under their rings.
  HexMap.prototype.setSearchHits = function (idSet) {
    const size = idSet ? (idSet.size == null ? idSet.length : idSet.size) : 0;
    this.searchHits = size ? new Set(idSet) : null;
    if (this.payload) this.draw();
  };

  HexMap.prototype.drawSearchHighlight = function () {
    const hits = this.searchHits;
    if (!hits || !this.payload) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    const n = (this.payload.tiles.terrain || []).length;
    ctx.save();
    ctx.lineWidth = Math.max(1.6, s * 0.075);
    ctx.strokeStyle = "rgba(255,214,80,.95)";
    ctx.fillStyle = "rgba(255,214,80,.18)";
    for (const i of hits) {
      if (!(i >= 0 && i < n)) continue;
      for (const p of this.screensOf(i, w, h)) {
        this.hexPath(ctx, p.sx, p.sy, s);
        ctx.fill();
        ctx.stroke();
      }
    }
    ctx.restore();
  };

  // improvements: pillaged (flags bit 1) render at 50% (no marker, v0.23).
  HexMap.prototype.drawImprovements = function () {
    if (!this.layers.improvement) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const arr = this.payload.tiles.improvement;
    const flags = this.payload.tiles.flags || [];
    const s = this.scale;
    for (let i = 0; i < arr.length; i++) {
      const hash = arr[i];
      if (hash === NONE || hash === -1) continue;
      const img = this._img(this.iconURL(hash));
      if (!img) continue;
      const pillaged = (flags[i] & 2) !== 0;
      for (const p of this.screensOf(i, w, h)) {
        const size = s * 0.9;
        ctx.globalAlpha = pillaged ? 0.5 : 0.9;
        ctx.drawImage(img, p.sx - size / 2, p.sy - size / 2, size, size);
        ctx.globalAlpha = 1;
        // v0.36: 被掠夺的改良同样是「半透明」这一档 —— 补一个火，别和建造中混
        if (pillaged) this._drawTileBadge(ctx, "pillage", p.sx, p.sy, s);
      }
    }
  };

  // v0.31 核污染: the original game paints a translucent green disc with a
  // radiation trefoil over every contaminated plot (strategic view and world
  // view alike).  The marker is drawn once into an offscreen canvas and then
  // stamped per tile, so zooming costs one drawImage per tile.
  const FALLOUT_RES = 96;
  const FALLOUT_DISC = "rgba(122,230,104,.55)";
  const FALLOUT_RIM = "rgba(206,255,186,.85)";
  const FALLOUT_INK = "rgba(18,110,44,.95)";

  HexMap.prototype._falloutIcon = function () {
    if (this._falloutCache) return this._falloutCache;
    const R = FALLOUT_RES / 2;
    const cv = document.createElement("canvas");
    cv.width = FALLOUT_RES; cv.height = FALLOUT_RES;
    const c = cv.getContext("2d");
    c.beginPath();
    c.arc(R, R, R * 0.94, 0, Math.PI * 2);
    c.fillStyle = FALLOUT_DISC; c.fill();
    c.lineWidth = Math.max(1, R * 0.06);
    c.strokeStyle = FALLOUT_RIM; c.stroke();
    // three 60° blades (annulus sectors) + the hub = the radiation trefoil
    const inner = R * 0.22, outer = R * 0.74, spread = Math.PI / 6;
    c.fillStyle = FALLOUT_INK;
    for (let k = 0; k < 3; k++) {
      const mid = -Math.PI / 2 + k * 2 * Math.PI / 3;
      c.beginPath();
      c.arc(R, R, outer, mid - spread, mid + spread);
      c.arc(R, R, inner, mid + spread, mid - spread, true);
      c.closePath();
      c.fill();
    }
    c.beginPath();
    c.arc(R, R, inner * 0.62, 0, Math.PI * 2);
    c.fill();
    this._falloutCache = cv;
    return cv;
  };

  HexMap.prototype.drawFallout = function () {
    if (!this.layers.fallout) return;
    const arr = this.payload.tiles.fallout;
    if (!arr || !arr.length) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const icon = this._falloutIcon();
    const size = this.scale * 1.14;
    ctx.globalAlpha = 0.92;
    for (let i = 0; i < arr.length; i++) {
      if (!arr[i]) continue;
      for (const p of this.screensOf(i, w, h)) {
        ctx.drawImage(icon, p.sx - size / 2, p.sy - size / 2, size, size);
      }
    }
    ctx.globalAlpha = 1;
  };

  HexMap.prototype.drawResources = function () {
    if (!this.layers.resource) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const arr = this.payload.tiles.resource;
    const size = this.scale * 0.32;
    for (let i = 0; i < arr.length; i++) {
      const hash = arr[i];
      if (hash === NONE || hash === -1) continue;
      const img = this._img(this.iconURL(hash));
      if (!img) continue;
      for (const p of this.screensOf(i, w, h)) {
        const cx = p.sx - 0.03 * this.scale, cy = p.sy + 0.38 * this.scale;
        ctx.globalAlpha = 0.92;
        ctx.drawImage(img, cx - size / 2, cy - size / 2, size, size);
        ctx.globalAlpha = 1;
      }
    }
  };

  // Plot yield groups fill the bottom row left-to-right before the upper row.
  // Each group is one yield type; 1–4 points are repeated small game glyphs,
  // five points use the large glyph and larger values add a bottom-right total.
  HexMap.prototype.drawPlotYields = function () {
    if (!this.layers.yield) return;
    const records = this.payload.tileYields || [];
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale, cell = s * 0.25, glyph = s * 0.14;
    const visible = this.layers.fog && this.fog.enabled && this.fog.player != null
      ? (this.payload.visibility || {})[this.fog.player] : null;
    ctx.save();
    ctx.textAlign = "right"; ctx.textBaseline = "bottom";
    ctx.font = `bold ${Math.max(8, s * 0.13)}px sans-serif`;
    ctx.lineWidth = Math.max(1.5, s * 0.025);
    ctx.strokeStyle = "rgba(0,0,0,.95)"; ctx.fillStyle = "#fff";
    for (let i = 0; i < records.length; i++) {
      const record = records[i];
      if (!record || record.status === "unavailable" || (visible && !visible[i])) continue;
      const parts = PLOT_YIELD_ICONS.map(([hash, name]) => ({
        name, amount: Number((record.yields || {})[hash]) || 0,
      })).filter((part) => part.amount > 0);
      if (!parts.length) continue;
      for (const pos of this.screensOf(i, w, h)) {
        for (let k = 0; k < parts.length; k++) {
          const part = parts[k], row = Math.floor(k / 3), column = k % 3;
          const count = Math.min(3, parts.length - row * 3);
          const cx = pos.sx + (column - (count - 1) / 2) * cell;
          const cy = pos.sy - s * 0.02 - row * cell;
          const large = part.amount >= 5;
          const img = this._img(`/assets/icons/plot-yield/${part.name}${large ? "Large" : ""}.png`);
          if (!img) continue;
          if (large) {
            const size = cell * 0.9;
            ctx.drawImage(img, cx - size / 2, cy - size / 2, size, size);
          } else {
            const layouts = {
              1: [[0, 0]], 2: [[0, -0.38], [0, 0.38]],
              3: [[0, -0.36], [-0.38, 0.34], [0.38, 0.34]],
              4: [[-0.38, -0.36], [0.38, -0.36], [-0.38, 0.34], [0.38, 0.34]],
            };
            for (const [dx, dy] of layouts[Math.min(4, Math.floor(part.amount))] || layouts[1]) {
              ctx.drawImage(img, cx + dx * glyph - glyph / 2, cy + dy * glyph - glyph / 2, glyph, glyph);
            }
          }
          if (part.amount > 5 || !Number.isInteger(part.amount)) {
            const x = cx + cell * 0.48, y = cy + cell * 0.5;
            const text = String(Math.round(part.amount * 10) / 10);
            ctx.strokeText(text, x, y); ctx.fillText(text, x, y);
          }
        }
      }
    }
    ctx.restore();
  };

  // districts: one icon per placed district (players[].districts), skipped for
  // the synthetic DISTRICT_WONDER marker.
  HexMap.prototype.drawDistricts = function () {
    if (!this.layers.district) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    for (const pl of (this.payload.players || [])) {
      for (const d of (pl.districts || [])) {
        const type = d.type >>> 0;
        if (type === DISTRICT_WONDER) continue;
        const url = this.iconURL(type);
        if (!url) continue;
        // v0.36: 灰 = 建造中（``built === 0``）或地基被掠夺；两者都盖右下角标区分
        // （锤子 / 火）。灰色变体缺失时退回半透明彩色图，角标照样说清状态。
        const building = d.built === 0;
        const ruin = d.pillage === 1;
        const grey = building || ruin;
        const greyURL = this._greyURL(url);
        let img = grey ? (greyURL === url ? this._greyIcon(url) : this._img(greyURL)) : null;
        let alpha = grey ? 1 : 0.95;
        if (!img) { img = this._img(url); if (grey) alpha = 0.45; }
        if (!img) continue;
        for (const p of this.screensOf(d.y * this.width + d.x, w, h)) {
          const size = s;
          ctx.globalAlpha = alpha;
          ctx.drawImage(img, p.sx - size / 2, p.sy - size / 2, size, size);
          ctx.globalAlpha = 1;
          if (grey) {
            this._drawTileBadge(ctx, building ? "build" : "pillage", p.sx, p.sy, s,
                                this._hasAdjacency(d));
          }
        }
      }
    }
  };

  HexMap.prototype._hasAdjacency = function (district) {
    return this.scale >= 28 && district && district.adjacency &&
      Object.values(district.adjacency).some((v) => Number.isFinite(v) && v > 0);
  };

  // A separate pass keeps the badge above building and unit artwork.
  HexMap.prototype.drawAdjacency = function () {
    if (!this.layers.district || this.scale < 28) return;
    const ctx = this.ctx, s = this.scale;
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const vis = this.layers.fog && this.fog.enabled && this.fog.player != null
      ? (this.payload.visibility || {})[String(this.fog.player)] : null;
    const meta = this.meta && this.meta.yieldMeta || {};
    const order = this.meta && this.meta.yieldOrder || Object.keys(ADJACENCY_ICONS).map(Number);
    const fs = Math.max(7, Math.min(16, s * 0.20));
    for (const pl of (this.payload.players || [])) {
      for (const d of (pl.districts || [])) {
        if ((d.type >>> 0) === DISTRICT_WONDER || !this._hasAdjacency(d)) continue;
        const index = d.y * this.width + d.x;
        if (vis && !vis[index]) continue;
        const parts = order.filter((yh) => Number.isFinite(d.adjacency[yh]) && d.adjacency[yh] > 0)
          .map((yh) => ({ yh, text: "+" + d.adjacency[yh] }));
        if (!parts.length) continue;
        ctx.save();
        ctx.font = "600 " + fs + "px sans-serif";
        ctx.textAlign = "left"; ctx.textBaseline = "middle";
        const gap = Math.max(2, fs * 0.25), padding = 3;
        for (const part of parts) part.width = fs + gap + ctx.measureText(part.text).width;
        const badgeW = parts.reduce((sum, part) => sum + part.width, 0) +
          (parts.length - 1) * gap * 2 + padding * 2;
        const badgeH = fs + padding * 2;
        for (const pos of this.screensOf(index, w, h)) {
          const y = pos.sy + s * 0.44;
          let x = pos.sx - badgeW / 2 + padding;
          roundRect(ctx, pos.sx - badgeW / 2, y - badgeH / 2, badgeW, badgeH, 3);
          ctx.fillStyle = "rgba(8,20,32,.92)"; ctx.fill();
          ctx.strokeStyle = "rgba(80,130,165,.85)"; ctx.lineWidth = 1; ctx.stroke();
          for (const part of parts) {
            const img = this._img("/assets/icons/yield/" + ADJACENCY_ICONS[part.yh]);
            if (img) ctx.drawImage(img, x, y - fs / 2, fs, fs);
            ctx.fillStyle = (meta[part.yh] || {}).color || "#4aa3d6";
            ctx.fillText(part.text, x + fs + gap, y);
            x += part.width + gap * 2;
          }
        }
        ctx.restore();
      }
    }
  };

  // v0.35: 一格一栋的贴图尺寸（x scale）——原来同格铺 3×3 个 ``0.24s`` 的小图标，
  // 默认缩放下几乎看不见；现在只有单张 ``0.6s``，仍在六边形内。
  const BUILDING_ICON = 0.6;

  // buildings: a city's ``built`` map places every building on a real tile
  // (v0.23: the map value is the tile index), so the icon lands exactly on the
  // building's tile.  Wonders get a full-tile texture from drawWonders and are
  // skipped here; pillaged buildings are dimmed.
  // v0.30: ``city.pillagedBuildings`` flags them one by one (the game strips a
  // district building by building - the district itself is pillaged last), so
  // the dim follows the building, not its district.  A payload without the list
  // falls back to the host district's ``pillage`` flag.
  // v0.35: 一格只贴一栋（挑哪一栋见 ``_pickBuilding``），尺寸 ``BUILDING_ICON``。
  // v0.36: 被掠夺时改成贴「被掠夺的最低级建筑」（见 ``_pickLowest``），且
  // 区域本体也被掠夺时整张转灰；这两种状态都盖右下角标（火），由区域层或本层画。
  HexMap.prototype.drawBuildings = function () {
    if (!this.layers.district) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    const wonder = this.payload.tiles.wonder || [];
    for (const pl of (this.payload.players || [])) {
      for (const city of (pl.cities || [])) {
        const built = city.built || {};
        const pil = Array.isArray(city.pillagedBuildings)
          ? new Set(city.pillagedBuildings.map((x) => x >>> 0)) : null;
        // the city's own tile takes the wall rule in ``_pickBuilding``
        const center = city.y * this.width + city.x;
        const groups = new Map();
        for (const bh in built) {
          const i = built[bh];
          if (typeof i !== "number" || i < 0 || i >= wonder.length) continue;
          // an entry that *is* the tile's wonder is already drawn whole
          if ((wonder[i] >>> 0) === (parseInt(bh, 10) >>> 0)) continue;
          let list = groups.get(i);
          if (!list) { list = []; groups.set(i, list); }
          list.push(parseInt(bh, 10));
        }
        for (const [i, list] of groups) {
          const dist = this._districtByTile.get(i);
          const distPillaged = !!(dist && dist.pillage === 1);
          // v0.36: 区域本体被掠夺 / 建造中时，角标由区域层画（一格只盖一个）
          const tileBadge = !!(dist && (dist.built === 0 || dist.pillage === 1));
          // v0.36: 掠夺是从这一格最上面那栋往下剥的，所以贴「被掠夺的最低级建筑」——
          // 大学被踩时贴大学，大学修好后回到实验室。老 payload 没有
          // ``pillagedBuildings`` 时，宿主区域被掠夺即视为这一格被掠夺。
          const hurt = pil ? list.filter((h) => pil.has(h >>> 0))
                           : (distPillaged ? list : []);
          // 地基也被掠夺 → 整张转灰（角标仍是「火」，说明是掠夺不是建造中）
          const grey = distPillaged;
          const hash = hurt.length ? this._pickLowest(hurt)
                     : (grey ? this._pickLowest(list)
                             : this._pickBuilding(list, i === center));
          const url = this.iconURL(hash);
          const img = grey ? this._greyIcon(url) : this._img(url);
          if (!img) continue;
          const alpha = (grey || !hurt.length) ? 0.92 : 0.45;
          const size = s * BUILDING_ICON;
          for (const p of this.screensOf(i, w, h)) {
            ctx.globalAlpha = alpha;
            ctx.drawImage(img, p.sx - size / 2, p.sy - size / 2, size, size);
            ctx.globalAlpha = 1;
            if (hurt.length && !tileBadge) {
              this._drawTileBadge(ctx, "pillage", p.sx, p.sy, s, this._hasAdjacency(dist));
            }
          }
        }
      }
    }
  };

  // v0.35: 同格多栋只贴一栋，贴「最后」那栋：
  //   1) 市中心格上有城墙时，取 ``wall_order`` 最大的一档 —— 城墙是原地升级的，
  //      但存档 / MOD 可能同时留下几档，只画最高等级那张（其余建筑让位）；
  //   2) 否则取造价最大的一栋（``meta.buildingCost``）：市中心以外的建筑几乎
  //      都挂在同一片区域的升级链上（图书馆 90 → 大学 250 → 研究实验室 440），
  //      最贵的那栋就是玩家眼里的「最后那栋」；市中心没有城墙时同样按这条走
  //      （纪念碑 / 粮仓 / 水磨之间没有从属关系，取最贵的即可）；
  //   3) 快照没有造价表时退回列表末位，行为仍然确定。
  HexMap.prototype._pickBuilding = function (list, isCenter) {
    const last = list[list.length - 1];
    if (isCenter) {
      const table = this.meta && this.meta.wallDefense
        && this.meta.wallDefense.buildings;
      let wall = null, order = -Infinity;
      if (table) {
        for (const h of list) {
          const e = table[String(h >>> 0)];
          if (e && (wall === null || e.order > order)) { wall = h; order = e.order; }
        }
      }
      if (wall !== null) return wall;
    }
    const cost = this.meta && this.meta.buildingCost;
    if (cost) {
      let best = last, bestCost = -1;
      for (const h of list) {
        const c = cost[String(h >>> 0)];
        if (typeof c === "number" && c > bestCost) { bestCost = c; best = h; }
      }
      return best;
    }
    return last;
  };

  // v0.36: 一格被掠夺的几栋里挑「最低级」的那栋。造价就是档次（图书馆 90 → 大学
  // 250 → 研究实验室 440），城墙三档 100 / 200 / 300 也一样；快照缺造价表时退回
  // 列表首位，行为仍然确定。
  HexMap.prototype._pickLowest = function (list) {
    if (!list.length) return null;
    const cost = this.meta && this.meta.buildingCost;
    if (!cost) return list[0];
    let best = list[0], bestCost = Infinity;
    for (const h of list) {
      const c = cost[String(h >>> 0)];
      if (typeof c === "number" && c < bestCost) { bestCost = c; best = h; }
    }
    return best;
  };

  // --- v0.36 灰色建筑贴图 / 角标 -------------------------------------------
  // 状态一览（README「第六轮调整（v0.36）」）：正常 = 不透明；建筑被掠夺 = 半透明 +
  // 火；地基被掠夺 = 灰 + 火；区域 / 建筑建造中 = 灰 + 锤子。灰色和半透明都是「坏
  // 掉」的样子，靠右下角标区分是掠夺还是建造中。
  const GREY_RES = 128;             // 灰色建筑贴图的内部解析度（px）

  // ``/assets/icons`` 里只有区域的 GREY 变体，建筑没有，所以就地做一张：按亮度去
  // 饱和、压暗一点、抬一点底，和区域灰变体一个调子（做法同 ``_starIcon`` 的像素级
  // 处理），按 URL 缓存。
  HexMap.prototype._greyIcon = function (url) {
    if (!url) return null;
    const img = this._img(url);
    if (!img) return null;
    let cv = this._greyCache.get(url);
    if (cv) return cv;
    const S = GREY_RES;
    cv = document.createElement("canvas");
    cv.width = S; cv.height = S;
    const c = cv.getContext("2d");
    c.drawImage(img, 0, 0, S, S);
    const rec = c.getImageData(0, 0, S, S);
    const px = rec.data;
    for (let k = 0; k < px.length; k += 4) {
      if (!px[k + 3]) continue;
      const lum = px[k] * 0.299 + px[k + 1] * 0.587 + px[k + 2] * 0.114;
      const g = Math.max(0, Math.min(255, lum * 0.78 + 30));
      px[k] = g; px[k + 1] = g; px[k + 2] = g;
    }
    c.putImageData(rec, 0, 0);
    this._greyCache.set(url, cv);
    return cv;
  };

  const BADGE_RES = 64;             // 角标内部解析度（px）
  const BADGE_DISC = "rgba(10,14,20,.68)";
  const BADGE_RIM = "rgba(255,255,255,.5)";
  const HAMMER_FACE = "#cfd8e2";
  const HAMMER_EDGE = "#78838f";
  const HAMMER_GRIP = "#a8763f";
  const FLAME_OUT = "#ff8a1e";
  const FLAME_IN = "#ffe066";
  const BADGE_INK = "rgba(26,17,6,.9)";

  // 角标画一次进离屏 canvas（同 v0.31 的核污染标记），之后逐格贴。
  HexMap.prototype._badgeIcon = function (kind) {
    let cv = this._badgeCache.get(kind);
    if (cv) return cv;
    const R = BADGE_RES / 2;
    cv = document.createElement("canvas");
    cv.width = BADGE_RES; cv.height = BADGE_RES;
    const c = cv.getContext("2d");
    c.beginPath();
    c.arc(R, R, R * 0.94, 0, Math.PI * 2);
    c.fillStyle = BADGE_DISC; c.fill();
    c.lineWidth = Math.max(1, R * 0.1);
    c.strokeStyle = BADGE_RIM; c.stroke();
    c.save();
    c.translate(R, R);
    if (kind === "build") {
      // 斜握的锤子：木柄 + 浅灰锤头
      c.rotate(-Math.PI / 5);
      c.fillStyle = HAMMER_GRIP;
      roundRect(c, -0.10 * R, -0.08 * R, 0.20 * R, 0.80 * R, 0.09 * R);
      c.fill();
      c.fillStyle = HAMMER_FACE;
      roundRect(c, -0.54 * R, -0.64 * R, 1.08 * R, 0.36 * R, 0.11 * R);
      c.fill();
      c.lineWidth = Math.max(1, R * 0.075);
      c.strokeStyle = HAMMER_EDGE;
      c.stroke();
    } else {
      // 火：外橙内黄的两层火焰
      const flame = (sc, fill) => {
        c.beginPath();
        c.moveTo(0, -0.86 * sc);
        c.bezierCurveTo(0.44 * sc, -0.38 * sc, 0.66 * sc, 0.04 * sc, 0.38 * sc, 0.46 * sc);
        c.bezierCurveTo(0.22 * sc, 0.72 * sc, -0.22 * sc, 0.72 * sc, -0.38 * sc, 0.46 * sc);
        c.bezierCurveTo(-0.66 * sc, 0.04 * sc, -0.44 * sc, -0.38 * sc, 0, -0.86 * sc);
        c.closePath();
        c.fillStyle = fill; c.fill();
      };
      flame(R * 0.88, FLAME_OUT);
      c.lineWidth = Math.max(1, R * 0.11);
      c.strokeStyle = BADGE_INK;
      c.stroke();
      flame(R * 0.46, FLAME_IN);
    }
    c.restore();
    this._badgeCache.set(kind, cv);
    return cv;
  };

  // 贴在格子的右下角（``0.24s / 0.32s`` 处，直径 ``0.42s``）。
  HexMap.prototype._drawTileBadge = function (ctx, kind, cx, cy, s, withAdjacency) {
    const icon = this._badgeIcon(kind);
    if (!icon) return;
    const size = s * (withAdjacency ? 0.24 : 0.42);
    const bx = cx + s * (withAdjacency ? 0.38 : 0.24);
    const by = cy + s * (withAdjacency ? 0.08 : 0.32);
    ctx.drawImage(icon, bx - size / 2, by - size / 2, size, size);
  };

  // wonders: tiles.wonder -> full-tile building texture (upstream Viewer).
  // v0.23: a wonder hash missing from its city's ``built`` map is still under
  // construction, so it is drawn at 50% (mirrors upstream Viewer.cpp).
  HexMap.prototype.drawWonders = function () {
    if (!this.layers.district) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale, r = SQRT * s;
    const arr = this.payload.tiles.wonder || [];
    for (let i = 0; i < arr.length; i++) {
      const hash = arr[i];
      if (hash === NONE || hash === -1) continue;
      const img = this._img(this.iconURL(hash));
      if (!img) continue;
      const built = this._builtOfTile(i);
      const wip = !(built && built[String(hash >>> 0)]);
      for (const p of this.screensOf(i, w, h)) {
        ctx.globalAlpha = wip ? 0.5 : 1;
        ctx.drawImage(img, p.sx - s / 2, p.sy - r, s, 2 * r);
        ctx.globalAlpha = 1;
      }
    }
  };
  HexMap.prototype.drawRivers = function () {
    if (!this.layers.river) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    const bits = this.payload.tiles.riverBits || [];
    ctx.lineCap = "round";
    for (let i = 0; i < bits.length; i++) {
      const mask = (bits[i] >> 8) & 0xFF;
      if (!mask) continue;
      for (const p of this.screensOf(i, w, h)) {
        const v = this.vertices(p.sx, p.sy, s);
        for (let k = 0; k < 6; k++) {
          if (!(mask & (1 << k))) continue;
          const [a, b] = RIVER_EDGE[k];
          this._segment(ctx, v[a], v[b], RIVER_OUTER, 0.1075 * s);
          this._segment(ctx, v[a], v[b], RIVER_INNER, 0.0806 * s);
        }
      }
    }
  };

  HexMap.prototype._segment = function (ctx, a, b, color, width) {
    ctx.beginPath();
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(b[0], b[1]);
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1, width);
    ctx.stroke();
  };

  // Neighbour index for border bit ``k`` (``BORDER_OFFSET``/``BORDER_EDGE``
  // order, odd rows shifted by one) with ``wrapX`` applied; -1 at the map
  // edge.  Shared by the border walk and the route layer so both agree on
  // which tiles touch across the seam.
  HexMap.prototype.neighborIndex = function (i, k) {
    const x = i % this.width, y = (i / this.width) | 0;
    let dx = BORDER_OFFSET[k][0];
    const dy = BORDER_OFFSET[k][1];
    if (dy !== 0 && (y & 1)) dx += 1;
    const ny = y + dy;
    if (ny < 0 || ny >= this.height) return -1;
    let nx = (x + dx) % this.width;
    if (nx < 0) nx += this.width;
    return ny * this.width + nx;
  };

  // v0.25 (PLAN B1) route layer.  A segment is drawn to every neighbour that
  // also carries a route - once per pair (``ni < i``, as in the upstream
  // Viewer) - coloured by the *higher* route index of the two ends because
  // roads upgrade in place (0 -> 1 -> 2 -> 3 in the save).  The shared edge
  // switches to the bridge style when it crosses a river bit or touches water
  // and the route supports bridges (``SupportsBridges`` is false only for
  // ``ROUTE_ANCIENT_ROAD``, i.e. index >= 1).
  // Roads run after terrain and rivers so bridges sit above the water,
  // and *below* every icon layer (see the order in ``draw``).
  HexMap.prototype.drawRoads = function () {
    if (!this.layers.road) return;
    const tiles = this.payload.tiles;
    const road = tiles.road || [];
    if (!road.length) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    const riverBits = tiles.riverBits || [];
    const water = tiles.water || [];
    ctx.lineCap = "round";
    for (let i = 0; i < road.length; i++) {
      const ri = road[i];
      if (ri < 0 || ri === ROAD_NONE) continue;
      for (let k = 0; k < 6; k++) {
        const ni = this.neighborIndex(i, k);
        if (ni < 0 || ni >= road.length || ni < i) continue;
        const rn = road[ni];
        if (rn < 0 || rn === ROAD_NONE) continue;
        const idx = Math.min(Math.max(ri, rn), ROAD_FALLBACK);
        const bridge = idx >= 1 &&
          ((((riverBits[i] >> 8) & 0xFF) & (1 << BORDER_EDGE[k])) !== 0 ||
           water[i] === 1 || water[ni] === 1);
        for (const p of this.screensOf(i, w, h)) {
          const q = this._nearestScreen(ni, p, w, h);
          if (!q) continue;
          const a = [p.sx, p.sy], b = [q.sx, q.sy];
          if (idx === 4) this._drawRail(ctx, a, b, s, bridge);
          else if (bridge) this._drawBridge(ctx, a, b, s, ROAD_COLORS[idx]);
          else this._drawRoad(ctx, a, b, s, ROAD_COLORS[idx]);
        }
      }
    }
  };

  // Screen copy of tile ``i`` whose x is closest to ``p`` - the wrap-aware
  // partner for a segment (mirrors the upstream ``myPos.x -= mapWidth`` fix).
  HexMap.prototype._nearestScreen = function (i, p, w, h) {
    let best = null, bestD = Infinity;
    for (const q of this.screensOf(i, w, h)) {
      const d = Math.abs(q.sx - p.sx);
      if (d < bestD) { bestD = d; best = q; }
    }
    return best;
  };

  // plain road: dark casing keeps the five shades readable on any terrain
  HexMap.prototype._drawRoad = function (ctx, a, b, s, color) {
    const w = Math.max(1, ROAD_WIDTH * s);
    this._segment(ctx, a, b, "rgba(12,16,22,.5)", w * 1.9);
    this._segment(ctx, a, b, color, w);
  };

  // bridge: heavy dark deck plus two crossties (PLAN B1)
  HexMap.prototype._drawBridge = function (ctx, a, b, s, color) {
    const w = Math.max(1, ROAD_WIDTH * s);
    this._segment(ctx, a, b, "rgba(10,14,20,.9)", w * 2.2);
    this._segment(ctx, a, b, color, w * 1.1);
    this._drawSleepers(ctx, a, b, w * 1.7, "rgba(18,22,30,.9)", [0.34, 0.66]);
  };

  // v0.26 railroad: a white base line with equal-length black dashes on top, so
  // it reads as alternating black/white at every zoom.  On a bridge the dark
  // deck stays underneath (``_drawBridge``'s cue) and carries the same pattern.
  HexMap.prototype._drawRail = function (ctx, a, b, s, bridge) {
    const w = Math.max(1, ROAD_WIDTH * s);
    if (bridge) this._segment(ctx, a, b, "rgba(10,14,20,.9)", w * 2.4);
    else this._segment(ctx, a, b, "rgba(12,16,22,.55)", w * 1.9);
    this._segment(ctx, a, b, RAIL_WHITE, w * 1.05);
    const dash = Math.max(1.6, RAIL_DASH * s);
    ctx.save();
    ctx.setLineDash([dash, dash]);
    this._segment(ctx, a, b, RAIL_BLACK, w * 1.05);
    ctx.restore();
  };

  // perpendicular ticks at fractions ``ts`` along the a->b segment
  HexMap.prototype._drawSleepers = function (ctx, a, b, half, color, ts) {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len = Math.hypot(dx, dy);
    if (!ts || !ts.length || len < 0.5) return;
    const ux = dx / len, uy = dy / len, px = -uy, py = ux;
    ctx.beginPath();
    for (const t of ts) {
      const cx = a[0] + ux * len * t, cy = a[1] + uy * len * t;
      ctx.moveTo(cx - px * half, cy - py * half);
      ctx.lineTo(cx + px * half, cy + py * half);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1, half * 0.55);
    ctx.stroke();
  };

  // Border masks per tile, ported from upstream CivVIState::ComputeCityLine.
  // ``owner``: differing / out-of-map neighbour keeps the edge.
  // ``city``: neighbour with a different city id but same owner (>=0) keeps it.
  HexMap.prototype.cityLines = function () {
    if (this._linesFor === this.payload && this._linesCache) return this._linesCache;
    const tiles = this.payload.tiles;
    const owner = tiles.owner, city = tiles.city;
    const ownerLines = new Uint8Array(owner.length);
    const cityLines = new Uint8Array(owner.length);
    for (let i = 0; i < owner.length; i++) {
      const o = owner[i];
      const ci = city[i];
      let oMask = 0, cMask = 0;
      for (let k = 0; k < 6; k++) {
        const ni = this.neighborIndex(i, k);
        if (ni < 0) continue;
        if (ci >= 0 && o >= 0 && city[ni] >= 0 && city[ni] !== ci && owner[ni] === o) {
          cMask |= (1 << k);
        }
        if (o < 0) continue;
        if (oMask === 0) oMask = 63;
        if (owner[ni] === o) oMask &= ~(1 << k);
      }
      ownerLines[i] = oMask;
      cityLines[i] = cMask;
    }
    this._linesFor = this.payload;
    this._linesCache = { owner: ownerLines, city: cityLines };
    return this._linesCache;
  };

  HexMap.prototype.drawBorders = function () {
    if (!this.layers.owner) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    const lines = this.cityLines().owner;
    const owner = this.payload.tiles.owner;
    for (let i = 0; i < lines.length; i++) {
      const mask = lines[i];
      if (!mask) continue;
      const primary = this.playerColor(owner[i]);
      const secondary = this.playerSecondary(owner[i]);
      for (const p of this.screensOf(i, w, h)) {
        const v = this.vertices(p.sx, p.sy, s);
        for (let k = 0; k < 6; k++) {
          if (!(mask & (1 << k))) continue;
          const [a, b] = RIVER_EDGE[BORDER_EDGE[k]];
          this._segment(ctx, v[a], v[b], primary, 0.1075 * s);
          this._segment(ctx, v[a], v[b], secondary, 0.0215 * s);
        }
      }
    }
  };

  // dashed intra-civ city boundaries (drawn after the owner border)
  HexMap.prototype.drawCityDashes = function () {
    if (!this.layers.owner) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    const lines = this.cityLines().city;
    const owner = this.payload.tiles.owner;
    ctx.save();
    ctx.setLineDash([0.12 * s, 0.12 * s]);
    for (let i = 0; i < lines.length; i++) {
      const mask = lines[i];
      if (!mask) continue;
      ctx.strokeStyle = this._alpha(this.playerColor(owner[i]), 0.55);
      ctx.lineWidth = Math.max(1, 0.03 * s);
      for (const p of this.screensOf(i, w, h)) {
        const v = this.vertices(p.sx, p.sy, s);
        for (let k = 0; k < 6; k++) {
          if (!(mask & (1 << k))) continue;
          const [a, b] = RIVER_EDGE[BORDER_EDGE[k]];
          ctx.beginPath();
          ctx.moveTo(v[a][0], v[a][1]);
          ctx.lineTo(v[b][0], v[b][1]);
          ctx.stroke();
        }
      }
    }
    ctx.restore();
  };

  // city status bars (scale >= 9) / legacy circle+name marker (scale < 9).
  HexMap.prototype.drawCities = function () {
    if (!this.layers.district) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    const bars = s >= 9;
    ctx.textAlign = "center";
    for (const pl of (this.payload.players || [])) {
      for (const city of (pl.cities || [])) {
        const i = city.y * this.width + city.x;
        for (const p of this.screensOf(i, w, h)) {
          if (bars) this._drawCityBar(ctx, pl, city, p.sx, p.sy, s);
          else this._drawCityDot(ctx, pl, city, p.sx, p.sy, s);
        }
      }
    }
  };

  HexMap.prototype._drawCityDot = function (ctx, pl, city, sx, sy, s) {
    ctx.beginPath(); ctx.arc(sx, sy, s * 0.42, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(0,0,0,.55)"; ctx.fill();
    ctx.strokeStyle = this.playerColor(pl.iPlayer); ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = "#fff";
    ctx.font = Math.max(8, s * 0.5) + "px sans-serif";
    ctx.textBaseline = "middle";
    ctx.fillText(String(city.population), sx, sy + 0.5);
    if (city.name) {
      const fs = Math.max(9, 0.42 * s);
      ctx.font = fs + "px \"Microsoft YaHei\", sans-serif";
      ctx.textBaseline = "alphabetic";
      const ty = sy - s * 0.56;
      ctx.lineWidth = Math.max(2, fs * 0.22);
      ctx.strokeStyle = "rgba(0,0,0,.85)";
      ctx.lineJoin = "round";
      ctx.strokeText(city.name, sx, ty);
      ctx.fillStyle = "#fff";
      ctx.fillText(city.name, sx, ty);
    }
  };

  // --- v0.26 city walls ---------------------------------------------------
  // ``meta.wallDefense`` = {buildings: {hash: {hp, order}}, urbanDefense,
  // steelTech}.  The cap is taken from the *highest ordered* wall building the
  // city actually built (``city.built``) because that is the only reliable tier
  // signal: a MOD may give every tier the same HP (BBG: 75) and ``city.wall``
  // is 1 for every walled city on the sample save.  A city whose ``built`` map
  // carries no wall entry at all falls back to the tier matching ``wall``
  // (1 = 远古城墙, 2 = 中世纪城墙, 3 = 文艺复兴城墙).
  HexMap.prototype._knowsSteel = function (iPlayer) {
    const wd = this.meta && this.meta.wallDefense;
    if (!wd || wd.steelTech == null) return false;
    const steel = wd.steelTech >>> 0;
    for (const p of (this.payload.players || [])) {
      if (p.iPlayer !== iPlayer) continue;
      return (p.techResearched || []).some((h) => (h >>> 0) === steel);
    }
    return false;
  };

  // ``{max}`` wall cap in force for the city, or ``null`` when it has no walls.
  HexMap.prototype._wallInfo = function (iPlayer, city) {
    const wd = this.meta && this.meta.wallDefense;
    const table = wd && wd.buildings;
    const level = Number(city.wall) || 0;
    const dmg = Number(city.wallDamage) || 0;
    if (!table || !Object.keys(table).length) {
      // snapshot predates the wall table: keep the old "has walls" signal (the
      // strip then falls back to the city centre's own 200 HP scale)
      return (level > 0 || dmg > 0) ? { max: CITY_CENTER_HP } : null;
    }
    let best = null;
    const built = city.built || {};
    for (const k in built) {
      const e = table[String(parseInt(k, 10) >>> 0)];
      if (e && (!best || e.order > best.order)) best = e;
    }
    if (!best && level > 0) {
      for (const h in table) {
        const e = table[h];
        if (e.order === level - 1) { best = e; break; }
      }
    }
    if (!best) return dmg > 0 ? { max: CITY_CENTER_HP } : null;
    let max = Number(best.hp) || 0;
    if (wd.urbanDefense && this._knowsSteel(iPlayer)) max = Number(wd.urbanDefense);
    return { max: max || CITY_CENTER_HP };
  };

  HexMap.prototype._drawCityBar = function (ctx, pl, city, sx, sy, s) {
    const fs = Math.max(9, 0.4 * s);
    ctx.font = fs + "px \"Microsoft YaHei\", sans-serif";
    ctx.textBaseline = "middle";
    const name = city.name || "";
    const nameW = ctx.measureText(name).width;
    const pad = fs * 0.42;
    const popW = fs * 1.5;
    const iconS = fs * 1.25;
    // v0.26: the wall shield + damage number are gone - the walls are the blue
    // strip under the health bar (see below)
    const wall = this._wallInfo(pl.iPlayer, city);
    const prodHash = (city.currentProds || [])[0];
    // v0.25 (PLAN B4): majority religion, drawn leftmost of the right-hand
    // slots.  ``religion`` is a ``RELIGION_*`` hash (0xFFFFFFFF = none).
    const religionHash = city.religion;
    const religionShow = religionHash != null && (religionHash >>> 0) !== NONE;
    let rightN = 0;
    if (religionShow) rightN++;
    if (city.governor != null && (city.governor >>> 0) !== NONE) rightN++;
    if (prodHash != null) rightN++;
    const rightW = rightN * (iconS + fs * 0.2);
    const barW = popW + pad + Math.max(nameW, fs * 2) + pad + rightW + pad;
    // the two stacked bars (health, walls) each add their own row
    const stripH = Math.max(1.5, fs * 0.16);
    const stripsH = stripH * (wall ? 2 : 1) + (wall ? Math.max(1, fs * 0.08) : 0);
    const barH = fs * 1.85 + stripsH;
    const bx = sx - barW / 2;
    const by = sy - s * 0.92 - barH;
    const col = this.playerColor(pl.iPlayer);
    roundRect(ctx, bx, by, barW, barH, fs * 0.35);
    ctx.fillStyle = "rgba(14,19,27,.86)"; ctx.fill();
    ctx.strokeStyle = col; ctx.lineWidth = Math.max(1, fs * 0.12); ctx.stroke();
    roundRect(ctx, bx, by, popW, barH - stripsH, fs * 0.35);
    ctx.fillStyle = col; ctx.fill();
    const rowCy = by + (barH - stripsH) / 2;
    ctx.fillStyle = "#fff";
    ctx.font = "bold " + fs + "px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(String(city.population), bx + popW / 2, rowCy + 0.5);
    ctx.font = fs + "px \"Microsoft YaHei\", sans-serif";
    ctx.textAlign = "left";
    ctx.fillStyle = "#fff";
    ctx.fillText(name, bx + popW + pad, rowCy + 0.5);
    let rx = bx + popW + pad + Math.max(nameW, fs * 2) + pad + iconS * 0.5;
    const cy = rowCy;
    if (religionShow) {
      const icon = this.iconURL(religionHash) || "/assets/icons/yield/Faith.png";
      const gi = this._img(icon);
      if (gi) ctx.drawImage(gi, rx - iconS / 2, cy - iconS / 2, iconS, iconS);
      rx += iconS + fs * 0.2;
    }
    if (city.governor != null && (city.governor >>> 0) !== NONE) {
      const gi = this._img(this.iconURL(city.governor));
      if (gi) ctx.drawImage(gi, rx - iconS / 2, cy - iconS / 2, iconS, iconS);
      rx += iconS + fs * 0.2;
    }
    if (prodHash != null) {
      const pi = this._img(this.iconURL(prodHash));
      if (pi) ctx.drawImage(pi, rx - iconS / 2, cy - iconS / 2, iconS, iconS);
    }
    // --- health strip: always drawn (green while untouched) ---------------
    const dmg = city.damage || 0;
    const hy = by + barH - stripsH;
    const hw = barW * Math.max(0, Math.min(1, (CITY_CENTER_HP - dmg) / CITY_CENTER_HP));
    ctx.fillStyle = "rgba(0,0,0,.6)";
    ctx.fillRect(bx, hy, barW, stripH);
    ctx.fillStyle = hw > barW * 0.5 ? "#5fbf5f" : (hw > barW * 0.25 ? "#d8b53c" : "#d05545");
    ctx.fillRect(bx, hy, hw, stripH);
    // --- blue wall strip glued right under it ----------------------------
    if (wall) {
      const wy = hy + stripH + Math.max(1, fs * 0.08);
      // v0.26.1: the strip is the wall's *own* bar - full width at full wall HP,
      // shrinking as it is damaged - instead of a fraction of the city's 200 HP
      // (which made an untouched 远古城墙 look half destroyed).
      const frac = Math.max(0, Math.min(1,
        (wall.max - (Number(city.wallDamage) || 0)) / wall.max));
      ctx.fillStyle = "rgba(0,0,0,.6)";
      ctx.fillRect(bx, wy, barW, stripH);
      ctx.fillStyle = "#4fa3d9";
      ctx.fillRect(bx, wy, barW * frac, stripH);
    }
    this._cityRects.push({ x: bx, y: by, w: barW, h: barH, iPlayer: pl.iPlayer, cityId: city.id });
  };

  HexMap.prototype._alpha = function (rgbStr, a) {
    const m = /rgb\((\d+),(\d+),(\d+)\)/.exec(rgbStr);
    if (!m) return rgbStr;
    return "rgba(" + m[1] + "," + m[2] + "," + m[3] + "," + a + ")";
  };
  // One icon per (category, owner) group: white silhouette tinted with the
  // owner's primary colour plus a secondary-colour outline.  The composite is
  // cached offscreen (key = iconURL + primary + secondary).
  HexMap.prototype._tintedIcon = function (url, primary, secondary) {
    if (!url) return null;
    const img = this._img(url);
    if (!img) return null;
    const key = url + "|" + primary + "|" + secondary;
    let cv = this._tintCache.get(key);
    if (cv) return cv;
    const S = TINT_SIZE, off = TINT_OFF;
    cv = document.createElement("canvas");
    cv.width = S + off * 2;
    cv.height = S + off * 2;
    const c = cv.getContext("2d");
    const sil = (color, dx, dy) => {
      const t = document.createElement("canvas");
      t.width = S; t.height = S;
      const tc = t.getContext("2d");
      tc.drawImage(img, 0, 0, S, S);
      tc.globalCompositeOperation = "source-in";
      tc.fillStyle = color;
      tc.fillRect(0, 0, S, S);
      c.drawImage(t, off + dx, off + dy);
    };
    sil(secondary, -off, 0); sil(secondary, off, 0);
    sil(secondary, 0, -off); sil(secondary, 0, off);
    sil(primary, 0, 0);
    this._tintCache.set(key, cv);
    return cv;
  };

  HexMap.prototype._drawUnitIcon = function (ctx, g, cx, cy, size, primary, secondary) {
    const cv = this._tintedIcon(this.iconURL(g.type),
      primary || this.playerColor(g.iPlayer),
      secondary || this.playerSecondary(g.iPlayer));
    if (cv) ctx.drawImage(cv, cx - size / 2, cy - size / 2, size, size);
  };

  // v0.23: formation stars.  ``star.png`` is loaded once, its brightness used
  // as the alpha of a white silhouette and then tinted with the owner's
  // secondary colour (cached per colour); ``_img`` already caches the file.
  const STAR_URL = "/assets/icons/icon/star.png";
  const STAR_RES = 32;

  HexMap.prototype._starIcon = function (color) {
    const img = this._img(STAR_URL);
    if (!img) return null;
    let cv = this._starCache.get(color);
    if (cv) return cv;
    const S = STAR_RES;
    const sil = document.createElement("canvas");
    sil.width = S; sil.height = S;
    const sc = sil.getContext("2d");
    sc.drawImage(img, 0, 0, S, S);
    const rec = sc.getImageData(0, 0, S, S);
    const px = rec.data;
    for (let k = 0; k < px.length; k += 4) {
      const lum = Math.max(px[k], px[k + 1], px[k + 2]);
      px[k] = 255; px[k + 1] = 255; px[k + 2] = 255;
      px[k + 3] = (px[k + 3] * lum) / 255;
    }
    sc.putImageData(rec, 0, 0);
    cv = document.createElement("canvas");
    cv.width = S; cv.height = S;
    const c = cv.getContext("2d");
    c.drawImage(sil, 0, 0);
    c.globalCompositeOperation = "source-in";
    c.fillStyle = color;
    c.fillRect(0, 0, S, S);
    this._starCache.set(color, cv);
    return cv;
  };

  // one ★ per army level (1 = corps/fleet -> 2 stars, 2 = army/armada -> 3)
  HexMap.prototype._drawStars = function (ctx, cx, cy, count, starSize, iPlayer, iconSize) {
    if (!count) return;
    const cv = this._starIcon(this.playerSecondary(iPlayer));
    if (!cv) return;
    const gap = starSize * 1.06;
    const y = cy - iconSize * 0.5 - starSize * 0.62;
    let x = cx - (count - 1) * gap / 2;
    for (let k = 0; k < count; k++) {
      ctx.drawImage(cv, x - starSize / 2, y - starSize / 2, starSize, starSize);
      x += gap;
    }
  };

  // v0.24: unit health bar (drawn under the icon, only when the unit is hurt -
  // mirrors the in-game behaviour).  ``hp``/``hpMax`` come from the payload;
  // ``ratio`` is 0..1 and the colour walks green -> amber -> red.
  HexMap.prototype._drawUnitHealth = function (ctx, cx, cy, size, ratio) {
    const bw = size * 0.92, bh = Math.max(2, size * 0.11);
    const bx = cx - bw / 2, by = cy + size * 0.42;
    const r = Math.max(0, Math.min(1, ratio));
    ctx.fillStyle = "rgba(8,11,16,.85)";
    ctx.fillRect(bx - 1, by - 1, bw + 2, bh + 2);
    ctx.fillStyle = r > 0.6 ? "#5fbf5f" : (r > 0.3 ? "#d8b53c" : "#d05545");
    ctx.fillRect(bx, by, bw * r, bh);
  };

  // Health of the group for the map bar: the weakest unit decides, so a
  // damaged corps/army in a stack is not hidden behind a healthy one.
  function groupHp(g) {
    if (!g.count) return 1;
    return (g.hpMin == null ? g.hpMax : g.hpMin) / (g.hpMax || 100);
  }

  // Every category uses one extra icon with a black drop shadow to indicate
  // stacking. Further units stay in the payload but add no map icons or badges.
  const UNIT_STACK_MAX = 2;

  // Take at most two units in group order; the renderer paints the back first.
  function stackLayers(groups) {
    const out = [];
    for (const g of groups) {
      for (let k = 0; k < Math.min(g.count, UNIT_STACK_MAX); k++) {
        if (out.length >= UNIT_STACK_MAX) return out;
        out.push(g);
      }
    }
    return out;
  }

  // the weakest unit in the slot settles its health bar (as in ``groupHp``)
  function stackHp(groups) {
    let ratio = 1, hurt = false;
    for (const g of groups) {
      ratio = Math.min(ratio, groupHp(g));
      if (g.hpMin < g.hpMax) hurt = true;
    }
    return { ratio: ratio, hurt: hurt };
  }

  // Formation stars ride on the front icon; include units beyond the icon cap
  // when choosing the formation level, just as the health bar does.
  HexMap.prototype._drawUnitStack = function (ctx, slot, cx, cy, size,
                                              starSize) {
    const layers = slot.layers, n = layers.length;
    for (let k = n - 1; k >= 0; k--) {
      const dx = -k * size * 0.16, dy = -k * size * 0.16;
      if (n > 1) {
        this._drawUnitIcon(ctx, layers[k], cx + dx + size * 0.05,
                           cy + dy + size * 0.07, size, "#000", "#000");
      }
      this._drawUnitIcon(ctx, layers[k], cx + dx, cy + dy, size);
    }
    const hp = stackHp(slot.groups);
    if (hp.hurt) {
      this._drawUnitHealth(ctx, cx, cy + (1 - n) * size * 0.16, size, hp.ratio);
    }
    if (n) {
      let best = slot.groups[0];
      for (const g of slot.groups) if (starCount(g.army) > starCount(best.army)) best = g;
      this._drawStars(ctx, cx, cy, starCount(best.army), starSize, best.iPlayer,
                      size);
    }
  };

  // One position per (category, owner), with all traders sharing a tile slot.
  HexMap.prototype._drawUnitSlot = function (ctx, slot, cx, cy, size, starSize) {
    this._drawUnitStack(ctx, slot, cx, cy, size, starSize);
  };

  HexMap.prototype.drawUnits = function () {
    if (!this.layers.unit) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const s = this.scale;
    const byTile = new Map();
    for (const u of (this.payload.units || [])) {
      const i = u.y * this.width + u.x;
      let m = byTile.get(i);
      if (!m) { m = new Map(); byTile.set(i, m); }
      const cat = u.air ? "air" : (u.cat || "mil");
      const army = armyNorm(u.army);
      // Keep each type so mixed civilian, spy, or military stacks can paint
      // distinct icons while still sharing one category/owner slot.
      const key = cat + "\u0000" + u.iPlayer + "\u0000" + army + "\u0000" + u.type;
      let g = m.get(key);
      if (!g) {
        g = { cat: cat, iPlayer: u.iPlayer, type: u.type,
              army: army, count: 0, hpMax: u.hpMax || 100, hpMin: null };
        m.set(key, g);
      }
      g.count += 1;
      const hp = (u.hp == null) ? g.hpMax : u.hp;
      g.hpMin = (g.hpMin == null) ? hp : Math.min(g.hpMin, hp);
    }
    for (const [i, m] of byTile) {
      const groups = [...m.values()].sort((a, b) =>
        (CAT_ORDER.indexOf(a.cat) - CAT_ORDER.indexOf(b.cat)) ||
        (a.iPlayer - b.iPlayer) || (a.army - b.army));
      // Preserve category/owner positions and the shared trader slot, folding
      // all types and formation levels at each position into the same stack.
      const slots = [];
      const slotByKey = new Map();
      for (const g of groups) {
        const key = g.cat === "trade" ? "trade" : g.cat + "\u0000" + g.iPlayer;
        let slot = slotByKey.get(key);
        if (!slot) {
          slot = { cat: g.cat, groups: [], layers: [] };
          slotByKey.set(key, slot);
          slots.push(slot);
        }
        slot.groups.push(g);
      }
      for (const slot of slots) slot.layers = stackLayers(slot.groups);
      const shown = slots.slice(0, 6);
      for (const p of this.screensOf(i, w, h)) {
        const starSize = (shown.length === 1 ? 0.22 : 0.18) * s;
        if (shown.length === 1) {
          this._drawUnitSlot(ctx, shown[0], p.sx, p.sy, s * 0.62, starSize);
        } else {
          const row = GROUP_POS[shown.length - 1];
          for (let k = 0; k < shown.length; k++) {
            const gx = row[k * 2] / 180 * s, gy = row[k * 2 + 1] / 180 * s;
            this._drawUnitSlot(ctx, shown[k], p.sx + gx, p.sy + gy, s * 0.46,
                               starSize);
          }
        }
      }
    }
  };

  HexMap.prototype.drawSelectedHover = function () {
    const ctx = this.ctx;
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    for (const [i, color, width] of [[this.selected, "#fff", 2.5], [this.hover, "#ffd36b", 2]]) {
      if (i == null || i < 0) continue;
      for (const p of this.screensOf(i, w, h)) {
        this.hexPath(ctx, p.sx, p.sy, this.scale);
        ctx.strokeStyle = color; ctx.lineWidth = width; ctx.stroke();
      }
    }
  };

  HexMap.prototype.drawFog = function () {
    if (!this.layers.fog || !this.fog.enabled || this.fog.player == null) return;
    const vis = (this.payload.visibility || {})[String(this.fog.player)];
    if (!vis) return;
    const ctx = this.ctx, w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    for (let i = 0; i < vis.length; i++) {
      if (vis[i]) continue;
      for (const p of this.screensOf(i, w, h)) {
        this.hexPath(ctx, p.sx, p.sy, this.scale);
        ctx.fillStyle = "rgba(5,8,12,.82)"; ctx.fill();
      }
    }
  };

  HexMap.prototype.nameInfo = function (hash) {
    const h = (hash >>> 0).toString();
    return this.meta && this.meta.names ? this.meta.names[h] : null;
  };
  HexMap.prototype.playerInfo = function (iPlayer) {
    return (this.meta && this.meta.players)
      ? this.meta.players.find((x) => x.iPlayer === iPlayer) : null;
  };
  HexMap.prototype.playerColor = function (iPlayer) {
    const p = this.playerInfo(iPlayer);
    return p ? rgb(p.primary) : "#888";
  };
  HexMap.prototype.playerSecondary = function (iPlayer) {
    const p = this.playerInfo(iPlayer);
    return p ? rgb(p.secondary) : "#eee";
  };

  function rgb(c) { return "rgb(" + ((c[0]*255)|0) + "," + ((c[1]*255)|0) + "," + ((c[2]*255)|0) + ")"; }
  HexMap.terrainColor = terrainColor;
  HexMap.terrainKey = terrainKey;
  HexMap.LAYERS = LAYERS;
  HexMap.MAX_SCALE = MAX_SCALE;
  HexMap.MIN_SCALE = MIN_SCALE;
  HexMap.DEFAULT_SCALE = DEFAULT_SCALE;

  HexMap.prototype._bind = function () {
    const cv = this.canvas;
    let down = false, moved = false, last = null;
    cv.addEventListener("mousedown", (e) => { down = true; moved = false; last = { x: e.clientX, y: e.clientY }; cv.classList.add("dragging"); });
    window.addEventListener("mouseup", (e) => {
      if (down && !moved) {
        const r = cv.getBoundingClientRect();
        const lx = e.clientX - r.left, ly = e.clientY - r.top;
        const city = this._cityHit(lx, ly);
        if (city) {
          this._emit("cityselect", city);
        } else {
          const i = this.nearest(lx, ly);
          if (i >= 0) { this.selected = i; this.draw(); this._emit("select", i); }
        }
      }
      down = false; cv.classList.remove("dragging");
    });
    cv.addEventListener("mousemove", (e) => {
      const r = cv.getBoundingClientRect();
      if (down && last) {
        this._clearHover();
        const dx = e.clientX - last.x, dy = e.clientY - last.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
        this.camX -= dx / this.scale; this.camY -= dy / this.scale;
        this._wrapCam();
        last = { x: e.clientX, y: e.clientY }; this.draw();
      } else {
        const lx = e.clientX - r.left, ly = e.clientY - r.top;
        // v0.25 (B4): a city status bar is its own hit target - while the
        // pointer is on one no tile is hovered, and the app layer renders the
        // city tooltip instead of the tile tooltip (single writer).
        const bar = this._cityHit(lx, ly);
        const key = bar ? (bar.iPlayer + ":" + bar.cityId) : null;
        // over a bar the tile under the cursor is not the bar's city tile
        const i = bar ? -1 : this.nearest(lx, ly);
        if (i !== this.hover || key !== this._hoverCity) {
          this.hover = i; this._hoverCity = key;
          this.draw();
          this._emit("hover", {
            i, x: lx, y: ly,
            city: bar ? { iPlayer: bar.iPlayer, cityId: bar.cityId } : null,
          });
        }
      }
    });
    cv.addEventListener("mouseleave", () => this._clearHover(true));
    cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = cv.getBoundingClientRect();
      const bx = e.clientX - r.left, by = e.clientY - r.top;
      const before = this.toWorld(bx, by);
      this.scale *= e.deltaY < 0 ? 1.12 : 1 / 1.12;
      this.scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, this.scale));
      const after = this.toWorld(bx, by);
      this.camX += before.wx - after.wx; this.camY += before.wy - after.wy;
      this._wrapCam();
      this.draw();
    }, { passive: false });
    window.addEventListener("resize", () => this._scheduleDraw());
  };

  HexMap.prototype._cityHit = function (x, y) {
    for (let i = this._cityRects.length - 1; i >= 0; i--) {
      const r = this._cityRects[i];
      if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) return r;
    }
    return null;
  };

  // Drop the hover state (and tell the app layer) - ``redraw`` is false while
  // panning because the pan itself repaints.
  HexMap.prototype._clearHover = function (redraw) {
    if (this.hover === -1 && !this._hoverCity) return;
    this.hover = -1; this._hoverCity = null;
    if (redraw) this.draw();
    this._emit("hover", { i: -1, x: 0, y: 0, city: null });
  };

  global.HexMap = HexMap;
})(window);
