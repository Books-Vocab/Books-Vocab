export const meta = {
  name: 'web-parity-surface-batch',
  description: '並行授權多個 web parity surface（各 agent 寫自己目錄 4 檔 + 回傳接線片段）',
  phases: [
    { title: 'Author', detail: 'one agent per surface: read SoT + measure refs + write 4 files' },
  ],
}

// ── 共享授權 GUIDE（每 agent 都收到）────────────────────────────────────────
const GUIDE = `
你是 KG web design-system parity 的 surface 作者。目標：把一個 iOS Catalog surface 1:1 鏡像成 web
元件，讓 Playwright 截圖與 iOS catalog ref PNG 在 RMSE < 0.25 內吻合。

## 工作根目錄
worktree：/Users/chenliangyu/worktrees/kg-web-ds
catalog ref 根：/Users/chenliangyu/project/kg/build/snapshots/catalog-full-20260611-130335/iPhone 15 Pro portrait/<RefDir>/
iOS app 原始碼根：/Users/chenliangyu/project/kg/ios/

## 你要產出（只在你自己的 surface 目錄，禁止碰共享檔）
web/src/surfaces/<surfaceId>/ 下：
  - <PascalName>Screen.tsx  — export function <PascalName>Screen({ scenario }: { scenario: ScenarioId<'<surfaceId>'> })
  - fixtures.ts             — 各 scenario 的資料（逐字對齊 iOS Scenarios 檔的合成資料）
  - <surfaceId>.css         — 視覺；token 一律走 design-system CSS 變數，禁裸視覺 literal（系統色/資料色例外，加行內 token-allow 註解）
  - icons.tsx               — 若需 SF 圖示，用 import { makeGlyph, makeFilledGlyph } from '../../shared/glyph'

**禁止**編輯 src/harness/scenarios.ts、src/harness/PhoneFrame.tsx、tools/parity-manifest.mjs、
design-system/parity/parity-baseline.json（這些由主線串接）。**禁止**跑 dev server / parity / git。

## 必做流程
1. 讀 iOS SoT（給你的 View + Scenarios 檔），逐 scenario 抓出資料與視圖樹。
2. 讀 2-3 個既有 web surface 當模板學慣例（強烈建議）：
   - 乾淨最小範例：web/src/surfaces/vocab-highlight-picker/
   - 卡片/overlay（mono 標題+divider+ghost button）：web/src/surfaces/collocation-explain/、link-reason-sheet/
   - grouped Form（nav+section+卡）：web/src/surfaces/notebook-edit/
   - 資料視覺化/grid/stack：web/src/surfaces/notebooks-stack/、vocab-review-progress-bar/
   - cover pattern 複用：web/src/surfaces/notebook-cover/icons.tsx（PatternOverlay/CirclesOverlay）
3. 量測你的每個 ref PNG（native 1179×2556，web 邏輯寬 393pt = ÷3）：
   - 透明判定：magick "<ref>.png" -alpha extract -format "%[fx:mean]" info:
     · alpha-mean ≈ 0（透明畫布，多為 component-isolated scene）→ manifest 需 transparent:true，CSS 加
       .phone-frame[data-surface='<id>']{background:transparent}（若 component crop 則加 [data-crop='component']）
     · alpha-mean = 1（不透明，多為 full-screen / grouped-bg scene）→ 不加 transparent flag
   - 關鍵顏色/位置：magick "<ref>.png" -format "%[pixel:p{x,y}]" info: 取色；掃描列找 band 邊界定位。
4. token 對照（web CSS 變數，定義在 src/styles/kg-tokens.css，先 grep 確認存在）：
   字級 --text-detail-word(27,mono) --text-body(17) --text-subhead(15,iOS typography.body) --text-caption(12,bold)
   間距 --sp-1=4 --sp-2=8 --sp-3=12 --sp-4=16 --sp-5=20 --sp-6=24 --sp-7=32；--section-gap=14；--inline-gap=8
   圓角 --radius-sm=6 --radius-card=8(md) --radius-lg=12 --radius-control=6
   色   --text-primary --text-secondary --text-tertiary --divider --sp-hairline(0.5px) --page-bg --card-bg
        --card-border --muted-fill --destructive --accent --tint --leading-heading(1.2)
   iOS 系統色（非品牌 token，用 token-allow literal）：systemGroupedBackground #F2F2F7、card 白 #fff、
   grouped card radius 10、systemGroupedBackground nav 等。
   字型：iOS AppFonts.sans→--font-sans、systemMono/mono→--font-mono；bold→font-weight 700。
   iOS typography.body = sans 15 = --text-subhead（非 --text-body=17，常見坑）。
   iOS caption = sans 12 **bold** → --text-caption + font-weight 700。
5. 顏色換算：iOS Color(red:g:b:) 用 Swift round()（half-away-from-zero）→ round(c*255)。
6. SwiftUI lineSpacing(n) = 額外加成 → CSS line-height: calc(1.2em + Npx)。
7. 字串：中文逐字對齊 iOS（含標點）。catalog scene 標題若為 DEBUG raw literal 直接照抄。

## 接線片段（回傳給主線，不要自己改共享檔）
- surfaceId：kebab-case，= 你的目錄名 = manifest params.surface = scenario key。
- scenarioIds：kebab-case 陣列，逐一對齊 iOS Scenario(...) 順序；首位 = 預設。
- importLine：PhoneFrame.tsx 的 import，例：import { WordEditScreen } from '../surfaces/word-edit/WordEditScreen'
- caseBlock：PhoneFrame switch case，例：case 'word-edit':\\n      return <WordEditScreen scenario={config.scenario} />
- manifestEntries：parity-manifest.mjs 的物件字面陣列字串（每 scenario 一個），每個含：
    { case: '<id>-<scenario>-light', params: { surface: '<id>', scenario: '<scenario>', appearance: 'light'[, crop: 'component'] },
      [transparent: true,] [crop: '.<selector>',] ref: { surface: '<RefSurfaceName>', scenario: '<RefScenarioName>', appearance: 'light' },
      note: '<一句中文說明> (light)' }
    · ref.surface / ref.scenario 必須**逐字**等於 catalog（addScenarios(of:) 名 + Scenario(...) 名）。
    · component crop（僅當該 scene 是 component-isolated 且你用了 crop selector）：params 加 crop:'component'、頂層加 crop:'.<surface-root-class>'，並在 CSS 用
      .phone-frame[data-crop='component'][data-surface='<id>']{background:transparent}。不確定就用全 phone-frame 透明（多數 .fill scene）。

## 品質自查（回傳前）
- 4 個檔都寫了、import 路徑正確、Screen 簽名用 ScenarioId<'<id>'>。
- fixtures 的 scenario key 與 scenarioIds 完全一致。
- 每個 ref 都量過 alpha-mean，transparent flag 一致。
- 沒碰任何共享檔。
`

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['surfaceId', 'scenarioIds', 'importLine', 'caseBlock', 'manifestEntries', 'filesWritten', 'transparent', 'notes', 'risks'],
  properties: {
    surfaceId: { type: 'string', description: 'kebab-case surface id = 目錄名 = manifest params.surface' },
    scenarioIds: { type: 'array', items: { type: 'string' }, description: 'kebab scenario ids，對齊 iOS Scenario 順序' },
    importLine: { type: 'string', description: 'PhoneFrame.tsx import 行' },
    caseBlock: { type: 'string', description: 'PhoneFrame switch case 區塊' },
    manifestEntries: { type: 'string', description: 'parity-manifest.mjs 物件字面陣列字串（逗號分隔，每 scenario 一個物件，可直接 splice）' },
    filesWritten: { type: 'array', items: { type: 'string' }, description: '實際寫入的檔案絕對路徑' },
    transparent: { type: 'boolean', description: '是否透明捕捉（任一 scene 透明即 true，並於 notes 說明 per-scene 差異）' },
    notes: { type: 'string', description: 'token 對照重點、alpha-mean 量測、特殊處理' },
    risks: { type: 'string', description: '可能 parity 不過的風險點 / 未解處' },
  },
}

// ── 目標 surface 清單（args 提供則用 args，否則用預設 batch-1）─────────────────
const DEFAULT_TARGETS = [
  {
    id: 'word-edit',
    refDir: 'Word_Edit',
    refSurface: 'Word Edit',
    sot: 'ios/BooksAndVocab/Views/Vocabulary/Scenes/WordEditSheet.swift + Debug/Scenarios/WordEditScenarios.swift',
    hint: 'grouped Form / sheet，結構近似 notebook-edit（強烈建議讀 web/src/surfaces/notebook-edit/ 當模板）。4 scenes: Populated / Empty explanation / Long content stress / Long word title。',
  },
  {
    id: 'vocab-calendar',
    refDir: 'Vocab_Calendar',
    refSurface: 'Vocab Calendar',
    sot: 'ios/BooksAndVocab/Views/Vocabulary/Components/VocabCalendarGrid.swift + Debug/Scenarios/VocabCalendarGridScenarios.swift',
    hint: '月曆 grid 元件（7 欄 day cell + intensity 著色）。多為 component-isolated 透明畫布——務必量 alpha-mean。5 scenes。',
  },
  {
    id: 'vocab-forecast',
    refDir: 'Vocab_Forecast',
    refSurface: 'Vocab Forecast',
    sot: 'ios/BooksAndVocab/Views/Vocabulary/Components/VocabForecastChart.swift + Debug/Scenarios/VocabForecastScenarios.swift',
    hint: '長條圖 / 預測圖元件。量 alpha-mean 決定透明。4 scenes（7-day / 14-day / Compact 30 / Sparse single spike）。',
  },
  {
    id: 'vocab-heatmap',
    refDir: 'Vocab_Heatmap',
    refSurface: 'Vocab Heatmap',
    sot: 'ios/BooksAndVocab/Views/Vocabulary/Components/VocabActivityHeatmap.swift + Debug/Scenarios/VocabActivityHeatmapScenarios.swift',
    hint: 'GitHub-style 活動熱圖（週×日 grid + graded 著色）。量 alpha-mean。5 scenes（Dense graded / Empty / No thresholds / Short range 8wk / Sparse）。',
  },
  {
    id: 'review-banner',
    refDir: 'Banners_·_Review',
    refSurface: 'Banners · Review',
    sot: 'ios/BooksAndVocab/Views/Vocabulary/Components/VocabReviewBanner.swift + Debug/Scenarios/BannerScenarios.swift',
    hint: 'review banner 元件。BannerScenarios 含「Banners · Review」(4) 與「Banners · Demo」(1)；兩者 ref 在不同目錄（Banners_·_Review / Banners_·_Demo）。把兩組都做進同一 surface（scenarioIds 用前綴區分，如 review-both / review-due / review-unlearned / review-large / demo-default），manifestEntries 的 ref.surface 各自填對。量 alpha-mean。',
    extraRefDirs: ['Banners_·_Demo'],
  },
  {
    id: 'vocab-add-link',
    refDir: 'Vocabulary_·_Add_Link',
    refSurface: 'Vocabulary · Add Link',
    sot: 'ios/BooksAndVocab/Views/Vocabulary/Scenes/AddLinkSheet.swift + Debug/Scenarios/VocabScenarios.swift（grep "Add Link"）',
    hint: 'card-link 候選清單 sheet。2 scenes（With candidates / No candidates）。量 alpha-mean。',
  },
  {
    id: 'vocab-linked-card',
    refDir: 'Vocabulary_·_Linked_Card',
    refSurface: 'Vocabulary · Linked Card',
    sot: 'ios/BooksAndVocab/Views/Vocabulary/Overlay/LinkedCardOverlayStack.swift + Debug/Scenarios/VocabScenarios.swift（grep "Linked Card"）',
    hint: 'linked card overlay。2 scenes（Single card / Stacked 3-deep）。量 alpha-mean。',
  },
]

// args 可能以 JSON 字串傳入（Workflow tool 的 args 欄位序列化）→ 先 parse。
let _argTargets = args
if (typeof _argTargets === 'string') {
  try { _argTargets = JSON.parse(_argTargets) } catch { _argTargets = null }
}
const TARGETS = Array.isArray(_argTargets) && _argTargets.length ? _argTargets : DEFAULT_TARGETS

phase('Author')
const results = await parallel(
  TARGETS.map((t) => () =>
    agent(
      `${GUIDE}

## 你的 surface
- surfaceId：${t.id}
- catalog ref 目錄：${t.refDir}${t.extraRefDirs ? '（另含：' + t.extraRefDirs.join(', ') + '）' : ''}
- catalog ref surface 名（addScenarios of）：${t.refSurface}
- iOS SoT：${t.sot}
- 提示：${t.hint}

先 ls catalog ref 目錄列出所有 scene PNG，逐一量 alpha-mean 與必要顏色；讀 iOS SoT 與 2-3 個 web 模板；
再寫 4 個檔到 web/src/surfaces/${t.id}/。完成後回傳結構化接線片段（manifestEntries 的 ref 名逐字對齊 catalog）。`,
      { label: `author:${t.id}`, phase: 'Author', schema: SCHEMA, agentType: 'general-purpose' },
    ),
  ),
)

return results.filter(Boolean)
