import type { ReactNode } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { WORD_DETAIL_CARD_FIXTURES } from './fixtures'
import type { WordDetailCardFixture } from './fixtures'
import { SpeakerWaveFillIcon, TextWordSpacingIcon, BookClosedIcon } from './icons'
import { useWordDetailCardApiStore, useWordParam } from './useWordDetailCardApiStore'
import './word-detail-card.css'

/**
 * Word Detail · Card Document surface — iOS `CardDocumentView`（CardDocumentView.swift）
 * 的 web 鏡像。catalog scene = WordDetailScenarios.cardSheet：
 *   ScrollView { CardDocumentView(document, compact).padding(cardBlockPadding=24) }
 *     .background(pageBackground)
 *
 * component crop（ref corner = page-bg #f7f6f3 不透明 → 無 transparent）。
 * crop 目標 = `.word-detail-card` surface（含 page-bg + scene .padding(24)），
 * compressed layout 緊裁至內容 intrinsic box。
 *
 * 幾何契約（CardDocumentView.body）：
 *   - VStack(alignment:.leading, spacing: blockSpacing)。
 *     blockSpacing = compact ? foldSectionSpacing(24) : 0
 *   - 每個非 divider block 外覆 .padding(blockPadding)。
 *     blockPadding = compact ? 0 : cardBlockPadding(24)
 *   - divider：compact → horizontalPadding 0；否則 cardDividerHorizontalPadding(24)
 *   - block 順序由 CardDocumentBuilder.build 決定（見 fixtures.ts）
 *
 * Hero（CardDocumentHeroBlock）：
 *   HStack(.top, spacing cardBlockContentGap=16){
 *     VStack(.leading, spacing cardBlockInnerGap=8){
 *       HStack(.firstTextBaseline, spacing heroBaselineGap=8){
 *         word (detailWord=systemMono27 semibold, tracking h2Tight -0.65)
 *         pos? (body=sans15 .medium, secondaryText)
 *       }
 *       HStack(spacing heroBaselineGap=8){ speaker.wave.2.fill iconSmall(12) 36×36 鈕 } }
 *     Spacer(minLength blockGap=12)
 *     tier? VocabTierLabel（monoLabel=mono10 bold, tierColor.opacity(0.78)） }
 *
 * Example（CardDocumentExampleBlock）：detailExampleSerif=serifItalic22 primaryText，lineSpacing 4。
 * Meaning（CardDocumentMeaningBlock）：title translationTitle=serif21 bold tracking h2Tight；
 *   paragraphs body=sans15 secondaryText，lineSpacing compact?5:detailLineSpacing(5)，compact lineLimit 3。
 * Collocations（CardDocumentCollocationsBlock）：CardSectionLabel(text.word.spacing,「搭配」)
 *   + flow pills（monoBody=mono14 secondaryText, .padding(.h s2=8 .v s1=4),
 *     Capsule fill divider.opacity(0.5)），inner gap cardBlockInnerGap=8。
 * Source（CardDocumentSourceBlock）：CardSectionLabel(book.closed,「來源」)
 *   + HStack(spacing sourceMetadataGap=6){ bookTitle / · chapter }（caption=sans12 bold secondaryText），
 *     inner gap cardBlockInnerGap=8。
 */
export function WordDetailCardScreen({ scenario }: { scenario: ScenarioId<'word-detail-card'> }) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) return <WordDetailCardApi />
  return <WordDetailCardBody fx={WORD_DETAIL_CARD_FIXTURES[scenario]} />
}

/** shell 路徑：拉真實卡片並以同一 buildBlocks 佈局渲染（loading/error → no-example fixture）。 */
function WordDetailCardApi() {
  const word = useWordParam()
  const store = useWordDetailCardApiStore(word)
  const fx = store.status === 'ready' && store.fixture ? store.fixture : WORD_DETAIL_CARD_FIXTURES['no-example']
  return <WordDetailCardBody fx={fx} />
}

/** 共用畫面本體：buildBlocks → block 佈局（fixture / API 兩條路共用）。 */
function WordDetailCardBody({ fx }: { fx: WordDetailCardFixture }) {
  const blocks = buildBlocks(fx)
  return (
    <div
      className="word-detail-card"
      data-compact={fx.compact ? 'true' : undefined}
    >
      <div className="wdc-stack">
        {blocks.map((b, i) =>
          b.kind === 'divider' ? (
            <div key={i} className="wdc-divider" role="separator" />
          ) : (
            <div key={i} className="wdc-block">
              {b.node}
            </div>
          ),
        )}
      </div>
    </div>
  )
}

type Block = { kind: 'divider' } | { kind: 'block'; node: ReactNode }

function buildBlocks(fx: WordDetailCardFixture): Block[] {
  const out: Block[] = []
  out.push({ kind: 'block', node: <HeroBlock fx={fx} /> })
  if (fx.example) {
    out.push({ kind: 'block', node: <ExampleBlock text={fx.example} /> })
  }
  if (fx.meaning) {
    out.push({ kind: 'divider' })
    out.push({ kind: 'block', node: <MeaningBlock meaning={fx.meaning} compact={fx.compact} /> })
  }
  if (fx.collocations.length > 0) {
    out.push({ kind: 'divider' })
    out.push({ kind: 'block', node: <CollocationsBlock items={fx.collocations} /> })
  }
  out.push({ kind: 'divider' })
  out.push({ kind: 'block', node: <SourceBlock source={fx.source} /> })
  return out
}

function HeroBlock({ fx }: { fx: WordDetailCardFixture }) {
  return (
    <div className="wdc-hero">
      <div className="wdc-hero-main">
        <div className="wdc-hero-title">
          <span className="wdc-hero-word">{fx.hero.word}</span>
          {fx.hero.partOfSpeech && <span className="wdc-hero-pos">{fx.hero.partOfSpeech}</span>}
        </div>
        <div className="wdc-hero-actions">
          <span className="wdc-hero-speaker" aria-label={`朗讀 ${fx.hero.word}`}>
            <SpeakerWaveFillIcon className="wdc-icon-small" />
          </span>
        </div>
      </div>
      {fx.hero.difficultyTier && (
        <span className="wdc-tier" aria-label={`難度等級：${fx.hero.difficultyTier}`}>
          {fx.hero.difficultyTier}
        </span>
      )}
    </div>
  )
}

function ExampleBlock({ text }: { text: string }) {
  return <p className="wdc-example">{text}</p>
}

function MeaningBlock({
  meaning,
  compact,
}: {
  meaning: { title: string; paragraphs: string[] }
  compact: boolean
}) {
  return (
    <div className="wdc-meaning">
      {meaning.title && <h2 className="wdc-meaning-title">{meaning.title}</h2>}
      <div className="wdc-meaning-body">
        {meaning.paragraphs.map((p, i) => (
          <p
            key={i}
            className={compact ? 'wdc-meaning-para wdc-meaning-para--clamp' : 'wdc-meaning-para'}
          >
            {p}
          </p>
        ))}
      </div>
    </div>
  )
}

function CollocationsBlock({ items }: { items: string[] }) {
  return (
    <div className="wdc-section">
      <div className="wdc-section-label">
        <TextWordSpacingIcon className="wdc-icon-tiny" />
        <span className="wdc-section-label-text">搭配</span>
      </div>
      <div className="wdc-collocations">
        {items.map((item, i) => (
          <span key={i} className="wdc-pill">
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}

function SourceBlock({ source }: { source: { bookTitle: string; chapterTitle: string | null } }) {
  return (
    <div className="wdc-section">
      <div className="wdc-section-label">
        <BookClosedIcon className="wdc-icon-tiny" />
        <span className="wdc-section-label-text">來源</span>
      </div>
      <div className="wdc-source-meta">
        <span>{source.bookTitle}</span>
        {source.chapterTitle && <span>{`· ${source.chapterTitle}`}</span>}
      </div>
    </div>
  )
}
