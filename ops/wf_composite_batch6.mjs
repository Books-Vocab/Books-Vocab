export const meta = {
  name: 'wf-composite-batch6',
  description: 'Build the next web design-system tier (composite/molecule components) mirroring iOS SoT, in parallel; each agent writes its own isolated surface dir and returns shared-file integration snippets for the main loop to apply serially.',
  phases: [{ title: 'Build composites', detail: 'one agent per composite surface: read iOS SoT → write web component dir → return integration snippets' }],
}

// Batch-2 (composite layer). 3 surfaces, 12 scenes — each exercises a known,
// distinct capture pattern so the composite tier is validated cleanly:
//   - banner-review     .fillH  TRANSPARENT  tight crop=component   (atom pattern)
//   - collocation-explain .fill TRANSPARENT  full phone-frame       (vocab-empty-state pattern)
//   - kg-empty-state    .fill   OPAQUE(page-bg) full phone-frame    (screen pattern, new)
// Agents write ONLY their own web/src/surfaces/<dir>/ and RETURN shared-file deltas
// as strings; the main loop integrates tokens.json / scenarios.ts / PhoneFrame.tsx /
// parity-manifest.mjs serially and runs the single serial parity bless.
const WT = '/Users/chenliangyu/worktrees/kg-web-ds'

// batch-3: Sync (.fill opaque page-bg full-frame, safe) / Notebooks·Card
// (opaque-on-page-bg tight, low-contrast edge) / KG Vocab Row (WordRow molecule,
// transparent tight, reusable). 3 capture modes exercised.
// batch-6: Podcast cards (series card / continue card / episode row).
// Mixed opaque/transparent per probe.
const BATCH = [
  { surface: 'Podcast Series Card', dir: 'podcast-series-card', scenarios: ['A11y3', 'Long host', 'Narrow', 'Normal'] },
  { surface: 'Podcast Continue Card', dir: 'podcast-continue-card', scenarios: ['Completed (Replay)', 'Free Preview', 'Fresh (Play)', 'Gated (Sign In / Upgrade / Unavailable)', 'In Progress (Resume)'] },
  { surface: 'Podcast · Episode Row', dir: 'podcast-episode-row', scenarios: ['Variants'] },
]

const BUILD_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['surfaceId', 'dirName', 'filesWritten', 'scenarioEntry', 'phoneFrameImport', 'phoneFrameCase', 'manifestCasesJs', 'tokensNeeded', 'scenarios', 'capture', 'notes'],
  properties: {
    surfaceId: { type: 'string', description: 'kebab surface id used in SURFACE_SCENARIOS and manifest params, e.g. banner-review' },
    dirName: { type: 'string', description: 'the web/src/surfaces/<dir> directory name created' },
    filesWritten: { type: 'array', items: { type: 'string' }, description: 'absolute paths of files written' },
    scenarioEntry: { type: 'string', description: "exact line(s) to insert into SURFACE_SCENARIOS, e.g.  'banner-review': ['both-types', 'due-only', ...]," },
    phoneFrameImport: { type: 'string', description: 'the import line for PhoneFrame.tsx' },
    phoneFrameCase: { type: 'string', description: "the switch case block for SurfaceView, e.g.   case 'banner-review':\\n    return <BannerReviewScreen scenario={config.scenario} />" },
    manifestCasesJs: { type: 'string', description: 'the JS object literal block(s) of parity-manifest cases (one per scenario), ready to splice into the PARITY array. Shape MUST match the capture mode (see RECIPE step 4).' },
    tokensNeeded: {
      type: 'array',
      description: 'NEW design tokens this component needs that are NOT already in design-system/tokens.json (empty if all exist). Each maps to an iOS SoT literal. NOTE the system colors system-{red,blue,green,purple,indigo,secondary-label} + mono-label + micro-gap + chrome-button-size + tab-selector-height + tone-chip-padding-h/v + row-padding-v + action-button-padding-v + progress-bar-* + toolbar-badge-padding-* + empty-state-stack + tracking.label ALREADY EXIST from batch-1; do not re-add.',
      items: {
        type: 'object', additionalProperties: false,
        required: ['group', 'name', 'value', 'swift', 'description'],
        properties: {
          group: { type: 'string', description: "tokens.json group: 'space.semantic' | 'web-only.theme-color' | 'type.scale' | etc." },
          name: { type: 'string' }, value: { type: 'string' }, swift: { type: 'string' }, description: { type: 'string' },
        },
      },
    },
    scenarios: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['title', 'id'],
        properties: { title: { type: 'string', description: 'exact iOS catalog scenario title' }, id: { type: 'string', description: 'web scenario id (kebab)' } },
      },
    },
    capture: {
      type: 'object', additionalProperties: false,
      required: ['mode', 'transparent'],
      properties: {
        mode: { type: 'string', description: "'full-frame' (catalog ref ≈1179x2556, layout .fill → capture whole phone-frame, NO crop) | 'component' (tight ref e.g. 1179x342, layout .fillH/.compressed → crop to component surface)" },
        transparent: { type: 'boolean', description: 'true if catalog ref corner alpha=0; false if opaque (corner is a bg color → map to a bg token, no transparent flag)' },
      },
    },
    notes: { type: 'string', description: 'fidelity notes, token mappings, capture-mode reasoning, any uncertainty for the integrator/reviewer' },
  },
}

const RECIPE = `
You are building ONE web component that pixel-mirrors an iOS SwiftUI surface, as part of the KG web design system. Work in the worktree ${WT} (branch web-ds). Use ABSOLUTE paths.

COMPLETED reference examples to imitate (read the ones matching your capture mode):
  - transparent component crop (atom):   ${WT}/web/src/surfaces/vocab-sort-pill? -> actually ${WT}/web/src/surfaces/vocab-shell/{VocabSortPillScreen.tsx,vocab-shell.css} and ${WT}/web/src/surfaces/vocab-tone-chip/
  - transparent FULL-FRAME (.fill):      ${WT}/web/src/surfaces/vocab-empty-state/{VocabEmptyStateScreen.tsx,vocab-empty-state.css}  (full phone-frame, content vertically centered, phone-frame transparent)
  - opaque FULL-FRAME (screen):          ${WT}/web/src/surfaces/bookshelf/  (full phone-frame, opaque page-bg, no crop, no transparent)
  - harness wiring:                      ${WT}/web/src/harness/scenarios.ts + PhoneFrame.tsx ; manifest ${WT}/web/tools/parity-manifest.mjs

CRITICAL CAPTURE-MODE DECISION (do this FIRST, it dictates everything):
  Find your catalog ref PNG. Catalog root = newest ${WT}/build/snapshots/catalog-full-* (if ${WT}/build is empty use /Users/chenliangyu/project/kg/build/snapshots/catalog-full-20260611-130335).
  PNG path = "<root>/iPhone 15 Pro portrait/<surface spaces→underscores, · kept>/<scenario title>.png".
  Run:  magick "<png>" -format "dims=%wx%h corner=%[pixel:p{2,2}]\\n" info:
  - dims ≈ 1179x2556  → layout .fill → FULL-FRAME capture: NO manifest crop selector, params has NO crop:'component'. Surface CSS fills the phone-frame (width/height 100%) and positions content as the .fill scene does (usually vertically centered for empty-states; top-aligned for editors — check the ref image visually with Read).
  - dims tight (e.g. 1179x342, 252x209) → layout .fillH/.compressed → COMPONENT capture: manifest top-level crop:'.<your-surface-class>' AND params crop:'component'.
  - corner alpha=0 (srgba(...,0))  → TRANSPARENT: manifest transparent:true; CSS makes the captured element transparent (full-frame → .phone-frame[data-surface=<id>]{background:transparent}; component → .phone-frame[data-crop='component'][data-surface=<id>]{background:transparent}).
  - corner OPAQUE (e.g. srgba(247,246,243,1)=page-bg #f7f6f3) → NO transparent flag; the surface background IS that bg token (page-bg/stage-bg/card-bg — sample & map, do not hardcode hex). Full-frame opaque = exactly the bookshelf screen pattern.

STEPS:
1. iOS SoT: grep ios/BooksAndVocab/Debug/Scenarios/ for your surface to find the *Scenarios.swift; read each scenario's props/layout. Then grep ios/BooksAndVocab for the component struct(s) and read the view tree + modifiers + appSkin tokens.
2. Resolve tokens to web CSS vars (generated list: ${WT}/web/src/styles/kg-tokens.css; SoT map: ${WT}/design-system/tokens.json with $swift provenance). VERIFY each iOS token's REAL value from Swift (ios/BooksAndVocab/Models/AppSkin+BaseValues.swift baseSpacing/baseMetrics, AppMetrics.swift, DesignTokens.swift) — DO NOT guess from a similar var name. KNOWN FOOTGUNS: AppSpacing.microGap=6 → var(--micro-gap), NOT var(--sp-micro)(=2); chip paddings: compactChip 6/3=--compact-chip-padding-* , Spacing.chip 10/6=--tone-chip-padding-* , AppTagMetrics 10/5=--chip-padding-* . SwiftUI system colors (Color.red/.blue/.green/.purple/.indigo/.secondary) ALREADY have tokens: var(--system-red/-blue/-green/-purple/-indigo/-secondary-label). mono 10pt label → var(--text-mono-label). If a needed token has NO var, return it in tokensNeeded with correct $swift+value; for SwiftUI system colors not yet tokenised use group 'web-only.theme-color' with light/sepia/dark (Apple nominal sRGB). NEVER hardcode a visual literal, NEVER reuse a wrong-meaning var.
3. SF Symbol icons → ${WT}/web/src/shared/glyph makeGlyph (24-grid). Reuse existing glyphs (grep web/src/surfaces/*/icons.tsx) before drawing new.
4. Write your files under ${WT}/web/src/surfaces/<dirName>/ ONLY: <PascalName>Screen.tsx (props {scenario}), fixtures.ts, icons.tsx (if needed), <kebab>.css. ALL visual values via design-system CSS vars, ZERO literals except structural (flex, 999px capsule, box-sizing) and the scene-wrapper .padding(24) literal (rig convention, mirror vocab-sort-pill). Match the iOS view tree faithfully. KNOWN FOOTGUN: mono-font badges need line-height:1 (iOS Text is tight; web default leading inflates the box). Web user-facing strings: raw text is fine (no i18n lint on web).
5. DO NOT edit any shared file (scenarios.ts, PhoneFrame.tsx, parity-manifest.mjs, tokens.json). DO NOT run parity. RETURN the integration snippets (schema fields). manifestCasesJs per scenario shape:
   - full-frame:  { case:'<id>-<sid>-light', params:{ surface:'<id>', scenario:'<sid>', appearance:'light' }, [transparent:true,] ref:{ surface:'<exact catalog surface>', scenario:'<exact catalog title>', appearance:'light' }, note:'...' }   (NO crop)
   - component:   { case:'<id>-<sid>-light', params:{ surface:'<id>', scenario:'<sid>', appearance:'light', crop:'component' }, crop:'.<your-surface-class>', [transparent:true,] ref:{...}, note:'...' }

Return the BUILD_SCHEMA object. Be meticulous about iOS fidelity AND capture mode — a reviewer will diff against the catalog PNG and the iOS source, and parity (with anti-Goodhart ceiling) will judge it.`

phase('Build composites')

const results = await parallel(
  BATCH.map((b) => () =>
    agent(
      `${RECIPE}\n\n=== YOUR TARGET ===\nsurface (catalog): ${b.surface}\nsurfaceId/dirName: ${b.dir}\nscenarios (catalog titles, all light): ${JSON.stringify(b.scenarios)}\n\nBuild it now. FIRST run the magick corner+dims probe to fix your capture mode, then read iOS SoT + the matching reference example, then write your surface dir, then return the integration snippets.`,
      { label: `composite:${b.dir}`, phase: 'Build composites', schema: BUILD_SCHEMA },
    ).then((r) => (r ? { ...r, _surface: b.surface, _scenarios: b.scenarios } : null)),
  ),
)

return { built: results.filter(Boolean), failed: results.filter((r) => !r).length, total: BATCH.length }
