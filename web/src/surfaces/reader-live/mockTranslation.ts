import type { TranslationPanelData } from '../reader/fixtures'

/**
 * MOCK 翻譯來源 — phase-1 不接 backend translate endpoint。
 *
 * 誠實標注：本檔是純前端 fixture，依選中詞回傳「翻譯中 → 譯文」的假資料，
 * 用來驅動真實的 parity `TranslationPanel` 視覺殼。真正的 LLM 翻譯/詞庫接線
 * （backend `/api/vocab` + translate）是 phase-2 範圍，屆時改成 `web/src/api`
 * 的 client 呼叫即可，panel 殼層不需改動。
 *
 * 小型 demo 字典涵蓋測試書（childrens-literature.epub）常見詞；未命中者回退到
 * 一個明確標 [mock] 的佔位譯文，讓「點任意詞 → panel 浮現」鏈路完整可驗。
 */

const DICT: Record<string, { translation: string; pos: string; explanation: string }> = {
  children: {
    translation: '兒童（複數）',
    pos: 'n.',
    explanation: 'child 的複數，指年幼的人；此處為書名「Children\'s Literature」的一部分。',
  },
  literature: {
    translation: '文學',
    pos: 'n.',
    explanation: '以書寫形式呈現、具藝術價值的作品總稱，尤指小說、詩歌與戲劇。',
  },
  chimes: {
    translation: '鐘聲；一組調音鐘',
    pos: 'n.',
    explanation: '一組音高不同的鐘，敲響時奏出旋律；故事〈Why the Chimes Rang〉的核心意象。',
  },
  rang: {
    translation: '響起（ring 的過去式）',
    pos: 'v.',
    explanation: 'ring 的過去式，指鐘、鈴發出聲響。',
  },
  story: {
    translation: '故事',
    pos: 'n.',
    explanation: '對一連串真實或虛構事件的敘述。',
  },
  little: {
    translation: '小的；少量的',
    pos: 'adj.',
    explanation: '形容體積小、年紀幼或數量少。',
  },
  child: {
    translation: '孩子',
    pos: 'n.',
    explanation: '年幼的人；亦指某人的子女。',
  },
}

/** 依選中詞造一份 loading 態 panel data（hero 立刻顯示詞，body 顯示翻譯中）。 */
export function loadingPanel(word: string): TranslationPanelData {
  return {
    word,
    partOfSpeech: null,
    translation: null,
    isExpanded: false,
    explanation: null,
    isExplanationOnly: false,
    isPanelLarge: false,
    translationError: null,
    explanationError: null,
    isLoading: true,
    statusMessage: '翻譯中…（mock）',
    isSaved: false,
    timerText: null,
  }
}

/** 依選中詞 + context 造一份已完成 panel data（mock 譯文）。 */
export function resolvedPanel(word: string, _context: string, expanded: boolean): TranslationPanelData {
  const entry = DICT[word.toLowerCase()]
  const translation = entry
    ? entry.translation
    : `（mock 譯文）${word}`
  return {
    word,
    partOfSpeech: entry?.pos ?? null,
    translation,
    isExpanded: expanded,
    explanation: entry?.explanation ?? '（mock 語境解釋）此處僅為前端 fixture，phase-2 接 LLM 後替換。',
    isExplanationOnly: false,
    isPanelLarge: false,
    translationError: null,
    explanationError: null,
    isLoading: false,
    statusMessage: null,
    isSaved: false,
    timerText: '0.3s',
  }
}
