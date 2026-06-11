import type { ScenarioId } from '../../harness/scenarios'
import { TODAY_REVIEW_FIXTURES } from './fixtures'
import type { ExampleSegment, ReviewCard, ReviewLink, TodayReviewFixture } from './fixtures'
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

function CardStage({ fixture }: { fixture: TodayReviewFixture }) {
  const isBack = fixture.reveal === 'back'
  return (
    <div className="tr-stage">
      {/* deck shell（depth-2 暗示）+ preview（depth-1）— front 時於 active 卡後露邊。 */}
      {!isBack && (
        <>
          <div className="tr-deck-shell tr-deck-2" />
          <div className="tr-deck-shell tr-deck-1" />
        </>
      )}

      {/* active card — front 單卡；back 摺頁（front 縮頂 + chevron + answer 卡）。 */}
      <div className={`tr-card ${isBack ? 'tr-card-folded' : 'tr-card-single'}`}>
        <div className="tr-fold-top">
          <CardFront card={fixture.card} />
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
              <CardAnswer card={fixture.card} />
            </div>
          </>
        )}
      </div>

      {!isBack && <span className="tr-expand-hint">點一下展開</span>}
    </div>
  )
}

function BottomToolbar({ fixture }: { fixture: TodayReviewFixture }) {
  return (
    <div className="tr-toolbar">
      <div className="tr-nav">
        <span className="tr-nav-btn"><ChevronLeftIcon size={22} /></span>
        <span className="tr-nav-btn"><ChevronRightIcon size={22} /></span>
      </div>
      <div className="tr-feedback">
        <span className="tr-feedback-btn tr-feedback-forgot">
          <XmarkBoldIcon size={17} />
          <span>忘記</span>
          {fixture.forgotCount > 0 && <span className="tr-feedback-count">·{fixture.forgotCount}</span>}
        </span>
        <span className="tr-feedback-btn tr-feedback-remembered">
          <CheckmarkIcon size={17} />
          <span>記得</span>
          {fixture.rememberedCount > 0 && <span className="tr-feedback-count">·{fixture.rememberedCount}</span>}
        </span>
      </div>
    </div>
  )
}

export function TodayReviewScreen({ scenario }: { scenario: ScenarioId<'today-review'> }) {
  const fixture = TODAY_REVIEW_FIXTURES[scenario]
  return (
    <div className="today-review">
      <header className="tr-topbar">
        <span className="tr-progress-pill">{fixture.progressText}</span>
        <span className="tr-shuffle-pill">
          <ShuffleIcon size={13} />
          <span>洗牌</span>
        </span>
        <span className="tr-topbar-spacer" />
        <span className="tr-chrome-btn"><PlayCircleIcon size={22} /></span>
        <span className="tr-chrome-btn"><XmarkIcon size={18} /></span>
      </header>

      <div className="tr-content">
        <CardStage fixture={fixture} />
      </div>

      <BottomToolbar fixture={fixture} />
    </div>
  )
}
