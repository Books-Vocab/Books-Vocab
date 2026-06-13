import type { VocabRowFixture } from './fixtures'

/**
 * Vocabulary surface — share / pronounce helpers.
 *
 * Pure(ish) presentational utilities for the shell-path card actions. They are
 * deliberately framework-free and browser-API-guarded so they:
 *   - unit-test in the node vitest environment (no window/navigator/document);
 *   - degrade to a graceful no-op when the relevant Web API is unavailable
 *     (older Safari, insecure context, headless capture path).
 *
 * Parity isolation: these are only wired into the shell-gated UI (header/card
 * actions that render solely when `headerActions` is present), so the parity
 * capture DOM never reaches them.
 */

/**
 * Plain-text representation of a vocab card for share / clipboard:
 *   "word — meaning (example)"
 * The parenthetical is dropped when there is no example. All fields are trimmed.
 */
export function formatShareText(row: VocabRowFixture): string {
  const word = row.word.trim()
  const meaning = row.translation.trim()
  const example = row.expansion.example.trim()
  const base = `${word} — ${meaning}`
  return example ? `${base} (${example})` : base
}

/** Globals that may or may not exist depending on browser / environment. */
type SpeechGlobals = {
  speechSynthesis?: {
    cancel: () => void
    speak: (utterance: unknown) => void
  }
  SpeechSynthesisUtterance?: new (text: string) => { lang: string }
}

/**
 * Speak `word` via the Web Speech API (`speechSynthesis`). Cancels any pending
 * utterance first so rapid taps don't queue up. Returns true if speech was
 * dispatched, false if the API is unsupported (graceful no-op — never throws).
 */
export function speakWord(word: string, lang = 'en-US'): boolean {
  const g = globalThis as unknown as SpeechGlobals
  const synth = g.speechSynthesis
  const Utterance = g.SpeechSynthesisUtterance
  if (!synth || typeof Utterance !== 'function') return false
  const text = word.trim()
  if (!text) return false
  try {
    synth.cancel()
    const utterance = new Utterance(text)
    utterance.lang = lang
    synth.speak(utterance)
    return true
  } catch {
    return false
  }
}

/**
 * Result of a share/copy attempt — drives optional transient UI ("已複製").
 *   'shared'      — native share sheet invoked (navigator.share).
 *   'copied'      — text written to clipboard (navigator.clipboard).
 *   'unsupported' — neither API available (graceful no-op).
 */
export type ShareResult = 'shared' | 'copied' | 'unsupported'

type ShareGlobals = {
  navigator?: {
    share?: (data: { text: string }) => Promise<void>
    clipboard?: { writeText: (text: string) => Promise<void> }
  }
}

/**
 * Share `text` via `navigator.share` when available, else copy it to the
 * clipboard via `navigator.clipboard`. Returns the path taken. Never throws:
 * a user-cancelled share sheet (AbortError) resolves to 'shared'; any failure
 * to copy resolves to 'unsupported'.
 */
export async function shareOrCopy(text: string): Promise<ShareResult> {
  const nav = (globalThis as unknown as ShareGlobals).navigator
  if (nav?.share) {
    try {
      await nav.share({ text })
      return 'shared'
    } catch (err) {
      // User dismissal is not a failure; only fall through on real errors.
      if (err instanceof DOMException && err.name === 'AbortError') return 'shared'
      // fall through to clipboard.
    }
  }
  if (nav?.clipboard?.writeText) {
    try {
      await nav.clipboard.writeText(text)
      return 'copied'
    } catch {
      return 'unsupported'
    }
  }
  return 'unsupported'
}
