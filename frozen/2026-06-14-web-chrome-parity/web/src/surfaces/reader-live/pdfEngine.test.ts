import { describe, expect, it } from 'vitest'
import { clampPage, expandWord, pageFromProgress, progressFromPage } from './pdfEngine'

/**
 * PDF 引擎的純函式（分頁夾取 / 進度↔頁碼互轉 / 選詞擴展）。pdfjs 渲染本身需 DOM／worker
 * 不在此單測；此檔只釘死無副作用的分頁與選詞邏輯。
 */
describe('clampPage', () => {
  it('夾到 [1, numPages]', () => {
    expect(clampPage(0, 5)).toBe(1)
    expect(clampPage(3, 5)).toBe(3)
    expect(clampPage(9, 5)).toBe(5)
    expect(clampPage(-2, 5)).toBe(1)
  })
  it('numPages 0 → 1（防呆）', () => {
    expect(clampPage(3, 0)).toBe(1)
  })
})

describe('pageFromProgress / progressFromPage（恢復位置 ↔ 回寫位置）', () => {
  it('progress 0 / null → 第 1 頁', () => {
    expect(pageFromProgress(0, 10)).toBe(1)
    expect(pageFromProgress(null, 10)).toBe(1)
    expect(pageFromProgress(undefined, 10)).toBe(1)
  })
  it('progress 0.5 of 10 → 第 6 頁（floor*10 + 1）', () => {
    expect(pageFromProgress(0.5, 10)).toBe(6)
  })
  it('progress 接近 1 → 末頁（夾取）', () => {
    expect(pageFromProgress(0.99, 10)).toBe(10)
    expect(pageFromProgress(1, 10)).toBe(10)
  })
  it('progressFromPage 為「該頁起始」分數 (page-1)/numPages', () => {
    expect(progressFromPage(1, 4)).toBeCloseTo(0)
    expect(progressFromPage(2, 4)).toBeCloseTo(0.25)
    expect(progressFromPage(4, 4)).toBeCloseTo(0.75)
  })
  it('round-trip：第 N 頁回寫後恢復不退回更早頁', () => {
    const numPages = 7
    for (let p = 1; p <= numPages; p++) {
      const restored = pageFromProgress(progressFromPage(p, numPages), numPages)
      expect(restored).toBe(p)
    }
  })
})

describe('expandWord（caret offset → 完整英文詞）', () => {
  const text = "Deep work is the ability"
  it('命中字中間 → 整個詞', () => {
    // "work" 在 index 5..8
    expect(expandWord(text, 6)).toBe('work')
  })
  it('命中詞邊界（offset 在詞首）', () => {
    expect(expandWord(text, 0)).toBe('Deep')
  })
  it('去頭尾撇號／連字號', () => {
    expect(expandWord("'self-aware'", 3)).toBe('self-aware')
  })
  it('單字母 → null（太短）', () => {
    expect(expandWord('a b c', 0)).toBeNull()
  })
  it('offset 在詞尾邊界 → 選到該詞（caret 在詞尾沿用左側詞，與閱讀器點字尾選詞同義）', () => {
    expect(expandWord('Deep work', 4)).toBe('Deep')
  })
  it('offset 落在純空白區間（兩側皆非詞字元）→ null', () => {
    expect(expandWord('Deep   work', 5)).toBeNull()
  })
})
