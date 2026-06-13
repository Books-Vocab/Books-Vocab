import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, animate, motion, useMotionValue, useTransform } from 'framer-motion'
import { useDrag } from '@use-gesture/react'
import type { ScenarioId } from '../../harness/scenarios'
import type { ExampleSegment, ReviewCard, ReviewLink, RevealStage } from './fixtures'
import { snappy, gentle, navPush, usePreferredTransition, useReducedMotion } from '../../motion'
import { useTodayReviewStore } from './store'
import type { Grade } from './store'
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

/** active card 內容（front 單卡 / back 摺頁）— 翻面 3D rotate 的「面」。 */
function CardFace({ card, isBack }: { card: ReviewCard; isBack: boolean }) {
  return (
    <>
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
    </>
  )
}

/**
 * 互動 deck 卡 — 對齊 iOS 複習牌組手感的三層動畫（皆取自 web/src/motion）：
 *
 *   • 翻面（flip）：點卡 → front↔back 以 X 軸 3D rotate 翻轉（springs.snappy）。
 *     單一持久面（key=reveal 重掛 motion.div 重播 rotateX 進場），故任一時刻 DOM
 *     僅含當前 reveal 的內容，嚴守互動契約的同步 DOM（點卡 → answer body 即時進
 *     DOM；翻回 → 即時移除）。首翻前 initial={false}（無進場動畫），確保 parity
 *     capture 的初始幀為 settled 姿態（與靜態 PNG 的 RMSE 漂移遠低於 verdict
 *     jitter band 0.005，僅 AA 級噪訊）。
 *
 *   • 滑動評分（swipe-to-rate）：@use-gesture useDrag → 卡跟手平移 + 隨位移微傾 +
 *     漸隱；放手過距離/速度閾值 → 評分（右=記得 / 左=忘記）並帶動量飛出（飛出用共享
 *     motion 層 navPush spring，並以手勢甩動速度 seed framer animate 的 velocity，故
 *     甩越快飛越遠），未過閾值 → snappy 回彈。filterTaps 令「點」走翻面（保留既有
 *     click→flip 契約）、「拖」走評分。bind 掛內層 plain .tr-card（避 motion.div
 *     onDrag 型別衝突），x motion value 驅動外層 .tr-card-swipe 的 transform。
 *
 *   • 牌組推進（deck advance）：評分後 currentCard 換新，新卡由牌堆 scale-up 滑入
 *     （AnimatePresence key=cardKey；initial={false} 首幀不播）。
 *
 * reduced-motion：rotate/位移/牌堆動畫全收斂為瞬時（usePreferredTransition）。
 */
function DeckCard({
  card,
  reveal,
  cardKey,
  onFlip,
  onGrade,
}: {
  card: ReviewCard
  reveal: RevealStage
  /** 牌組身分（推進後改變 → 觸發 deck-advance 進場）。 */
  cardKey: number
  onFlip: () => void
  onGrade: (g: Grade) => void
}) {
  const isBack = reveal === 'back'
  const prefersReduced = useReducedMotion() ?? false
  const flipTransition = usePreferredTransition(snappy)
  const advanceTransition = usePreferredTransition(gentle)

  // 首翻 gate：未翻過前翻面元素 initial={false}（無進場動畫），確保 parity capture
  // 的初始幀為 settled 姿態。首次翻面後置 true → 後續 reveal 變動重播 rotateX 進場。
  // 牌組推進（cardKey 變）時 reset：新卡 reveal 回 front 的變動由 deck-advance 動畫
  // 主導，翻面進場不應疊播（reset → 該次 reveal 變動 initial={false}）。
  const [hasFlipped, setHasFlipped] = useState(false)
  useEffect(() => {
    setHasFlipped(false)
  }, [cardKey])
  const doFlip = () => {
    setHasFlipped(true)
    onFlip()
  }

  // 滑動評分：單一 x motion value 為真相 —— style 恆掛 {x, rotate, opacity}（x 跟手
  // 平移、隨位移微傾 + 接近飛出時漸隱）；放手以 framer 命令式 animate(x, …) 驅動飛出
  // 或回彈，避免「style motion-value ↔ animate prop」對同一鍵的衝突。
  const x = useMotionValue(0)
  const rotate = useTransform(x, [-200, 0, 200], [-9, 0, 9])
  const opacity = useTransform(x, [-260, -120, 0, 120, 260], [0, 1, 1, 1, 0])
  const firedRef = useRef(false)

  /** 過閾值方向：右(+1)=記得、左(-1)=忘記。 */
  const SWIPE_DISTANCE = 110
  const SWIPE_VELOCITY = 0.45

  const bind = useDrag(
    ({ down, movement: [mx], velocity: [vx], direction: [dx], last, tap }) => {
      // 點（非拖）→ 翻面（保留 click→flip 契約）。
      if (tap) {
        doFlip()
        return
      }
      if (firedRef.current) return
      if (down) {
        x.set(mx)
        return
      }
      if (!last) return
      // 放手：過距離或快速彈 → 評分飛出帶動量；否則 snappy 回彈。
      const far = Math.abs(mx) > SWIPE_DISTANCE
      const fast = vx > SWIPE_VELOCITY && dx !== 0
      if (far || fast) {
        const dir = (mx !== 0 ? Math.sign(mx) : dx) || 1
        firedRef.current = true
        if (prefersReduced) {
          // reduced-motion：略過飛出動畫，直接評分推進（新卡瞬時換上）。
          x.set(0)
          firedRef.current = false
          onGrade(dir > 0 ? 'remembered' : 'forgot')
          return
        }
        // 飛出沿用共享 motion 層 navPush spring（response .5 / ζ .82，權威落定無
        // overshoot），不再自編魔術數字。velocity 以手勢甩動速度 seed：@use-gesture
        // 的 vx 是 px/ms 且恆為正量值，乘 1000 轉 px/s、套方向，令甩越快飛越遠的手感
        // 與物理一致。
        animate(x, dir * 520, { ...navPush, velocity: dir * vx * 1000 }).then(() => {
          // 飛出完成 → 評分推進；新卡由 deck-advance 進場前先把 x 歸零。
          x.set(0)
          firedRef.current = false
          onGrade(dir > 0 ? 'remembered' : 'forgot')
        })
      } else {
        animate(x, 0, snappy)
      }
    },
    {
      axis: 'x',
      filterTaps: true,
      pointer: { touch: true, mouse: true },
      from: () => [x.get(), 0],
    },
  )

  return (
    <div className="tr-stage">
      {/* deck shell（depth-2/1 底卡暗示）— front 時於 active 卡後露邊。 */}
      {!isBack && (
        <>
          <div className="tr-deck-shell tr-deck-2" />
          <div className="tr-deck-shell tr-deck-1" />
        </>
      )}

      {/* deck-advance 進場：評分換卡 → 新卡由牌堆 scale-up 滑入。 */}
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={cardKey}
          className="tr-card-advance"
          initial={prefersReduced ? false : { scale: 0.94, y: 12, opacity: 0 }}
          animate={{ scale: 1, y: 0, opacity: 1 }}
          transition={advanceTransition}
        >
          {/* swipe 跟手層：x/rotate/opacity 恆由 x motion value 驅動（單一真相）；
              飛出 / 回彈由 bind 內 framer 命令式 animate(x, …) 推動。@use-gesture 的
              bind 掛內層 plain .tr-card（避 motion.div onDrag 型別衝突，pointer 事件
              由內層捕捉、x motion value 驅動此層 transform）。 */}
          <motion.div className="tr-card-swipe" style={{ x, rotate, opacity }}>
            {/* 翻面 3D：單一持久面（無 AnimatePresence），故任一時刻 DOM 僅有當前
                reveal 的內容——點卡 → folded 答案即時進 DOM、翻回 → answer body 即時
                移除，嚴守互動契約的同步 DOM。視覺翻轉以 key=reveal 重掛 motion.div
                重播 rotateX 進場達成；首翻前（hasFlipped=false）initial={false}，故
                parity capture 初始幀為 settled 姿態、DOM 與靜態 PNG 逐像素一致。
                {...bind()} 掛此 plain div（native onDrag，不與 framer 衝突）。 */}
            <div
              {...bind()}
              className={`tr-card ${isBack ? 'tr-card-folded' : 'tr-card-single'}`}
              role="button"
              tabIndex={0}
              aria-label={isBack ? '收合答案' : '展開答案'}
              style={{ touchAction: 'pan-y' }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  doFlip()
                }
              }}
            >
              <motion.div
                key={reveal}
                className="tr-flip-face"
                initial={
                  hasFlipped && !prefersReduced
                    ? { rotateX: isBack ? 90 : -90, opacity: 0.35 }
                    : false
                }
                animate={{ rotateX: 0, opacity: 1 }}
                transition={flipTransition}
              >
                <CardFace card={card} isBack={isBack} />
              </motion.div>
            </div>
          </motion.div>
        </motion.div>
      </AnimatePresence>

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
            保證初始 DOM 與靜態 PNG 逐像素一致（parity gate RMSE=0）。role=button +
            tabIndex 使其可聚焦，故須補 Enter/Space 啟動（與卡面翻面的鍵盤契約一致），
            否則鍵盤使用者能聚焦卻無法評分。 */}
        <span
          className="tr-feedback-btn tr-feedback-forgot"
          role="button"
          tabIndex={0}
          onClick={() => onGrade('forgot')}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onGrade('forgot')
            }
          }}
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
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onGrade('remembered')
            }
          }}
        >
          <CheckmarkIcon size={17} />
          <span>記得</span>
          {rememberedCount > 0 && <span className="tr-feedback-count">·{rememberedCount}</span>}
        </span>
      </div>
    </div>
  )
}

/**
 * 進度膠囊 — 推進時快速 scale 回彈（springs.snappy 質感），令「前進一張」有手感。
 *
 * parity 鐵律：第一次渲染（capture 初始幀）必須輸出 plain `<span class=tr-progress-pill>`
 * 且**無 inline motion style / 無動畫**。故首幀 animate={false}（framer 不寫 inline
 * transform、不播動畫）；掛載後（useEffect）才追蹤 text 變動 → 播 pop。React 官方
 * 「render 階段不可有副作用」契約以 useEffect 比對前值落實，避免 render 期改 ref。
 * reduced-motion 下永遠瞬時（usePreferredTransition）。
 */
function ProgressPill({ text }: { text: string }) {
  const [pulse, setPulse] = useState(0)
  const prevText = useRef(text)
  const transition = usePreferredTransition(snappy)
  useEffect(() => {
    if (prevText.current !== text) {
      prevText.current = text
      setPulse((n) => n + 1) // 變動 → 觸發一次 pop（pulse>0 即非首幀）。
    }
  }, [text])
  return (
    <motion.span
      className="tr-progress-pill"
      initial={false}
      animate={pulse > 0 ? { scale: [1, 1.14, 1] } : false}
      transition={transition}
    >
      {text}
    </motion.span>
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
        <ProgressPill text={store.progressText} />
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
          <DeckCard
            card={store.currentCard}
            reveal={store.reveal}
            // 牌組身分：已評張數（記得+忘記）每推進一張就 +1 → 觸發 deck-advance。
            cardKey={store.forgotCount + store.rememberedCount}
            onFlip={store.flip}
            onGrade={store.grade}
          />
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
