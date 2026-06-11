import { describe, expect, it } from 'vitest'
import {
  FONT_SIZE_MAX,
  FONT_SIZE_MIN,
  bodyCss,
  canDecrease,
  canIncrease,
  decreaseFontSize,
  fontSizeText,
  increaseFontSize,
} from './liveSettings'

/**
 * Live reader 字級檔位對齊 iOS ReaderSettings（範圍 0.75…2.0，step 0.125，預設 1.0）。
 * SoT：ios/BooksAndVocab/Views/Reader/ReaderSettingsPanel.swift。
 */
describe('liveSettings font tier (iOS parity)', () => {
  it('clamps decrease at 0.75', () => {
    expect(decreaseFontSize(0.875)).toBeCloseTo(0.75)
    expect(decreaseFontSize(0.75)).toBeCloseTo(0.75)
    expect(canDecrease(0.75)).toBe(false)
    expect(canDecrease(0.875)).toBe(true)
  })

  it('clamps increase at 2.0', () => {
    expect(increaseFontSize(1.875)).toBeCloseTo(2.0)
    expect(increaseFontSize(2.0)).toBeCloseTo(2.0)
    expect(canIncrease(2.0)).toBe(false)
    expect(canIncrease(1.875)).toBe(true)
  })

  it('steps by 0.125 and stays on the iOS grid', () => {
    let size = 1.0
    const seen = [size]
    for (let i = 0; i < 8; i++) {
      size = increaseFontSize(size)
      seen.push(size)
    }
    // 1.0 → 2.0 經 8 步（每步 0.125），末端飽和。
    expect(seen[seen.length - 1]).toBeCloseTo(FONT_SIZE_MAX)
    expect(seen).toContain(1.125)
    expect(seen).toContain(1.5)
  })

  it('formats size text like iOS {n}x', () => {
    expect(fontSizeText(1.0)).toBe('1.0x')
    expect(fontSizeText(0.75)).toBe('0.75x')
    expect(fontSizeText(2.0)).toBe('2.0x')
    expect(fontSizeText(1.5)).toBe('1.5x')
    expect(fontSizeText(1.125)).toBe('1.125x')
  })

  it('bounds match iOS', () => {
    expect(FONT_SIZE_MIN).toBe(0.75)
    expect(FONT_SIZE_MAX).toBe(2.0)
  })
})

describe('bodyCss injection', () => {
  it('scales 19px baseline by fontSize and picks the font family', () => {
    const serif = bodyCss({ fontSize: 1.0, font: 'serif' }, 'http://x')
    expect(serif).toContain('19.0px')
    expect(serif).toContain('CrimsonPro')

    const sansLarge = bodyCss({ fontSize: 2.0, font: 'sans' }, 'http://x')
    expect(sansLarge).toContain('38.0px')
    expect(sansLarge).toContain('ElmsSans')
  })

  it('embeds @font-face with absolute origin (iframe needs absolute URL)', () => {
    const css = bodyCss({ fontSize: 1.0, font: 'serif' }, 'http://localhost:5180')
    expect(css).toContain("url('http://localhost:5180/fonts/CrimsonPro.woff2')")
  })
})
