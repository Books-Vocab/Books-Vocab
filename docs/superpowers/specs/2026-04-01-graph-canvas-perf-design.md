# Graph Canvas 渲染效能優化 Design Spec

## 問題

`graph.html` 的 `draw()` 每幀存在四個效能瓶頸：

1. **Glow halo**（L133-134）— 每幀×每節點 `createRadialGradient`，造成大量物件分配與 GC 壓力
2. **Label shadow**（L160-161）— `shadowBlur = 4` 觸發 Canvas per-pixel 高斯模糊，極昂貴
3. **findNode**（L184-188）— `nodes.find()` O(N) 線性搜尋，每次 pointermove 觸發
4. **無條件全繪**— opacity < 0.1 的節點仍繪製 glow + label

## 目標

- 1000 nodes 穩定 50+ fps（現況 20-40fps）
- 不改 Swift 端任何程式碼
- 視覺輸出與現況無可察覺差異

## 非目標

- 多層 Canvas 分離（方案 B，未來可加）
- WebGL 重寫（方案 C）
- Backend graph 儲存/查詢優化

## 設計

### 改動範圍

**唯一修改檔案：`ios/BooksBrowser/Resources/graph.html`**

### 1. Glow 預渲染 Texture Cache

**現況：**
```js
// 每幀×每節點（L133-134）
const grad = ctx.createRadialGradient(d.x, d.y, r*0.4, d.x, d.y, r*2.2);
grad.addColorStop(0, color + '30');
grad.addColorStop(1, color + '00');
ctx.fillStyle = grad;
ctx.fill();
```

**改為：**
- 維護 `glowCache: Map<string, CanvasImageSource>`，key = `${color}_${radiusBucket}`
- radius 分桶（取整到最近偶數 px）以限制 cache entries
- Cache miss 時在離屏 canvas 預繪一次 radial gradient → `drawImage` 貼圖
- `draw()` 中改為 `ctx.drawImage(texture, d.x - size/2, d.y - size/2, size, size)`

```js
// ── Glow texture cache ──
const glowCache = new Map();

function getGlowTexture(color, radius) {
    const rBucket = Math.max(2, Math.round(radius / 2) * 2);
    const key = color + '_' + rBucket;
    let tex = glowCache.get(key);
    const size = Math.ceil(rBucket * 2.2 * 2);
    if (tex) return { tex, size };

    const size = Math.ceil(rBucket * 2.2 * 2);
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

**Draw 端：**
```js
if (!isThumbnail && opacity > 0.1) {
    const { tex, size } = getGlowTexture(color, r);
    ctx.globalAlpha = opacity;
    ctx.drawImage(tex, d.x - size/2, d.y - size/2, size, size);
}
```

**Cache 失效**：`initGraph` 和 `updateTheme` 時都 `glowCache.clear()`。`initGraph` 覆蓋 data/theme 全變更；`updateTheme` 覆蓋 dark↔light 切換（tier colors 在兩個模式下不同）。

### 2. Label Shadow 改雙層 fillText

**現況：**
```js
ctx.shadowColor = labelShadowColor;
ctx.shadowBlur = 4;
ctx.fillText(d.word, d.x, d.y + r + 3);
```

**改為：**
```js
// Shadow pass — 偏移 1px，較低透明度
ctx.fillStyle = labelShadowColor;
ctx.globalAlpha = 0.6 * opacity;
ctx.fillText(d.word, d.x + 1, d.y + r + 4);

// Main pass — 保留原始 dark/light 模式透明度差異
const labelAlpha = currentMode === 'dark' ? 0.90 * opacity : 0.82 * opacity;
ctx.fillStyle = hexToRGBA(labelColor, labelAlpha);
ctx.globalAlpha = 1;
ctx.fillText(d.word, d.x, d.y + r + 3);
```

移除所有 `ctx.shadowBlur` 設定。視覺上從「柔和光暈」變為「硬陰影偏移」，在 8-10px 字體下幾乎無可察覺差異。

### 3. findNode 改 d3.quadtree

**現況：**
```js
function findNode(x, y) {
    const sx = (x - transform.x) / transform.k;
    const sy = (y - transform.y) / transform.k;
    return nodes.find(n => Math.hypot(n.x - sx, n.y - sy) < nodeRadius(n) + 4);
}
```

**改為：**
```js
let qt = null; // quadtree，每 tick 重建

// 在 simulation tick callback 中更新
sim.on('tick', () => {
    qt = d3.quadtree(nodes, d => d.x, d => d.y);
    draw();
});

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

d3.quadtree 建構 O(N)，查詢 O(log N)。simulation tick 時已遍歷 nodes，附加一次 quadtree rebuild 成本極低。

### 4. 低 Opacity 節點跳過繪製

在 node 繪製迴圈中提前跳過：

```js
for (const d of nodes) {
    const interactOpacity = opacityForNode(d.id);
    if (interactOpacity < 0.1) continue; // ← 新增：跳過幾乎不可見的節點

    const r = nodeRadius(d);
    const color = nodeColor(d);
    const baseOp = baseOpacityForNode(d);
    const opacity = interactOpacity * baseOp;
    // ... glow + fill
}
```

**注意**：此項為 forward-looking 優化。目前最低 opacity = 0.15（> 0.1），閾值不會觸發。但當未來加入 filter/隱藏節點功能時立即生效。當前對 FPS 目標無直接貢獻，但改動成本為零（僅提前一次函式呼叫），故一併納入。label 迴圈已有 `if (opacity < 0.2) continue`，無需改。

### 5. Edge 繪製批次合併

現況每條 edge 獨立 `beginPath/stroke`。改為按 kind 分組，同 kind 一次 `beginPath` + 多條 `moveTo/lineTo` + 一次 `stroke`：

```js
// 按 kind + opacity 分組
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
        ctx.moveTo(segs[i], segs[i+1]);
        ctx.lineTo(segs[i+2], segs[i+3]);
    }
    ctx.strokeStyle = g.color;
    ctx.globalAlpha = g.alpha;
    ctx.lineWidth = screenLineWidth;
    ctx.stroke();
}
```

減少 Canvas state switch 次數（`strokeStyle`/`globalAlpha` 切換）。500 edges 從 ~500 次 stroke 降為 2-4 次。

## 測試策略

無法自動化 FPS 測試。驗證方式：

1. **視覺回歸**：Preview 比對優化前後截圖，確認 glow/label/edge 視覺一致
2. **效能計量**：在 `draw()` 起始處加可開關的 FPS counter（`console.log` 每 60 幀輸出平均 ms）
3. **功能驗證**：hover highlight、click select、drag、zoom 行為不變
4. **Thumbnail 不受影響**：thumbnail 模式已跳過 glow 和 label，確認無回歸

## FPS Debug 模式

在 `draw()` 加入可透過 `window.debugFPS = true` 開啟的計量：

```js
let _frameCount = 0, _lastFpsTime = performance.now();
// draw() 開頭：
if (window.debugFPS) {
    _frameCount++;
    const now = performance.now();
    if (now - _lastFpsTime >= 1000) {
        console.log(`[graph-perf] ${_frameCount} fps`);
        _frameCount = 0; _lastFpsTime = now;
    }
}
```
