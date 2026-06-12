import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_SEARCH_FIELD_FIXTURES } from './fixtures'
import { MagnifyingGlassIcon, XmarkCircleFillIcon } from './icons'
import './vocab-search-field.css'

/**
 * VocabSearchField surface — iOS `VocabSearchField` → `AppSearchField(style: .vocab)`
 * 的 web 鏡像（Vocab Shell chrome 層全寬搜尋欄）。
 *
 * iOS view tree（AppShellComponents.swift AppSearchField）：
 *   HStack(spacing s2=8)[
 *     Image("magnifyingglass").font(iconSmall=symbol12medium).fg(tertiaryText)
 *     TextField(prompt / text).font(body=sans15).fg(primaryText)
 *     if !text.isEmpty: Button{ Image("xmark.circle.fill")
 *         .font(iconMedium=symbol14medium).fg(quaternaryText) }
 *   ]
 *   .padding(.h s3=12, .v rowPadding=9)
 *   .background(RoundedRectangle(cornerRadius control=6).fill(mutedFill))
 *   .overlay(RoundedRectangle(control=6).stroke(divider, 1))
 *
 * `.vocab` style tokens：icon=tertiaryText、text=primaryText、clear=quaternaryText、
 * bg=mutedFill、border=divider、radius=control(6)。空態 prompt 文字色 = SwiftUI
 * placeholder（secondaryLabel）；此處以 tertiaryText 近似（iOS TextField placeholder
 * 走系統 placeholderText ≈ tertiary）。
 *
 * Scene = .frame(maxWidth:.infinity).padding(24)（fillH，全裝置寬）。catalog
 * 元件 scene 畫布透明（corner srgba 0）：`?crop=component` 令 surface 與 phone-frame
 * 透明、shots `transparent:true` → web 與 ref 同為 bar-over-transparent。
 */
export function VocabSearchFieldScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-search-field'>
}) {
  const { text, prompt } = VOCAB_SEARCH_FIELD_FIXTURES[scenario]
  const isEmpty = text.length === 0
  return (
    <div className="vocab-search-field-surface">
      <div className="vocab-search-field" role="search">
        <MagnifyingGlassIcon size={17} className="vocab-search-field-icon" />
        <span
          className="vocab-search-field-text"
          data-placeholder={isEmpty ? '1' : undefined}
        >
          {isEmpty ? prompt : text}
        </span>
        {!isEmpty && (
          <span className="vocab-search-field-clear" role="button" aria-label="清除">
            <XmarkCircleFillIcon size={19} />
          </span>
        )}
      </div>
    </div>
  )
}
