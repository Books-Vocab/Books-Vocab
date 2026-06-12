export const meta = {
  name: 'wf-vocab-atoms',
  description: 'Build the Vocab Shell/Components primitive (atom) layer as web components mirroring iOS SoT, in parallel; each agent writes its own isolated surface dir and returns shared-file integration snippets for the main loop to apply serially.',
  phases: [{ title: 'Build atoms', detail: 'one agent per Vocab primitive: read iOS SoT → write web component dir → return integration snippets' }],
}

// 12 surfaces, 28 light scenes. Each is an independent surface dir (no cross-file
// conflict). Agents write ONLY their own web/src/surfaces/<dir>/ and RETURN the
// shared-file deltas as strings — the main loop integrates tokens.json,
// scenarios.ts, PhoneFrame.tsx, parity-manifest.mjs serially (no races) and runs
// the single serial parity bless.
const WT = '/Users/chenliangyu/worktrees/kg-web-ds'

const BATCH = [
  { surface: 'Vocab Shell · Accessory Icon Button', dir: 'vocab-accessory-icon-button', scenarios: ['Default fill'] },
  { surface: 'Vocab Shell · Slider Row', dir: 'vocab-slider-row', scenarios: ['Interactive'] },
  { surface: 'Vocab Components · Tone Chip', dir: 'vocab-tone-chip', scenarios: ['Long text', 'Variants'] },
  { surface: 'Vocab Shell · Chrome Icon Button', dir: 'vocab-chrome-icon-button', scenarios: ['Close', 'Toned (filter)'] },
  { surface: 'Vocab Shell · Inline Action Button', dir: 'vocab-inline-action-button', scenarios: ['Accent default', 'Toned'] },
  { surface: 'Vocab Shell · Search Field', dir: 'vocab-search-field', scenarios: ['Empty · prompt visible', 'With query'] },
  { surface: 'Vocab Shell · Section Header', dir: 'vocab-section-header', scenarios: ['Icon + trailing count', 'Title only'] },
  { surface: 'Vocab Components · Review Progress Bar', dir: 'vocab-review-progress-bar', scenarios: ['Detail only (no bar)', 'Over 100% (clamped)', 'Ratios'] },
  { surface: 'Vocab Shell · Review CTA Pill', dir: 'vocab-review-cta-pill', scenarios: ['Both types (menu)', 'Due only', 'Unlearned only'] },
  { surface: 'Vocab Shell · Tab Selector', dir: 'vocab-tab-selector', scenarios: ['No counts · unlearned selected', 'With counts · due selected', 'Zero counts · reviewed selected'] },
  { surface: 'Vocab Shell · Toolbar Glyph', dir: 'vocab-toolbar-glyph', scenarios: ['Badge stress (99+)', 'Plain', 'With badge'] },
  { surface: 'Vocab Components · Empty State', dir: 'vocab-empty-state', scenarios: ['Card — no action', 'Card — with action', 'Content — basic', 'Content — guidance + action'] },
]

const BUILD_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['surfaceId', 'dirName', 'filesWritten', 'scenarioEntry', 'phoneFrameImport', 'phoneFrameCase', 'manifestCasesJs', 'tokensNeeded', 'scenarios', 'transparent', 'notes'],
  properties: {
    surfaceId: { type: 'string', description: 'kebab surface id used in SURFACE_SCENARIOS and manifest params, e.g. vocab-tone-chip' },
    dirName: { type: 'string', description: 'the web/src/surfaces/<dir> directory name created' },
    filesWritten: { type: 'array', items: { type: 'string' }, description: 'absolute paths of files written' },
    scenarioEntry: { type: 'string', description: "exact line(s) to insert into SURFACE_SCENARIOS, e.g.  'vocab-tone-chip': ['long-text', 'variants']," },
    phoneFrameImport: { type: 'string', description: 'the import line for PhoneFrame.tsx' },
    phoneFrameCase: { type: 'string', description: "the switch case block for SurfaceView, e.g.   case 'vocab-tone-chip':\\n    return <VocabToneChipScreen scenario={config.scenario} />" },
    manifestCasesJs: { type: 'string', description: 'the JS object literal block(s) of parity-manifest cases (one per scenario), each with case/params/crop/transparent/ref/note, ready to splice into the PARITY array' },
    tokensNeeded: {
      type: 'array',
      description: 'NEW design tokens this component needs that are NOT already in design-system/tokens.json (empty if all needed tokens already exist). Each maps to an iOS SoT literal.',
      items: {
        type: 'object', additionalProperties: false,
        required: ['group', 'name', 'value', 'swift', 'description'],
        properties: {
          group: { type: 'string', description: "tokens.json group: 'space.semantic' | 'color.theme.<t>' | etc. Almost always space.semantic for spacing." },
          name: { type: 'string', description: 'kebab token name, e.g. compact-row-padding-v' },
          value: { type: 'string', description: 'value with unit, e.g. 6px' },
          swift: { type: 'string', description: '$swift provenance, e.g. AppSkin.baseSpacing.compactRowVerticalPadding' },
          description: { type: 'string' },
        },
      },
    },
    scenarios: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['title', 'id', 'rmseExpectation'],
        properties: {
          title: { type: 'string', description: 'exact iOS catalog scenario title (the ref scenario)' },
          id: { type: 'string', description: 'web scenario id (kebab)' },
          rmseExpectation: { type: 'string', description: 'transparent | opaque — whether the catalog ref canvas is transparent (sampled corner alpha 0) or opaque' },
        },
      },
    },
    transparent: { type: 'boolean', description: 'true if catalog ref corner is transparent (alpha 0) → manifest needs transparent:true + crop to component surface element' },
    notes: { type: 'string', description: 'fidelity notes, token mappings, any uncertainty for the integrator/reviewer' },
  },
}

const RECIPE = `
You are building ONE web component that pixel-mirrors an iOS SwiftUI primitive, as part of the KG web design system. Work in the worktree ${WT} (branch web-ds). Use ABSOLUTE paths.

A COMPLETED reference example to imitate exactly (read it first):
  ${WT}/web/src/surfaces/vocab-shell/{VocabSortPillScreen.tsx,icons.tsx,fixtures.ts,vocab-shell.css}
  ${WT}/web/tools/parity-manifest.mjs  (search "vocab-sort-pill" for the 3-case block shape)
  ${WT}/web/src/harness/scenarios.ts + PhoneFrame.tsx  (how a surface is wired)

STEPS:
1. Find iOS SoT: grep ios/BooksAndVocab/Debug/Scenarios/ for your surface name to find the *Scenarios.swift registration; read it to learn each scenario's props/labels and the layout (.compressed=intrinsic pill/chip, .fillH=full-width bar). Then grep ios/BooksAndVocab for the actual component struct (e.g. VocabToneChip) and read its body: the exact view tree (HStack/VStack/ZStack + spacing), modifiers (.padding/.font/.foregroundStyle/.background/Capsule/RoundedRectangle), and which appSkin tokens it uses.
2. Resolve tokens to web CSS vars. The generated web vars are in ${WT}/web/src/styles/kg-tokens.css; the SoT mapping is ${WT}/design-system/tokens.json ($swift provenance). CRITICAL: verify each iOS token's REAL value from its Swift definition (ios/BooksAndVocab/Models/AppSkin+BaseValues.swift baseSpacing/baseMetrics, AppMetrics.swift AppSpacing/AppRadius, AppSkin+BaseValues buildTypography for fonts) — do NOT assume a similarly-named CSS var matches (e.g. compactChip padding 6/3 ≠ AppTagMetrics chip-padding 10/5). If your component needs a spacing/size token that has NO matching web var, return it in tokensNeeded with correct $swift+value; DO NOT hardcode a literal and DO NOT reuse a wrong-meaning var. Colors/typography tokens almost always already exist.
3. SF Symbol icons → ${WT}/web/src/shared/glyph makeGlyph (24x24 stroke). Mirror the SF symbol shape on a 24-grid. Reuse existing glyphs from other surfaces if the same symbol exists (grep web/src/surfaces/*/icons.tsx).
4. Determine transparency: run  magick "<catalog ref png>" -format "%[pixel:p{2,2}]" info:  on one of your scenario refs to check the corner. The catalog root is the newest ${WT}/build/snapshots/catalog-full-*; PNG path = "<root>/iPhone 15 Pro portrait/<surface-with-spaces→underscores, · kept>/<scenario title>.png". If corner alpha is 0 (srgba(...,0)) the scene is TRANSPARENT → your manifest cases need transparent:true and crop to your component-surface element; the surface/css must follow the vocab-sort-pill transparent pattern (component-surface is inline-flex with the scene's wrapper padding; a .phone-frame[data-crop=component][data-surface=<id>] transparent rule). If opaque, follow the selection-toolbar pattern instead (crop to surface, no transparent flag; surface background = the scene's bg token).
5. Write your component files under ${WT}/web/src/surfaces/<dirName>/ ONLY: <PascalName>Screen.tsx (props {scenario}), fixtures.ts (scenario→data), icons.tsx (if needed), <kebab>.css. ALL visual values via design-system CSS vars (var(--...)), ZERO literals except structural (flex, 999px capsule radius is var-or-999, box-sizing). Match the iOS view tree faithfully. For web user-facing strings raw text is fine (this is web, not iOS — no i18n lint).
6. DO NOT edit any shared file (scenarios.ts, PhoneFrame.tsx, parity-manifest.mjs, tokens.json). DO NOT run the parity pipeline. Instead RETURN the exact snippets to integrate (the schema fields). For manifestCasesJs, mirror the vocab-sort-pill block precisely: each scenario → one case object with case (e.g. '<id>-<scenarioId>-light'), params {surface:<id>, scenario:<scenarioId>, appearance:'light', crop:'component'}, crop:'.<your-surface-class>', transparent:true (if transparent), ref:{surface:'<exact catalog surface>', scenario:'<exact catalog title>', appearance:'light'}, note.

Return the BUILD_SCHEMA object. Be meticulous about iOS fidelity — a reviewer will diff against the catalog PNG and the iOS source.`

phase('Build atoms')

const results = await parallel(
  BATCH.map((b) => () =>
    agent(
      `${RECIPE}\n\n=== YOUR TARGET ===\nsurface (catalog): ${b.surface}\nsurfaceId/dirName: ${b.dir}\nscenarios (catalog titles, all light): ${JSON.stringify(b.scenarios)}\n\nBuild it now. Read the iOS SoT and the vocab-sort-pill reference first, then write your surface dir, then return the integration snippets.`,
      { label: `atom:${b.dir}`, phase: 'Build atoms', schema: BUILD_SCHEMA },
    ).then((r) => (r ? { ...r, _surface: b.surface, _scenarios: b.scenarios } : null)),
  ),
)

return { built: results.filter(Boolean), failed: results.filter((r) => !r).length, total: BATCH.length }
