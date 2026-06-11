import type { PodcastSentence } from './fixtures'

/**
 * Demo playback timeline — 把 5 句字幕鋪到 12s demo 音檔上，供互動播放時
 * 「逐句 + 逐詞」highlight 跟隨 currentTime。**僅互動後生效**：靜態 parity 首屏
 * 仍直接渲染 fixture 的 isActive/activeWordIndex（見 PodcastScreen 的 started gate），
 * 故 capture 像素不受此 demo timing 影響。
 *
 * fixtures 沒有真實 word-level timing（catalog seed 只給單一 active 詞），這裡造一組
 * 等分 demo timing 讓「跟讀」效果可觀測、可測試。
 */

/** demo 音檔長度（ffmpeg 合成，見 src/assets/podcast_demo.mp3）。 */
export const DEMO_DURATION_SEC = 12

export interface WordSpan {
  sentenceIndex: number
  wordIndex: number
  start: number
  end: number
}

/** 每句的 [start, end) 視窗（等分整段；最後一句吃到結尾）。 */
export function sentenceWindows(sentences: PodcastSentence[]): { start: number; end: number }[] {
  const n = sentences.length
  const per = DEMO_DURATION_SEC / n
  return sentences.map((_, i) => ({
    start: i * per,
    end: i === n - 1 ? DEMO_DURATION_SEC : (i + 1) * per,
  }))
}

/** 把每句再依字數等分成逐詞 span，攤平成一條時間軸。 */
export function buildWordSpans(sentences: PodcastSentence[]): WordSpan[] {
  const windows = sentenceWindows(sentences)
  const spans: WordSpan[] = []
  sentences.forEach((s, si) => {
    const words = s.text.split(' ')
    const { start, end } = windows[si]
    const per = (end - start) / words.length
    words.forEach((_, wi) => {
      spans.push({
        sentenceIndex: si,
        wordIndex: wi,
        start: start + wi * per,
        end: start + (wi + 1) * per,
      })
    })
  })
  return spans
}

/** 給定 currentTime 回傳當前 (sentenceIndex, wordIndex)；超出回最後一詞。 */
export function activeSpanAt(spans: WordSpan[], t: number): { sentenceIndex: number; wordIndex: number } {
  for (const span of spans) {
    if (t < span.end) return { sentenceIndex: span.sentenceIndex, wordIndex: span.wordIndex }
  }
  const last = spans[spans.length - 1]
  return { sentenceIndex: last.sentenceIndex, wordIndex: last.wordIndex }
}

/** 秒 → m:ss（locale 無關，對齊 iOS PodcastClock.format）。 */
export function formatClock(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec))
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/** 速度循環（rate pill 點擊：×1 → ×1.5 → ×2 → ×0.75 → ×1）。 */
export const RATE_CYCLE = [1, 1.5, 2, 0.75] as const
export type PlaybackRate = (typeof RATE_CYCLE)[number]

export function nextRate(current: PlaybackRate): PlaybackRate {
  const i = RATE_CYCLE.indexOf(current)
  return RATE_CYCLE[(i + 1) % RATE_CYCLE.length]
}

export function rateLabel(rate: number): string {
  // ×1 / ×1.5 / ×2 / ×0.75（String 本就不帶尾零）
  return `×${rate}`
}
