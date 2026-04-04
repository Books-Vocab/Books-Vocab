# Graph Canvas 渲染效能優化 Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 優化 `graph.html` Canvas 渲染效能，1000 nodes 達 50+ fps。
**Architecture:** 在單一 `graph.html` 內重構 draw loop — glow 預渲染 texture、label 雙層 fillText 替代 shadowBlur、quadtree 空間索引、edge 批次合併。
**Tech Stack:** Canvas 2D, d3.js quadtree, OffscreenCanvas（fallback createElement）

---

### Task 1: Glow Texture Cache

**Files:**
- Modify: `ios/BooksBrowser/Resources/graph.html:15-24`（global state 區塊加 cache）
- Modify: `ios/BooksBrowser/Resources/graph.html:121-147`（node draw loop）
- Modify: `ios/BooksBrowser/Resources/graph.html:272-346`（initGraph 加 cache clear）
- Modify: `ios/BooksBrowser/Resources/graph.html:363-367`（updateTheme 加 cache clear）

- [ ] **Step 1: 加入 glowCache 和 getGlowTexture 函式**

在 global state 區塊（`let sim, nodes = [], ...` 後面）加入：

```js
const glowCache = new Map();

function getGlowTexture(color, radius) {
    const rBucket = Math.max(2, Math.round(radius / 2) * 2);
    const key = color + '_' + rBucket;
    let tex = glowCache.get(key);
    const size = Math.ceil(rBucket * 2.2 * 2);
    if (tex) return { tex, size };

    const off = document.createElement('canvas');
    off.width = size; off.height = size;
    const oc = off.getContext('2d');
    const cx = size / 2, cy = size / 2;
    const inner = rBucket * 0.4, outer = rBucket * 2.2;
    const grad = oc.createRadialGradient(cx, cy, inner, cx, cy, outer);
    grad.addColorStop(0, color + '30');
    grad.addColorStop(1, color + '00');
    oc.fillStyle = grad;
    oc.beginPath();
    oc.arc(cx, cy, outer, 0, 2 * Math.PI);
    oc.fill();

    glowCache.set(key, off);
    return { tex: off, size };
}
```

- [ ] **Step 2: 替換 draw() 中的 glow 繪製邏輯**

將 L130-139（`if (!isThumbnail) { ... glow halo ... }`）替換為：

```js
if (!isThumbnail && opacity > 0.1) {
    const { tex, size } = getGlowTexture(color, r);
    ctx.globalAlpha = opacity;
    ctx.drawImage(tex, d.x - size / 2, d.y - size / 2, size, size);
}
```

- [ ] **Step 3: initGraph 和 updateTheme 加 cache clear**

在 `initGraph` 函式開頭（`const data = JSON.parse(jsonStr)` 之後）加：
```js
glowCache.clear();
```

在 `updateTheme` 函式開頭加：
```js
glowCache.clear();
```

- [ ] **Step 4: iOS build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 5: Commit**
`ios: graph canvas — replace per-frame gradient alloc with pre-rendered glow texture cache`

---

### Task 2: Label Shadow 改雙層 fillText

**Files:**
- Modify: `ios/BooksBrowser/Resources/graph.html:149-166`（label draw loop）

- [ ] **Step 1: 替換 label 繪製邏輯**

將 L150-166 替換為：

```js
if (!isThumbnail) {
    for (const d of nodes) {
        const r = nodeRadius(d);
        const opacity = opacityForNode(d.id);
        if (opacity < 0.2) continue;
        const fontSize = d.degree > 3 ? 10 : 8;
        ctx.font = `${fontSize}px -apple-system, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';

        // Shadow pass — 偏移 1px
        ctx.fillStyle = labelShadowColor;
        ctx.globalAlpha = 0.6 * opacity;
        ctx.fillText(d.word, d.x + 1, d.y + r + 4);

        // Main pass
        const labelAlpha = currentMode === 'dark' ? 0.90 * opacity : 0.82 * opacity;
        ctx.fillStyle = hexToRGBA(labelColor, labelAlpha);
        ctx.globalAlpha = 1;
        ctx.fillText(d.word, d.x, d.y + r + 3);
    }
}
```

注意：完全移除 `ctx.shadowColor` 和 `ctx.shadowBlur` 設定。

- [ ] **Step 2: iOS build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**
`ios: graph canvas — replace shadowBlur with double-pass fillText for labels`

---

### Task 3: findNode 改 d3.quadtree

**Files:**
- Modify: `ios/BooksBrowser/Resources/graph.html:15-24`（global state 加 qt）
- Modify: `ios/BooksBrowser/Resources/graph.html:183-188`（findNode）
- Modify: `ios/BooksBrowser/Resources/graph.html:337`（sim.on tick）

- [ ] **Step 1: 加入 quadtree 全域變數和 tick 更新**

Global state 加：
```js
let qt = null;
```

將 simulation 的 tick handler 從：
```js
.on('tick', draw);
```
改為：
```js
.on('tick', () => {
    qt = d3.quadtree(nodes, d => d.x, d => d.y);
    draw();
});
```

- [ ] **Step 2: 替換 findNode**

```js
function findNode(x, y) {
    if (!qt) return null;
    const sx = (x - transform.x) / transform.k;
    const sy = (y - transform.y) / transform.k;
    const maxR = (forces.baseNodeRadius || 4) * 2.2 + 4;
    const found = qt.find(sx, sy, maxR);
    if (!found) return null;
    if (Math.hypot(found.x - sx, found.y - sy) < nodeRadius(found) + 4) return found;
    return null;
}
```

- [ ] **Step 3: iOS build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**
`ios: graph canvas — use d3.quadtree for O(log N) node hit-testing`

---

### Task 4: Edge 批次合併 + Low Opacity Skip

**Files:**
- Modify: `ios/BooksBrowser/Resources/graph.html:105-119`（edge draw）
- Modify: `ios/BooksBrowser/Resources/graph.html:121-147`（node draw loop 開頭）

- [ ] **Step 1: 替換 edge 繪製邏輯**

將 L105-119 替換為：

```js
// Draw edges (batched by color + opacity)
const screenLineWidth = (forces.linkThickness || 1.0) / transform.k;
const edgeGroups = new Map();
for (const l of links) {
    const s = l.source, t = l.target;
    if (!s || !t || s.x == null || t.x == null) continue;
    const sid = typeof s === 'object' ? s.id : s;
    const tid = typeof t === 'object' ? t.id : t;
    const alpha = opacityForEdge(sid, tid);
    const color = EDGE_COLORS[l.kind] || '#888888';
    const key = color + '_' + alpha.toFixed(2);
    if (!edgeGroups.has(key)) edgeGroups.set(key, { color, alpha, segs: [] });
    edgeGroups.get(key).segs.push(s.x, s.y, t.x, t.y);
}
for (const [, g] of edgeGroups) {
    ctx.beginPath();
    const segs = g.segs;
    for (let i = 0; i < segs.length; i += 4) {
        ctx.moveTo(segs[i], segs[i + 1]);
        ctx.lineTo(segs[i + 2], segs[i + 3]);
    }
    ctx.strokeStyle = g.color;
    ctx.globalAlpha = g.alpha;
    ctx.lineWidth = screenLineWidth;
    ctx.stroke();
}
```

- [ ] **Step 2: Node draw loop 加 early exit**

在 node draw loop 開頭（`for (const d of nodes) {` 之後）加入提前計算：

```js
for (const d of nodes) {
    const interactOpacity = opacityForNode(d.id);
    if (interactOpacity < 0.1) continue;

    const r = nodeRadius(d);
    const color = nodeColor(d);
    const baseOp = baseOpacityForNode(d);
    const opacity = interactOpacity * baseOp;
    // ... 後續不變
```

- [ ] **Step 3: iOS build 驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**
`ios: graph canvas — batch edge draws by style and skip invisible nodes`

---

### Task 5: FPS Debug Mode + 最終驗證

**Files:**
- Modify: `ios/BooksBrowser/Resources/graph.html:89`（draw 開頭）

- [ ] **Step 1: 加入 FPS debug counter**

在 `draw()` 函式開頭（`ctx.clearRect` 之前）加：

```js
let _frameCount = 0, _lastFpsTime = performance.now();
```
（移至 global scope）

```js
// draw() 開頭
if (window.debugFPS) {
    _frameCount++;
    const now = performance.now();
    if (now - _lastFpsTime >= 1000) {
        console.log('[graph-perf] ' + _frameCount + ' fps');
        _frameCount = 0;
        _lastFpsTime = now;
    }
}
```

- [ ] **Step 2: iOS build 最終驗證**
Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: 功能驗證清單**
在 Preview 或 device 上確認：
- [ ] Glow halo 視覺與優化前一致
- [ ] Label 陰影效果可接受（硬陰影 vs 柔和模糊）
- [ ] Hover highlight 正常
- [ ] Click select/deselect 正常
- [ ] Drag 節點正常
- [ ] Zoom in/out 正常
- [ ] Thumbnail 無回歸（不顯示 glow/label）
- [ ] Dark/light 切換 glow 顏色正確

- [ ] **Step 4: Commit**
`ios: graph canvas — add opt-in FPS debug counter`

- [ ] **Step 5: 開 PR**
Title: `ios: graph canvas rendering performance optimization`
