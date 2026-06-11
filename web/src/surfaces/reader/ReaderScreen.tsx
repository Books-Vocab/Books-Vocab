import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { READER_FIXTURES, WARM_NEUTRAL } from './fixtures'
import type { ReaderFixture } from './fixtures'
import {
  BookClosedIcon,
  ChevronLeftIcon,
  ChevronUpIcon,
  EllipsisIcon,
  ListBulletIcon,
  TextformatSizeIcon,
  WarningTriangleIcon,
} from './icons'
import './reader.css'

/**
 * Reader surface（chrome）— iOS ReaderViewPresenter 的 web 重寫。R1 範圍 =
 * chrome 骨架（compact/expanded header、loading overlay、underline 進度、error
 * 卡）+ synthetic paper 本體（8 placeholder blocks）。translation panel（R2）/
 * 面板群（R3）/ selection（R4）後續疊在 .reader-stack 的 overlay 掛載點上。
 *
 * 層序對齊 iOS ReaderViewPresenter.body 的 ZStack：
 *   paper 本體 → (loading 卡) → (underline 進度卡) → bottom overlay 掛點 → top header。
 */

/** 本體：synthetic paper（三段 gradient + 8 placeholder blocks）。幾何逐個抄
 *  iOS ReaderPresentationMetrics.Preview。 */
function PaperBody({ fixture }: { fixture: ReaderFixture }) {
  const gradientVars = {
    // paperOpacityTop=0.96 / Mid=0.88：用 color-mix 把 paper 色 fade 向透明，疊在
    // .reader-stack 的 paper 底色上 → 等效 iOS 的 paperColor.opacity(...)。
    '--reader-paper-top': `color-mix(in srgb, ${fixture.paperColor} 96%, transparent)`,
    '--reader-paper-mid': `color-mix(in srgb, ${fixture.paperColor} 88%, transparent)`,
    // paperOpacityFloor=0.08：warmNeutral 8%。
    '--reader-paper-floor': `color-mix(in srgb, ${WARM_NEUTRAL} 8%, transparent)`,
  } as CSSProperties
  return (
    <div className="reader-paper" style={gradientVars}>
      <div className="reader-blocks">
        {Array.from({ length: 8 }, (_, index) => (
          <span
            key={index}
            className="reader-block"
            data-tall={index % 3 === 0 ? '' : undefined}
            data-emphasis={index === 2 ? '' : undefined}
            // trailing inset = (index % 3) × 28pt（右側錯落）
            style={{ marginRight: `${(index % 3) * 28}px` }}
          />
        ))}
      </div>
    </div>
  )
}

/** error 本體：置中「無法開啟書籍」卡（AppEmptyStateCard themed + vocab content）。 */
function ErrorBody() {
  return (
    <div className="reader-error">
      <div className="reader-error-card">
        <span className="reader-error-icon">
          <WarningTriangleIcon size={40} strokeWidth={1.4} />
        </span>
        <h2 className="reader-error-title">無法開啟書籍</h2>
        <p className="reader-error-desc">
          Reader publication 載入失敗。請確認檔案是否完整，或稍後重新下載。
        </p>
      </div>
    </div>
  )
}

/** loading 卡：spinner + phase 文字（置中）。 */
function LoadingOverlay({ phase }: { phase: string }) {
  return (
    <div className="reader-loading">
      <div className="reader-loading-card">
        <span className="reader-spinner" aria-hidden="true" />
        <span className="reader-loading-text">{phase}</span>
      </div>
    </div>
  )
}

/** 頂部 underline 進度卡（loading 期）：track + fill + 百分比。 */
function UnderlineProgress({ progress }: { progress: number }) {
  return (
    <div className="reader-underline">
      <div className="reader-underline-card">
        <span className="reader-underline-track">
          <span className="reader-underline-fill" style={{ width: `${Math.max(3, 80 * progress)}px` }} />
        </span>
        <span className="reader-underline-pct">{Math.round(progress * 100)}%</span>
      </div>
    </div>
  )
}

/** compact header：右上進度膠囊（book.closed + %.1f%%）+ ellipsis 展開鈕。 */
function CompactHeader({ totalProgression }: { totalProgression: number }) {
  return (
    <div className="reader-header-compact">
      {totalProgression > 0 && (
        <span className="reader-progress-badge">
          <BookClosedIcon size={12} strokeWidth={1.6} />
          <span className="reader-progress-num">{(totalProgression * 100).toFixed(1)}%</span>
        </span>
      )}
      <button type="button" className="reader-chrome-btn" aria-label="展開標題列">
        <EllipsisIcon size={14} strokeWidth={1.7} />
      </button>
    </div>
  )
}

/** expanded header：flat 白卡 toolbar（書庫 + 居中書名 + 4 鈕）。 */
function ExpandedHeader({ bookTitle }: { bookTitle: string }) {
  return (
    <div className="reader-header-expanded">
      <div className="reader-toolbar">
        <button type="button" className="reader-toolbar-back" aria-label="書庫">
          <ChevronLeftIcon size={15} strokeWidth={1.7} />
          <span className="reader-toolbar-back-label">書庫</span>
        </button>
        <span className="reader-toolbar-title">{bookTitle}</span>
        <div className="reader-toolbar-actions">
          <button type="button" className="reader-chrome-btn" aria-label="目錄">
            <ListBulletIcon size={14} strokeWidth={1.7} />
          </button>
          <button type="button" className="reader-chrome-btn" aria-label="閱讀設定">
            <TextformatSizeIcon size={14} strokeWidth={1.6} />
          </button>
          <button type="button" className="reader-chrome-btn" aria-label="選擇單字本">
            <BookClosedIcon size={14} strokeWidth={1.6} />
          </button>
          <button type="button" className="reader-chrome-btn" aria-label="收起標題列">
            <ChevronUpIcon size={14} strokeWidth={1.7} />
          </button>
        </div>
      </div>
    </div>
  )
}

export function ReaderScreen({ scenario }: { scenario: ScenarioId<'reader'> }) {
  const fixture = READER_FIXTURES[scenario]
  return (
    <div className="reader" style={{ '--reader-paper': fixture.paperColor } as CSSProperties}>
      <div className="reader-stack">
        {/* 本體：error 卡 or synthetic paper */}
        {fixture.showsErrorCard ? <ErrorBody /> : <PaperBody fixture={fixture} />}

        {/* loading 卡（isWebViewReady=false 時疊置中） */}
        {!fixture.isWebViewReady && <LoadingOverlay phase={fixture.loadingPhase} />}

        {/* 頂部 underline 進度卡（loading 期） */}
        {fixture.underlineProgress !== null && <UnderlineProgress progress={fixture.underlineProgress} />}

        {/* bottom overlay 掛載點 — R2 translation panel / R3 面板群疊於此 */}
        <div className="reader-bottom-overlay" data-overlay={fixture.overlay} />

        {/* top header（compact / expanded） */}
        {fixture.header === 'expanded' ? (
          <ExpandedHeader bookTitle={fixture.bookTitle} />
        ) : (
          <CompactHeader totalProgression={fixture.totalProgression} />
        )}
      </div>
    </div>
  )
}
