import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_TAB_SELECTOR_FIXTURES } from './fixtures'
import './vocab-tab-selector.css'

/**
 * VocabTabSelector surface — iOS `VocabTabSelector` → `AppTabSelector(style: .vocab)`
 * 的 web 鏡像（Vocab Shell review-state 全寬 segmented filter bar）。
 *
 * iOS view tree（AppTabSelector.swift）：
 *   HStack(spacing s2=8)[                                  ← 容器分段間距
 *     ForEach option → Button { appChipLabel(...) }
 *   ]
 *   .padding(tinyGap=3)                                    ← 容器內距
 *   .background(RoundedRectangle(containerRadius = control+4 = 6+4 = 10)
 *                 .fill(.vocab: stageBackground))
 *
 *   appChipLabel（chip 本體）：
 *     HStack(spacing 6)[
 *       (systemImage — 本 surface 無)
 *       Text(title).font(caption = sans12bold).fg(sel ? primaryText : secondaryText)
 *       if count != nil:
 *         Text("\(count)").font(monoLabel = mono10bold).monospacedDigit()
 *           .frame(minWidth: 26)
 *           .padding(.h compactChipHorizontalPadding=6, .v microGap=6)
 *           .background(Capsule.fill(sel ? primaryText@0.08 : mutedFill))
 *     ]
 *     .frame(maxWidth:.infinity)                           ← 三段均分裝置寬
 *     .padding(.h s2=8, .v s2=8)
 *     .background(Capsule.fill(sel ? mutedFill : .clear))  ← selected pill
 *     .overlay(Capsule.stroke(.clear, 1))                  ← .vocab：border 全 clear
 *     .overlay(Capsule.stroke(.clear, 0.8).padding(-0))    ← outer border clear
 *
 * `.vocab` style（AppTabSelector.swift extension）：selectedBorder/unselectedBorder/
 * selectedOuterBorder/unselectedOuterBorder = .clear、selectedBackground = mutedFill、
 * unselectedBackground = .clear、containerBackground = stageBackground、
 * countSelectedFill = primaryText.opacity(0.08)、countUnselectedFill = mutedFill。
 *
 * Scene = VocabTabSelector(...).padding(24)（layout .fillH，全裝置寬 393pt）。catalog
 * 元件 scene 畫布透明（corner srgba 0）：`?crop=component` 令 surface 與 phone-frame
 * 透明、shots `transparent:true` → web 與 ref 同為 bar-over-transparent。
 */
export function VocabTabSelectorScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-tab-selector'>
}) {
  const { options, selected } = VOCAB_TAB_SELECTOR_FIXTURES[scenario]
  return (
    <div className="vocab-tab-selector-surface">
      <div className="vocab-tab-selector" role="tablist">
        {options.map((option) => {
          const isSelected = option.id === selected
          return (
            <span
              key={option.id}
              className="vocab-tab-selector-chip"
              role="tab"
              aria-selected={isSelected}
              data-selected={isSelected ? '1' : undefined}
            >
              <span className="vocab-tab-selector-title">{option.title}</span>
              {option.count != null && (
                <span className="vocab-tab-selector-count">{option.count}</span>
              )}
            </span>
          )
        })}
      </div>
    </div>
  )
}
