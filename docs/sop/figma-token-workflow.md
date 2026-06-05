<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - design-system/
  - ops/
verified_against: ecbcbcfa
-->
# Figma Token Studio Workflow（零基礎 solo 設計師接 tokens.json）

把 `design-system/tokens.json`（W3C DTCG 格式）接進 Figma 的 **Tokens Studio for Figma** plugin，讓設計師能在 Figma 裡視覺化、調整 design token，再回流到 repo。本檔給**完全沒用過 Figma** 的單人開發者，照步驟做即可。

> **先理解權威方向（接線後分兩種，不可混淆）**：
> - **已接線 scalar 群組**（`AppRadius` / `AppSpacing` scale / `AppFonts.TypeScale` / `AppFonts.Tracking` / `AppElevation`）：這些 Swift 值已改為**引用 `DesignTokens.*`**（由 tokens.json 生成）。方向是 **tokens.json（Figma）→ `npm run build` 重生 `DesignTokens.swift` → iOS 消費**。在 Figma 改這些值、跑 build、**重編 app 即生效**，不必手改 Swift。
> - **未接線群組**（**全部顏色** `AppColors`/`AppTheme`、`AppMotion`、`LineSpacing`、`AppSkin` 組合層）：仍是**手寫 Swift literal 為 SoT**，tokens.json 鏡像之。Figma 改這些**不會自動生效**，須手動改對應 Swift 再讓 drift check 對齊。
> 兩種 regime 都由 `ops/token_drift_check.py` 守：已接線者驗「iOS 的 `DesignTokens.*` 引用解析值 == tokens.json」，未接線者驗「iOS literal == tokens.json」。顏色刻意未接（精確 float + `WCAGContrastTests` 釘死對比值，須逐值證明無損才接）。

---

## 0. tokens.json 的真實結構（先看懂再進 Figma）

不是泛用範例，是**本 repo 實際的 branch**。每個 leaf 是標準 DTCG node：`$type` + `$value`（+ 本 repo 自加的 `$description` / `$swift` 指回 Swift 來源，Token Studio 會忽略未知 key，不影響匯入）。

| Branch | 內容 | DTCG `$type` | 範例 leaf |
|--------|------|--------------|-----------|
| `color.primitive` | 原始品牌色（含 light/dark 對） | `color` | `accent.light = #4d7396`、`brand-hero`、`info`、`success`、`destructive`、`warning`、`tint`、`chart-highlight` |
| `color.theme.{light,dark,sepia}` | 三主題的語意色 | `color` | `light.page-bg = #f7f6f3`、`card-bg`、`text-primary`、`divider`、`border-strong`… |
| `color.vocab-highlight.{light,dark,sepia}` | 詞彙高亮專用 | `color` | 各 mode 一色 |
| `space.scale` | 間距尺標 | `dimension` | `4 = 16px`、`hairline`/`micro`/`tiny` + `1`..`10` |
| `space.semantic` | 語意間距 | `dimension` | `card-padding`、`section-gap`、`chip-padding-h/v`… |
| `radius.scale` | 圓角尺標 | `dimension` | `none`/`xs`/`sm`/`md`/`lg`/`xl`/`pill` |
| `radius.semantic` | 語意圓角 | `dimension` | `card`、`overlay`、`control`、`chip` |
| `type.family` | 字族 | `fontFamily` | `serif`/`sans`/`italic`/`mono`/`display` |
| `type.scale` | 字級 | `dimension` | `body = 17px`、`hero`/`h1`/`h2`/`caption`… |
| `type.tracking` | 字距 | `dimension` | `tight`/`normal`/`wide`/`uppercase` |
| `type.leading` | 行高 | `number` | `display`/`heading`/`body`/`reading`/`caption` |
| `elevation.steps.z0..z4` | 陰影層級（巢狀 `opacity`/`blur`/`y`） | `number`+`dimension` | `z1.opacity = 0.03`、`z1.blur = 4px` |
| `motion.duration` | 動畫時長 | `time` | `quick`、`control`、`chip`、`progress`、`pulse` |
| `motion.easing` | 緩動曲線 | `string` | `emphasized-decelerate`、`follow`… |
| `motion.spring` | 彈簧參數（巢狀 `response`/`damping`） | `number` | `standard.response = 0.3`、`standard.damping = 0.75` |
| `motion.transition` / `motion.tap-feedback` | 轉場 / 點按回饋 | 混合 | `tap-feedback.scale-down` |
| `web-only.*` | **web 專屬**（iOS 無對應） | 混合 | `theme-color.on-success`、`invariant-value.blur-material`/`toggle-size`/`toggle-glyph` |

**關鍵分組（決定下面 Token Set 怎麼切）**：
- **mode-invariant**（不分主題）：`color.primitive`、`space.*`、`radius.*`、`type.*`、`elevation.*`、`motion.*` — 所有主題共用同一份。
- **mode-specific**（三主題各一份）：`color.theme.light` / `color.theme.dark` / `color.theme.sepia`，以及 `color.vocab-highlight.{light,dark,sepia}`。Token Studio 的 **Themes** 就是用來在這三者間切換。
- **web-only**：`web-only.*` 不影響 iOS，調它只動 web CSS。

---

## 1. 安裝 Figma + Tokens Studio plugin（免費）

1. 註冊 Figma 帳號 → 桌面版下載 <https://www.figma.com/downloads/>（或直接用瀏覽器版，plugin 一樣可跑）。
2. 開任一 Figma file（左上 **Figma 選單 → File → New design file**，或在檔案列表點 **+ Design file**）。Token Studio 需要一個 file 當載體。
3. 裝 plugin：頂部選單 **Menu（漢堡圖示）→ Plugins → Manage plugins…**，搜尋 **「Tokens Studio for Figma」**（作者 Jan Six / tokens.studio），按 **Install**。免費版（free tier）即足夠本流程。
4. 開啟：**Menu → Plugins → Tokens Studio for Figma**，跑起來會看到右側面板，分頁有 **Tokens / Themes / Inspect / Settings / Tools**。

> 免費版限制（誠實揭露，見 §4）：GitHub sync 只支援**單檔（single file）**、**手動 push/pull**，無團隊多人協作的進階 branch UI。對 solo + 單一 `tokens.json` 來說剛好夠用。

---

## 2. 匯入既有 tokens.json

plugin 第一次開是空的，要把 repo 的 `design-system/tokens.json` 餵進去。

1. Token Studio 面板右上 **三點選單（⋯）/ Tools → Load from file/folder or preset**，或 **Settings → Token Storage** 選 **Local document**（先用本機，GitHub sync 留到 §4）。
2. 選 **Import**（有些版本在 **Tools → Import → JSON**）。把 `design-system/tokens.json` 整檔貼上或選檔。
3. plugin 會把 JSON 解析成 token 樹。本檔是**單一 multi-set JSON**：頂層每個 branch（`color` / `space` / `radius` / `type` / `elevation` / `motion` / `web-only`）會被讀成 token，巢狀 group 保留。確認左側出現上面 §0 表列的所有 branch。
4. **匯入後立即驗證沒走樣**：隨手點 `color.theme.light.page-bg`，值應為 `#f7f6f3`；`space.scale.4` 應為 `16`（Token Studio 把 `16px` 正規化為純數，正常）。對得上即匯入成功。

> 本 repo 的 `$swift` / `$description` 是非標準 key，Token Studio 不認得會略過 — **不會報錯、不會丟值**，但 plugin 內編輯時也看不到它們。它們是 repo 端 drift check 的錨點，請勿在 Figma 刪除（見 §5 round-trip 注意）。

---

## 3. 組織 Token Sets + Themes（對齊真實 DTCG 結構）

Token Studio 兩個核心概念：**Token Set**（一組 token，可開關）、**Theme**（一組 set 的啟用組合 + enabled/source 狀態）。把它們對到 §0 的分組：

### 3a. 切 Token Sets
在 **Tokens** 分頁左側 set 列表，建議切成：

| Token Set 名 | 收哪些 branch | 性質 |
|--------------|--------------|------|
| `core` | `color.primitive`、`space`、`radius`、`type`、`elevation`、`motion` | mode-invariant，全主題共用 |
| `theme-light` | `color.theme.light` + `color.vocab-highlight.light` | light 專屬 |
| `theme-dark` | `color.theme.dark` + `color.vocab-highlight.dark` | dark 專屬 |
| `theme-sepia` | `color.theme.sepia` + `color.vocab-highlight.sepia` | sepia 專屬 |
| `web-only` | `web-only.*` | 僅影響 web CSS |

> 若匯入時整檔進了單一 set，可在 set 列表用 **拖曳 / Duplicate / 刪 token** 重組，或更簡單：先在 `tokens.json` 端不動，**只靠 Themes 控制啟用**（見 3b），set 切分屬 optional 整理。

### 3b. 建 Themes（light / dark / sepia）
切到 **Themes** 分頁 → **+ New theme**，建三個：`Light`、`Dark`、`Sepia`。每個 theme 對每個 set 設三態之一：

- **Enabled（source）** — 灰色：值可被引用但不直接套用（給 `core` 這種共用 set）。
- **Enabled** — 綠色：啟用且套用（給該主題對應的 `theme-*` set）。
- **Disabled** — 不參與。

| Theme | `core` | `theme-light` | `theme-dark` | `theme-sepia` | `web-only` |
|-------|--------|---------------|--------------|---------------|------------|
| Light | source | enabled | disabled | disabled | source |
| Dark | source | disabled | enabled | disabled | source |
| Sepia | source | disabled | disabled | enabled | source |

切換頂部 theme 下拉即可預覽三主題。這對應 iOS 端 `AppTheme.light/dark/sepia` 三套語意色，**結構一一對映**，不要多造主題。

> 注意：sepia 在 iOS 是真實第三主題（reader 用），不是 dark 的變體 — 三者地位平等，各自有完整的 `color.theme.*` 與 `vocab-highlight`。

---

## 4. （選用）GitHub Sync — 手動 push/pull

不接也行（§2 local 匯入 + 手動把改動貼回 `tokens.json` 即可）。要接的話：

1. **Settings → Token Storage → Add new → GitHub**。
2. 填：
   - **Personal Access Token**：GitHub → Settings → Developer settings → **Fine-grained / classic PAT**，給目標 repo 的 `repo`（讀寫）權限。
   - **Repository**：`MaxChen228/Books-Vocab`（本 KG monorepo 的 remote；注意本地目錄名是 `kg`，repo 名是 `Books-Vocab`，唯一命名例外）。
   - **Branch**：開一條 token 專用 branch，例如 `design-tokens-figma`（**不要**直接對 `main`）。
   - **File Path**：`design-system/tokens.json`（**單檔**，免費版限制）。
3. 存檔後 plugin 出現 **Push / Pull** 按鈕：
   - **Pull** = 從 GitHub 拉最新 `tokens.json` 覆蓋 plugin 內容。每次開工先 Pull，避免覆蓋掉別處（含 iOS 端對齊後 drift-check 同步回來的）改動。
   - **Push** = 把 plugin 內容寫回該 branch 的 `tokens.json`，**會跳 commit message 欄**，務必寫清楚（例：`tokens: bump theme.light.accent per Figma review`）。Push 後到 GitHub 開 PR。

**免費版誠實限制**：
- **單檔 only** — 無法同步 multi-file token 目錄，但本 repo 本就單一 `tokens.json`，無影響。
- **手動 push/pull** — 沒有自動同步；忘了 Pull 就可能蓋掉新值。養成**先 Pull 再改**習慣。
- **無自動 iOS 同步** — Push 只動 `tokens.json`，**絕不**碰 `ios/BooksBrowser/...` 的 Swift 檔。iOS 對齊永遠手動（見 §5）。
- plugin 不寫 PR description、不跑 CI — 那是 push 之後 GitHub / 本地的事。

---

## 5. Round-trip：Figma 改值 → 回 repo → CI 保持綠

完整一圈，**每一步都有 gate**：

```
Figma 改值
   └─ Push（手動，附 commit message）→ branch design-tokens-figma 的 tokens.json
        └─ 開 PR / 本地 checkout 該 branch
             └─ npm run build          # Style Dictionary 重生 ios/BooksBrowser/Models/DesignTokens.swift
             └─ ops/gen_web_tokens.py   # 重生 web CSS（dist + extension + backend/static 副本）
                  └─ ops/verify_design_system.sh   # 全 gate 必須綠
```

### 5a. 本地接手（必跑）
拉下 token branch 後：

```bash
npm run build                 # 重生 ios/BooksBrowser/Models/DesignTokens.swift（scalar bridge 產物）
uv run --no-project --python 3.13 python ops/gen_web_tokens.py   # 重生所有 web CSS
ops/verify_design_system.sh   # 一支跑齊所有 guard
```

`verify_design_system.sh` 內含的 gate（任一紅就擋）：
1. **`token_drift_check.py`** — tokens.json 必須與 iOS 對齊。**未接線群組（最易踩中）**：在 Figma 把 `color.theme.light.page-bg` 從 `#f7f6f3` 改掉、push 回來，但沒同步改 `AppTheme.light.pageBackground` → **drift check 紅**；正確順序是先在 iOS Swift 端拍板值再讓 tokens.json 鏡像。**已接線 scalar 群組**（radius/spacing/type-scale/tracking/elevation）相反：改 tokens.json → `npm run build` 重生 `DesignTokens.swift`，iOS 自動引用、drift check 自動對齊，**不需手改 Swift**（見 §5b）。
2. **`gen_web_tokens.py --check`** — 確認生成的 CSS 與 tokens.json 一致、無 stale 副本（漏跑生成就會紅）。
3. **`npm run build:check`**（Style Dictionary）— 確認 `DesignTokens.swift` 與 tokens.json 一致。
4. extension 純邏輯 test（`pure.test.js` / `icons.test.js`）。

### 5b. 哪些 Figma 改動會自動生效、哪些要手動
`DesignTokens.swift` 由 Style Dictionary 從 tokens.json 生成（`CGFloat`/`Double`/`String` 常數）。iOS runtime 對它的採用是**漸進**的：

- **已接線（Figma 真注入）**：`AppRadius` / `AppSpacing` scale（`s1`–`s10`/`hairline`/`micro`/`tiny`）/ `AppFonts.TypeScale` / `AppFonts.Tracking` / `AppElevation`（z0–z4 opacity·blur·y）已改為引用 `DesignTokens.*`。在 Figma 改這些 → Push → `npm run build` 重生 `DesignTokens.swift` → **重編 app 即生效**，無需手改 Swift。
- **未接線（仍須手動）**：**全部顏色**（`AppColors` 原色 + `AppTheme` 三主題語意色，精確 float + `WCAGContrastTests` 釘死對比，刻意不自動接）、`AppMotion`（彈簧/時長/緩動）、`AppFonts.LineSpacing`（與 web `type.leading` 語意不同）、`AppSkin` 組合層。改這些須**手動改對應 Swift**，再讓 drift check 確認 tokens.json 對齊。
- 因此本檔流程價值：對已接線 scalar 是**真正的 Figma→iOS 注入**；對未接線群組是**視覺化探索 + 提案值 + 版本化回 repo**。無論哪種，PR 內 `ops/verify_design_system.sh` 必須綠。

> **鐵律對映**：動 iOS UI 值前讀 `docs/sop/ui-design.md`（Token 禁令 / Motion 契約）；改設計系統值請走本流程，PR 內**同時**改 iOS Swift + tokens.json，並貼 `ops/verify_design_system.sh` 綠輸出（驗證先於宣稱）。

---

## 速查

| 我要做 | 怎麼做 |
|--------|--------|
| 第一次接 | §1 裝 plugin → §2 Local 匯入 tokens.json |
| 切三主題預覽 | §3b Themes：Light/Dark/Sepia |
| 把改動存回 repo | §4 GitHub Push（附 commit message）到 `design-tokens-figma` branch |
| 改完本地驗證 | §5a：`npm run build` → `gen_web_tokens.py` → `verify_design_system.sh` 全綠 |
| 真的要改 app 外觀 | 手動改 iOS Swift token 檔，tokens.json 對齊，drift check 綠（§5b） |

**相關文檔**：`docs/sop/ui-design.md`（UI 規範 / Token 禁令）、`design-system/sd.config.mjs`（Swift 產生規則）、`ops/gen_web_tokens.py`（web CSS 生成）、`ops/token_drift_check.py`（值層 gate）。
