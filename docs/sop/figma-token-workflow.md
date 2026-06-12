<!-- doc-meta
tier: sop
authority: derived
update_trigger: sop-change
scope:
  - design-system/
  - ops/
verified_against: f0d37ca4
-->
# Figma Token Studio Workflow（零基礎 solo 設計師接 tokens.json）

把 `design-system/tokens.json`（W3C DTCG 格式）接進 Figma 的 **Tokens Studio for Figma** plugin，讓設計師能在 Figma 裡視覺化、調整 design token，再回流到 repo。本檔給**完全沒用過 Figma** 的單人開發者，照步驟做即可。

> **先理解權威方向（接線後分兩種，不可混淆）**：
> - **已接線 scalar 群組**（`AppRadius` / `AppSpacing` scale / `AppFonts.TypeScale` / `AppFonts.Tracking` / `AppElevation` / `AppMotion` 的 duration·spring·tap-feedback）：這些 Swift 值已改為**引用 `DesignTokens.*`**（由 tokens.json 生成）。方向是 **tokens.json（Figma）→ `npm run build` 重生 `DesignTokens.swift` → iOS 消費**。在 Figma 改這些值、跑 build、**重編 app 即生效**，不必手改 Swift。
> - **未接線群組**（**全部顏色** `AppColors`/`AppTheme`、`AppMotion` 的 easing/transition 與無 token 對應的 spring 成員、`LineSpacing`、`AppSkin` 組合層）：仍是**手寫 Swift literal 為 SoT**，tokens.json 鏡像之。Figma 改這些**不會自動生效**，須手動改對應 Swift 再讓 drift check 對齊。
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
| `web-only.*` | **web 專屬**（iOS 無對應） | 混合 | `theme-color.on-success`、`system-{red,blue,…}`（SwiftUI 系統色）、`invariant-value.blur-material`/`toggle-size`/`toggle-glyph` |

> **⚠️ CSS var 命名陷阱（寫 web 元件鏡像 iOS 時最易踩）**：`space.scale.micro`→`--sp-micro`(**2px**) 與 `space.semantic.micro-gap`→`--micro-gap`(**6px**) 名稱相近但值不同。iOS 讀 `AppSpacing.microGap` / `appSkin.spacing.microGap`(=6) 一律對應 **`--micro-gap`**，**勿**誤用 `--sp-micro`(=`Scale.micro`=2)。同理 chip padding 三組勿混：`compact-chip-*`(6/3) / `tone-chip-*`=`Spacing.chip*`(10/6) / `chip-padding-*`=`AppTagMetrics`(10/5)。token 真值一律核 `ios/.../AppSkin+BaseValues.swift`，別靠名稱猜。

**關鍵分組（決定下面 Token Set 怎麼切）**：
- **mode-invariant**（不分主題）：`color.primitive`、`space.*`、`radius.*`、`type.*`、`elevation.*`、`motion.*` — 所有主題共用同一份。
- **mode-specific**（三主題各一份）：`color.theme.light` / `color.theme.dark` / `color.theme.sepia`，以及 `color.vocab-highlight.{light,dark,sepia}`。由 repo sidecar 預投影成可切換的三 theme（見 §3，免 Pro）。
- **web-only**：`web-only.*` 不影響 iOS，調它只動 web CSS。

---

## 1. 安裝 Figma + Tokens Studio plugin（免費）

1. 註冊 Figma 帳號 → 桌面版下載 <https://www.figma.com/downloads/>（或直接用瀏覽器版，plugin 一樣可跑）。
2. 開任一 Figma file（左上 **Figma 選單 → File → New design file**，或在檔案列表點 **+ Design file**）。Token Studio 需要一個 file 當載體。
3. 裝 plugin：頂部選單 **Menu（漢堡圖示）→ Plugins → Manage plugins…**，搜尋 **「Tokens Studio for Figma」**（作者 Jan Six / tokens.studio），按 **Install**。免費版（free tier）即足夠本流程。
4. 開啟：**Menu → Plugins → Tokens Studio for Figma**，跑起來會看到右側面板，分頁有 **Tokens / Themes / Inspect / Settings / Tools**。

> 免費版限制（誠實揭露，見 §4）：GitHub sync 只支援**單檔（single file）**、**手動 push/pull**，無團隊多人協作的進階 branch UI。對 solo + 單一 `tokens.json` 來說剛好夠用。**另注意：plugin 內「建立 / 切換 Themes」是 Pro-only** — 但本流程用 repo 端預投影 sidecar（`design-system/.tokens-studio/`，見 §3）繞過，Free 即可拿到三主題結構。

---

## 2. 匯入既有 tokens.json

plugin 第一次開是空的，要把 repo 的 `design-system/tokens.json` 餵進去。

1. Token Studio 面板 **Settings → Token Storage** 選 **Local document**（先用本機；GitHub sync 留到 §4）。
2. **匯入 sidecar 投影資料夾（推薦）**：**Tools → Load from file/folder**，選 `design-system/.tokens-studio/tokens/` **整個資料夾**。它含預投影的 `core`/`theme-light`/`theme-dark`/`theme-sepia` 四 set + `$themes.json`/`$metadata.json` → 直接得三主題結構（見 §3），免 Pro。
   - *退而求其次*：import 單檔 `design-system/tokens.json`（整檔進單一 set，**只能看值、無 theme 切換**）。
3. plugin 解析成 token 樹，左側出現 §0 表列的 branch（巢狀 group 保留）。
4. **匯入後立即驗證沒走樣**：點 `color.theme.page-bg`，Light 應為 `#f7f6f3`、切 Dark 應為 `#191919`；`space.scale.4` 應為 `16`（plugin 把 `16px` 正規化為純數，正常）。對得上即成功。

> 本 repo 的 `$swift` / `$description` 是非標準 key，Token Studio 不認得會略過 — **不會報錯、不會丟值**，但 plugin 內編輯時也看不到它們。它們是 repo 端 drift check 的錨點，請勿在 Figma 刪除（見 §5 round-trip 注意）。

---

## 3. 三主題結構：已由 repo sidecar 預先投影（免 Pro）

> **重要更正（舊版本檔寫錯）**：Tokens Studio 在 plugin 內**建立 / 編輯 Themes 是 Pro-only**（官方原文："You'll need a Pro licence for the Tokens Studio Plugin to use the Themes feature"）。本 repo **繞過它** — 不在付費 UI 手動建 theme，而是由 `ops/gen_figma_sets.py` 從 `tokens.json` **單向投影**出預先寫好的 Tokens Studio sidecar（`design-system/.tokens-studio/tokens/`），內含 `core` / `theme-light` / `theme-dark` / `theme-sepia` 四個 set + 合法的 `$themes.json` / `$metadata.json`。§2 import 那個資料夾就直接拿到三主題結構，**無需手動切 set、無需 Pro 建 theme**。

sidecar set 佈局（**生成物，勿手改**；SoT 永遠是 `design-system/tokens.json`）：

| set | 收哪些 | `$themes.json` 狀態 |
|-----|--------|------|
| `core` | `color.primitive` + `space`/`radius`/`type`/`elevation`/`motion` | 三主題皆 **source**（可被引用、不直接套用） |
| `theme-light` | `color.theme.light` + `vocab-highlight.light`（路徑收斂為 `color.theme.*` / `color.vocab-highlight` 讓三 set 同名可切換） | Light 主題 enabled，其餘 disabled |
| `theme-dark` | 同上 dark | Dark enabled |
| `theme-sepia` | 同上 sepia | Sepia enabled |

三主題一一對映 iOS `AppTheme.light/dark/sepia`，**結構對齊，不要多造主題**。sepia 是真實第三主題（reader 用），非 dark 變體，三者地位平等。`web-only.*` 不投影進 sidecar（只影響 web CSS，Figma 無需管理）。

> **Free plan 能否「一鍵切換」預載 themes 待你實測**：§2 import 後切頂部 theme 下拉，看 `color.theme.page-bg` 是否隨主題在 light `#f7f6f3` ↔ dark `#191919` 變動。最壞情況 — Free 只列出三 theme 名、不能即時切換預覽；但 **web CSS 端三主題本就由 `tokens.json` 生成（已是注入）、版本化也已達成**，升 Pro 後切換即生效，**無任何倒退**。
> `tokens.json` 改了就重跑 `python ops/gen_figma_sets.py` 更新 sidecar（`--check` 已進 `ops/verify_design_system.sh` 防 stale）。sidecar 是**唯讀視圖**，回流走 `tokens.json`（見 §5 顏色 gate）。

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
- **無自動 iOS 同步** — Push 只動 `tokens.json`，**絕不**碰 `ios/BooksAndVocab/...` 的 Swift 檔。iOS 對齊永遠手動（見 §5）。
- plugin 不寫 PR description、不跑 CI — 那是 push 之後 GitHub / 本地的事。

---

## 5. Round-trip：Figma 改值 → 回 repo → CI 保持綠

完整一圈，**每一步都有 gate**：

```
Figma 改值
   └─ Push（手動，附 commit message）→ branch design-tokens-figma 的 tokens.json
        └─ 開 PR / 本地 checkout 該 branch
             └─ npm run build          # Style Dictionary 重生 ios/BooksAndVocab/Models/DesignTokens.swift
             └─ ops/gen_web_tokens.py   # 重生 web CSS（dist + extension + backend/static + web/src/styles 副本）
                  └─ ops/verify_design_system.sh   # 全 gate 必須綠
```

### 5a. 本地接手（必跑）
拉下 token branch 後：

```bash
npm run build                 # 重生 ios/BooksAndVocab/Models/DesignTokens.swift（scalar bridge 產物）
uv run --no-project --python 3.13 python ops/gen_web_tokens.py    # 重生所有 web CSS
uv run --no-project --python 3.13 python ops/gen_figma_sets.py    # 重生 Tokens Studio sidecar（.tokens-studio/）
ops/verify_design_system.sh   # 一支跑齊所有 guard
```

`verify_design_system.sh` 內含的 gate（任一紅就擋）：
1. **`token_drift_check.py`** — tokens.json 必須與 iOS 對齊。**未接線群組（最易踩中）**：在 Figma 把 `color.theme.light.page-bg` 從 `#f7f6f3` 改掉、push 回來，但沒同步改 `AppTheme.light.pageBackground` → **drift check 紅**；正確順序是先在 iOS Swift 端拍板值再讓 tokens.json 鏡像。**已接線 scalar 群組**（radius/spacing/type-scale/tracking/elevation）相反：改 tokens.json → `npm run build` 重生 `DesignTokens.swift`，iOS 自動引用、drift check 自動對齊，**不需手改 Swift**（見 §5b）。
2. **`gen_web_tokens.py --check`** — 確認生成的 CSS 與 tokens.json 一致、無 stale 副本（漏跑生成就會紅）。
3. **`npm run build:check`**（Style Dictionary）— 確認 `DesignTokens.swift` 與 tokens.json 一致。
4. extension 純邏輯 test（`pure.test.js` / `icons.test.js`）。

### 5b. 哪些 Figma 改動會自動生效、哪些要手動
`DesignTokens.swift` 由 Style Dictionary 從 tokens.json 生成（`CGFloat`/`Double`/`String` 常數）。iOS runtime 對它的採用是**漸進**的：

- **已接線（Figma 真注入）**：`AppRadius` / `AppSpacing` scale（`s1`–`s10`/`hairline`/`micro`/`tiny`）/ `AppFonts.TypeScale` / `AppFonts.Tracking` / `AppElevation`（z0–z4 opacity·blur·y）/ `AppMotion` duration（quick·control·chip·progress·indicator·breathing·subtle-breath）·spring（**全部具參數 spring**：standard·emphasized·press·content-reveal·modal-swap·relaxed·button·review-reveal·review-navigation·swipe-snap-back·swipe-fling·swipe-tracking·feedback-button·celebration-bounce·sheet-content-appear·tap-feedback 的 response/damping，含 `interactiveSpring`）·`TapFeedback`（scaleDown·opacityDip）已改為引用 `DesignTokens.*`。在 Figma 改這些 → Push → `npm run build` 重生 `DesignTokens.swift` → **重編 app 即生效**，無需手改 Swift。
- **未接線（仍須手動）**：**全部顏色**（`AppColors` 原色 + `AppTheme` 三主題語意色，精確 float + `WCAGContrastTests` 釘死對比，刻意不自動接）、`AppMotion` 的 **easing**（tokens 是 cubic-bezier 字串，iOS `timingCurve` 收 4×Double + 無對應的 duration，型別不橋接）/ **transition**（複合 `AnyTransition`）/ `systemSpring`·`feedbackPulse`（`Animation.spring()` 平台預設、無顯式參數可入 token）、`AppFonts.LineSpacing`（與 web `type.leading` 語意不同）、`AppSkin` 組合層。改這些須**手動改對應 Swift**，再讓 drift check 確認 tokens.json 對齊。
- 因此本檔流程價值：對已接線 scalar 是**真正的 Figma→iOS 注入**；對未接線群組是**視覺化探索 + 提案值 + 版本化回 repo**。無論哪種，PR 內 `ops/verify_design_system.sh` 必須綠。

> **鐵律對映**：動 iOS UI 值前讀 `docs/sop/ui-design.md`（Token 禁令 / Motion 契約）；改設計系統值請走本流程，PR 內**同時**改 iOS Swift + tokens.json，並貼 `ops/verify_design_system.sh` 綠輸出（驗證先於宣稱）。

### 5c. 顏色回流 gate（比 scalar 多兩道，務必走完）
顏色是**未接線群組**（iOS literal 為 SoT，精確 float + `WCAGContrastTests` 釘死對比 + 多建構子 + opacity 疊加色 hex 存不了 → 刻意不自動接）。在 Figma 改色是**提案**不是直接生效，比 scalar 多兩道 gate：

1. Figma（Tokens Studio）改 `color.theme.*` 值，三主題切換確認視覺。
2. **Push 只動 `tokens.json`**（單檔 sync），**絕不碰 `ios/` Swift**。
3. 本地 checkout branch → **手動把新色值填進對應 iOS Swift**：`AppColors.swift`（原色）或 `AppTheme.swift`（三主題語意色）。顏色未接線，**iOS literal 才是 SoT**，tokens.json 鏡像它。
4. `ops/token_drift_check.py` — 顏色 literal 必須 == tokens.json（沒對齊就紅）。
5. **`./ops/ios_test.sh` 搜 `WCAGContrast`** — iOS 對比測試 gate；改色可能讓對比掉出無障礙門檻而**紅**，紅就退回（這正是顏色不自動接的根因）。
6. `ops/gen_web_tokens.py` 重生 web CSS（顏色那端是真注入，受惠）→ `verify_design_system.sh` 全綠 → 開 PR。

> 心智模型一句話：**在 Figma 改色 = 提案一個新色；要生效得過 drift check + iOS WCAG 對比測試兩道 gate，沒過就退回。** `vocab-highlight` 是 CSS gradient 字串，color picker 不能視覺編輯，維持唯讀展示。

---

## 速查

| 我要做 | 怎麼做 |
|--------|--------|
| 第一次接 | §1 裝 plugin → §2 import `.tokens-studio/tokens/` 資料夾（得三主題） |
| 切三主題預覽 | §3 sidecar 三 theme（import `.tokens-studio` 資料夾即得；Free 一鍵切換待實測） |
| 改顏色 | §5c 顏色 gate：提案 → 手填 iOS literal → drift + WCAG 測試 → PR |
| 把改動存回 repo | §4 GitHub Push（附 commit message）到 `design-tokens-figma` branch |
| 改完本地驗證 | §5a：`npm run build` → `gen_web_tokens.py` → `gen_figma_sets.py` → `verify_design_system.sh` 全綠 |
| 真的要改 app 外觀 | 手動改 iOS Swift token 檔，tokens.json 對齊，drift check 綠（§5b/5c） |

**相關文檔**：`docs/sop/ui-design.md`（UI 規範 / Token 禁令）、`design-system/sd.config.mjs`（Swift 產生規則）、`ops/gen_web_tokens.py`（web CSS 生成）、`ops/token_drift_check.py`（值層 gate）。
