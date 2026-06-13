import type { SVGProps } from 'react'

/**
 * SF-Symbol-style glyph factories — shared across all web surfaces.
 *
 * 視覺語言：24×24 grid、stroke:currentColor、純裝飾（aria-hidden）。
 * 與 iOS ContentView.swift SF Symbols 對應；形狀不在此修改。
 *
 * `makeGlyph`       — stroke-only 線條圖示（預設 strokeWidth 1.7）。
 * `makeFilledGlyph` — fill:currentColor 實心圖示。
 *
 * 注意：shell/icons.tsx 的 tab-bar glyph 刻意用 size=25，獨立不共用此工廠。
 */

export function makeGlyph(
  paths: string,
  defaults: { size?: number; strokeWidth?: number } = {},
) {
  const defaultSize = defaults.size ?? 24
  const defaultStrokeWidth = defaults.strokeWidth ?? 1.7
  return function Glyph({
    size = defaultSize,
    strokeWidth = defaultStrokeWidth,
    ...rest
  }: SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
        dangerouslySetInnerHTML={{ __html: paths }}
        {...rest}
      />
    )
  }
}

export function makeFilledGlyph(paths: string) {
  return function FilledGlyph({ size = 24, ...rest }: SVGProps<SVGSVGElement> & { size?: number }) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill="currentColor"
        stroke="none"
        aria-hidden="true"
        focusable="false"
        dangerouslySetInnerHTML={{ __html: paths }}
        {...rest}
      />
    )
  }
}
