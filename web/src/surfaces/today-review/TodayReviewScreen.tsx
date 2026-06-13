import type { ScenarioId } from '../../harness/scenarios'
import type { ExampleSegment, ReviewCard, ReviewLink, RevealStage } from './fixtures'
import { useTodayReviewStore } from './store'
import { useTodayReviewApiStore } from './useTodayReviewApiStore'
import { VocabSceneShell } from '../../shared/VocabSceneShell'
import {
  ArrowUpRightIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronUpIcon,
  CheckmarkIcon,
  PaperclipIcon,
  PlayCircleIcon,
  PlusThinIcon,
  ShuffleIcon,
  SpeakerWaveIcon,
  XmarkBoldIcon,
  XmarkIcon,
} from './icons'
import './today-review.css'

/**
 * Today Review surface — iOS TodayReviewView/TodayReviewPresenter 的 web 重寫。
 * 幾何常數逐一對齊 iOS（見 today-review.css 的 px 註解）。結構：
 *   topBar（progress pill + 洗牌 pill + spacer + autoplay + close）
 *   → card stage（deck shell + active card；back 時摺頁展開答案卡）
 *   → bottomToolbar（忘記 / 記得 或 nav）
 *
 * 互動化（fixtures 當資料層，store 薄 session 狀態）：點卡翻面（front↔back 摺頁
 * reveal，對齊 iOS ReviewFoldSurface 摺/展，CSS transition 等效手感）；答對/答錯
 * 推進佇列至下一張；走完佇列 → 完成態。parity 契約：初始狀態（index seed / reveal
 * = scenario）下 DOM 與靜態 PNG 逐像素一致；互動僅在使用者操作後改變 DOM。
 *
 * 當 URL 含 shell=1 時，切換至 API-backed useTodayReviewApiStore（讀 ?notebook_id=
 * 拉取 due 卡建 queue，grade 後批次 submit events/state）。非 ready 態由 VocabSceneShell
 * 包裹。
 */

/** front prompt 右上 chrome（喇叭 / 詳情）。recognition 與 production 共用。 */
function FrontChrome() {
  return (
    <div className="tr-front-chrome">
      <span className="tr-chrome-btn"><SpeakerWaveIcon size={20} /></span>
      <span className="tr-chrome-btn"><ArrowUpRightIcon size={20} /></span>
    </div>
  )
}

/** 富文本例句 — plain + mark（highlight）+ blank（cloze 遮蔽）。 */
function ExampleText({ segments, className }: { segments: ExampleSegment[]; className: string }) {
  return (
    <p className={className}>
      {segments.map((seg, i) =>
        seg.mark ? (
          <span key={i} className="tr-ex-mark">{seg.text}</span>
        ) : seg.blank ? (
          <span key={i} className="tr-ex-blank">{seg.text}</span>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </p>
  )
}

/** 卡正面內容（prompt + 詞性 + chrome；production 另帶 cloze 例句）。 */
function CardFront({ card }: { card: ReviewCard }) {
  return (
    <div className="tr-front-body">
      <div className="tr-front-prompt">
        {card.mode === 'recognition' ? (
          <span className="tr-front-word">{card.word}</span>
        ) : (
          <span className="tr-front-translation">{card.translation}</span>
        )}
        {card.partOfSpeech && <span className="tr-pos">{card.partOfSpeech}</span>}
      </div>
      {card.mode === 'production' && card.exampleFront.length > 0 && (
        <ExampleText segments={card.exampleFront} className="tr-front-example" />
      )}
    </div>
  )
}

function LinkStrip({ links }: { links: ReviewLink[] }) {
  return (
    <div className="tr-linkstrip">
      <span className="tr-linkstrip-clip"><PaperclipIcon size={13} /></span>
      <div className="tr-linkstrip-groups">
        {links.map((group) => (
          <div key={group.label} className="tr-linkstrip-row">
            <span className="tr-link-label">{group.label}：</span>
            {group.words.map((w, i) => (
              <span key={w} className="tr-link-item-wrap">
                <span className="tr-link-item">{w}</span>
                {i < group.words.length - 1 && <span className="tr-link-sep">|</span>}
              </span>
            ))}
            {group.overflowCount > 0 && <span className="tr-link-overflow">+{group.overflowCount}</span>}
          </div>
        ))}
      </div>
      <span className="tr-linkstrip-add"><PlusThinIcon size={16} /></span>
    </div>
  )
}

/** 答案卡內容（tier + 答案詞 + divider + link strip + 例句 + 釋義）。 */
function CardAnswer({ card }: { card: ReviewCard }) {
  // recognition 揭示 serif 翻譯；production 揭示 mono 英文單字。
  const answerWord = card.mode === 'production' ? card.word : card.translation
  return (
    <div className="tr-answer-body">
      <div className="tr-tier-row">
        {card.difficultyTier && <span className="tr-tier">{card.difficultyTier}</span>}
      </div>
      <div className={card.mode === 'production' ? 'tr-answer-word-mono' : 'tr-answer-word-serif'}>
        {answerWord}
      </div>
      <div className="tr-answer-divider" />
      <LinkStrip links={card.links} />
      <ExampleText segments={card.exampleBack} className="tr-answer-example" />
      <p className="tr-answer-explanation">{card.explanation}</p>
    </div>
  )
}

function CardStage({
  card,
  reveal,
  onFlip,
}: {
  card: ReviewCard
  reveal: RevealStage
  onFlip: () => void
}) {
  const isBack = reveal === 'back'
  return (
    <div className="tr-stage">
      {/* deck shell（depth-2 暗示）+ preview（depth-1）— front 時於 active 卡後露邊。 */}
      {!isBack && (
        <>
          <div className="tr-deck-shell tr-deck-2" />
          <div className="tr-deck-shell tr-deck-1" />
        </>
      )}

      {/* active card — front 單卡；back 摺頁（front 縮頂 + chevron + answer 卡）。
          整卡可點翻面（front→展開、back→收合），對齊 iOS 點卡 reveal 手感。 */}
      <div
        className={`tr-card ${isBack ? 'tr-card-folded' : 'tr-card-single'}`}
        onClick={onFlip}
        role="button"
        tabIndex={0}
        aria-label={isBack ? '收合答案' : '展開答案'}
      >
        <div className="tr-fold-top">
          <CardFront card={card} />
          {!isBack && <FrontChrome />}
          {isBack && (
            <div className="tr-front-chrome tr-front-chrome-folded">
              <span className="tr-chrome-btn"><SpeakerWaveIcon size={20} /></span>
              <span className="tr-chrome-btn"><ArrowUpRightIcon size={20} /></span>
            </div>
          )}
        </div>
        {isBack && (
          <>
            <div className="tr-chevron-pill"><ChevronUpIcon size={13} /></div>
            <div className="tr-fold-bottom">
              <CardAnswer card={card} />
            </div>
          </>
        )}
      </div>

      {!isBack && <span className="tr-expand-hint">點一下展開</span>}
    </div>
  )
}

/** 完成態 — 走完佇列後的收尾卡（對齊 iOS TodayReview 完成 summary 精神）。 */
function CompletionStage({ forgot, remembered }: { forgot: number; remembered: number }) {
  return (
    <div className="tr-stage">
      <div className="tr-complete">
        <span className="tr-complete-check"><CheckmarkIcon size={40} /></span>
        <span className="tr-complete-title">今日複習完成</span>
        <p className="tr-complete-stats">
          記得 {remembered} · 忘記 {forgot}
        </p>
      </div>
    </div>
  )
}

function BottomToolbar({
  forgotCount,
  rememberedCount,
  onGrade,
}: {
  forgotCount: number
  rememberedCount: number
  onGrade: (g: 'forgot' | 'remembered') => void
}) {
  return (
    <div className="tr-toolbar">
      <div className="tr-nav">
        <span className="tr-nav-btn"><ChevronLeftIcon size={22} /></span>
        <span className="tr-nav-btn"><ChevronRightIcon size={22} /></span>
      </div>
      <div className="tr-feedback">
        {/* span role=button（非 <button>）：避免 button 內建 line 度量造成的基線/光柵差，
            保證初始 DOM 與靜態 PNG 逐像素一致（parity gate RMSE=0）。 */}
        <span
          className="tr-feedback-btn tr-feedback-forgot"
          role="button"
          tabIndex={0}
          onClick={() => onGrade('forgot')}
        >
          <XmarkBoldIcon size={17} />
          <span>忘記</span>
          {forgotCount > 0 && <span className="tr-feedback-count">·{forgotCount}</span>}
        </span>
        <span
          className="tr-feedback-btn tr-feedback-remembered"
          role="button"
          tabIndex={0}
          onClick={() => onGrade('remembered')}
        >
          <CheckmarkIcon size={17} />
          <span>記得</span>
          {rememberedCount > 0 && <span className="tr-feedback-count">·{rememberedCount}</span>}
        </span>
      </div>
    </div>
  )
}

export function TodayReviewScreen({ scenario }: { scenario: ScenarioId<'today-review'> }) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    const notebookId = new URLSearchParams(window.location.search).get('notebook_id')
    return <TodayReviewScreenApi notebookId={notebookId} />
  }
  return <TodayReviewScreenFixture scenario={scenario} />
}

/** Fixture-driven screen — parity harness 路徑（無 shell=1 時）。 */
function TodayReviewScreenFixture({ scenario }: { scenario: ScenarioId<'today-review'> }) {
  const store = useTodayReviewStore(scenario)
  return <TodayReviewBody store={store} />
}

/** API-driven screen — shell=1 時使用真實後端資料。 */
function TodayReviewScreenApi({ notebookId }: { notebookId: string | null }) {
  const store = useTodayReviewApiStore(notebookId)
  return (
    <VocabSceneShell
      status={store.status === 'ready' ? 'content' : store.status === 'loading' ? 'loading' : 'error'}
      onRetry={store.retry}
    >
      <TodayReviewBody store={store} />
    </VocabSceneShell>
  )
}

/** 共享的 today-review 畫面本體（fixture / API 兩條路共用）。 */
function TodayReviewBody({
  store,
}: {
  store: {
    currentCard: ReviewCard
    reveal: RevealStage
    progressText: string
    forgotCount: number
    rememberedCount: number
    done: boolean
    flip: () => void
    grade: (g: 'forgot' | 'remembered') => void
  }
}) {
  return (
    <div className="today-review">
      <header className="tr-topbar">
        <span className="tr-progress-pill">{store.progressText}</span>
        <span className="tr-shuffle-pill">
          <ShuffleIcon size={13} />
          <span>洗牌</span>
        </span>
        <span className="tr-topbar-spacer" />
        <span className="tr-chrome-btn"><PlayCircleIcon size={22} /></span>
        <span className="tr-chrome-btn"><XmarkIcon size={18} /></span>
      </header>

      <div className="tr-content">
        {store.done ? (
          <CompletionStage forgot={store.forgotCount} remembered={store.rememberedCount} />
        ) : (
          <CardStage card={store.currentCard} reveal={store.reveal} onFlip={store.flip} />
        )}
      </div>

      <BottomToolbar
        forgotCount={store.forgotCount}
        rememberedCount={store.rememberedCount}
        onGrade={store.grade}
      />
    </div>
  )
}
