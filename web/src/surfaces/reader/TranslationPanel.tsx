import type { TranslationPanelData } from './fixtures'
import {
  CheckmarkCircleFillIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  SpeakerWaveIcon,
  TextBubbleIcon,
  TranslateIcon,
  TrashIcon,
  WarningTriangleFillIcon,
  XmarkIcon,
} from './icons'

/**
 * TranslationPanel（R2）— iOS TranslationVocabPresenter 的 web 重寫（iPhone =
 * .bottomSheet：drag handle、contentTopInset=0、bottom-flush）。幾何逐一抄
 * ReaderMetrics / AppSpacing / AppSkin BaseValues，px 註解標 iOS 來源常數。
 *
 * 內容態（panelBody）對齊 contentMode × explanationContentMode：
 *   loading / translation(+explanation) / explanationOnly / translationError。
 * footer 對齊 footerToolbar：已加入(success) + timer(mono) + chevron/trash/xmark。
 */

/** chrome icon button（VocabChromeIconButton）：32pt 白卡 + control radius。
 *  tone 決定 icon 色（destructive=trash，否則 secondary）。 */
function ChromeBtn({
  children,
  label,
  tone,
}: {
  children: React.ReactNode
  label: string
  tone?: 'destructive'
}) {
  return (
    <button
      type="button"
      className="reader-chrome-btn translation-chrome-btn"
      data-tone={tone}
      aria-label={label}
    >
      {children}
    </button>
  )
}

/** state message card（VocabStateMessageCard）：themed 卡 + icon + title (+ desc / accessory)。 */
function StateMessageCard({
  icon,
  title,
  desc,
  accessory,
}: {
  icon: React.ReactNode
  title: string
  desc?: string
  accessory?: React.ReactNode
}) {
  return (
    <div className="translation-state-card">
      <div className="translation-state-head">
        <span className="translation-state-icon">{icon}</span>
        <span className="translation-state-title">{title}</span>
      </div>
      {desc && <p className="translation-state-desc">{desc}</p>}
      {accessory && <div className="translation-state-accessory">{accessory}</div>}
    </div>
  )
}

/** 語境解釋段（explanationSection）：divider + 「語境解釋」label + body/error/empty。 */
function ExplanationSection({ panel }: { panel: TranslationPanelData }) {
  return (
    <div className="translation-explanation">
      <span className="translation-divider" />
      <span className="translation-explanation-label">
        <TextBubbleIcon size={13} strokeWidth={1.6} />
        語境解釋
      </span>
      {panel.explanationError ? (
        <StateMessageCard
          icon={<WarningTriangleFillIcon size={18} />}
          title="語境解釋暫時無法載入"
          desc={panel.explanationError}
        />
      ) : panel.explanation ? (
        <p className="translation-explanation-body">{panel.explanation}</p>
      ) : null}
    </div>
  )
}

/** footer toolbar — 已加入 + timer（左）/ chevron/trash/xmark（右）。 */
function Footer({ panel }: { panel: TranslationPanelData }) {
  // showsExpandAction（單字模式 chevron）：有譯文、非句子模式、非錯誤/loading。
  const showsExpand =
    panel.translation !== null &&
    !panel.isExplanationOnly &&
    !panel.translationError &&
    !panel.isLoading
  // 句子模式專屬高度切換 chevron。
  const showsHeightToggle = panel.isExplanationOnly
  return (
    <div className="translation-footer">
      {panel.isSaved && (
        <span className="translation-saved">
          <CheckmarkCircleFillIcon size={15} />
          已加入
        </span>
      )}
      {panel.timerText && <span className="translation-timer">{panel.timerText}</span>}
      <span className="translation-footer-spacer" />
      {showsHeightToggle && (
        <ChromeBtn label={panel.isPanelLarge ? '縮小面板' : '放大面板'}>
          {panel.isPanelLarge ? (
            <ChevronDownIcon size={14} strokeWidth={1.7} />
          ) : (
            <ChevronUpIcon size={14} strokeWidth={1.7} />
          )}
        </ChromeBtn>
      )}
      {showsExpand && (
        <ChromeBtn label={panel.isExpanded ? '收合語境解釋' : '展開語境解釋'}>
          {panel.isExpanded ? (
            <ChevronUpIcon size={14} strokeWidth={1.7} />
          ) : (
            <ChevronDownIcon size={14} strokeWidth={1.7} />
          )}
        </ChromeBtn>
      )}
      {panel.isSaved && (
        <ChromeBtn label="刪除單字" tone="destructive">
          <TrashIcon size={14} strokeWidth={1.6} />
        </ChromeBtn>
      )}
      <ChromeBtn label="關閉">
        <XmarkIcon size={14} strokeWidth={1.7} />
      </ChromeBtn>
    </div>
  )
}

/** panelBody — contentMode 分派。 */
function PanelBody({ panel }: { panel: TranslationPanelData }) {
  if (panel.isLoading) {
    return (
      <StateMessageCard
        icon={<TranslateIcon size={18} />}
        title={panel.statusMessage ?? '翻譯中...'}
        accessory={
          <div className="translation-loading-row">
            <span className="reader-spinner translation-spinner" aria-hidden="true" />
            {panel.timerText && <span className="translation-timer">{panel.timerText}</span>}
          </div>
        }
      />
    )
  }
  if (panel.translationError) {
    return (
      <StateMessageCard
        icon={<WarningTriangleFillIcon size={18} />}
        title="翻譯暫時失敗"
        desc={panel.translationError}
      />
    )
  }
  if (panel.isExplanationOnly) {
    // 句子模式：純解釋段（無譯文 hero）。
    return <ExplanationSection panel={panel} />
  }
  // 一般翻譯：譯文 + 可選展開解釋。
  return (
    <>
      {panel.translation && <p className="translation-text">{panel.translation}</p>}
      {panel.isExpanded && <ExplanationSection panel={panel} />}
    </>
  )
}

export function TranslationPanel({ panel }: { panel: TranslationPanelData }) {
  return (
    <div className="translation-panel" data-large={panel.isPanelLarge ? '' : undefined}>
      {/* drag handle（bottomSheet capsule） */}
      <span className="translation-handle" aria-hidden="true" />

      <div className="translation-content">
        {/* hero：word（mono）+ speaker + adj. chip */}
        <div className="translation-hero">
          <span className="translation-word">{panel.word}</span>
          <button type="button" className="translation-speaker" aria-label="朗讀">
            <SpeakerWaveIcon size={10} strokeWidth={1.3} />
          </button>
          <span className="translation-hero-spacer" />
          {/* pos chip 綁 translation（iOS partOfSpeech = result?.partOfSpeech，
              loading/error 無 translation → 無 result → 無 chip）。 */}
          {panel.partOfSpeech && panel.translation && (
            <span className="translation-pos-chip">{panel.partOfSpeech}</span>
          )}
        </div>

        <PanelBody panel={panel} />
        {/* loading 模式無 footer（iOS loadingSection 不掛 footerToolbar）。 */}
        {!panel.isLoading && <Footer panel={panel} />}
      </div>
    </div>
  )
}
