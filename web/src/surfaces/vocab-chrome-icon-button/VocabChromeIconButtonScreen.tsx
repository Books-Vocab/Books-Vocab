import type { ScenarioId } from '../../harness/scenarios'
import { VOCAB_CHROME_ICON_BUTTON_FIXTURES } from './fixtures'
import './vocab-chrome-icon-button.css'

/**
 * VocabChromeIconButton surface — iOS `VocabChromeIconButton` 的 web 鏡像。
 *
 * 視圖樹：Button → VocabChromeSurface(fill cardBackground, border cardBorder,
 * radius control=sm/6) { Image(systemName).font(iconMedium=symbol 14 .medium)
 * .foregroundStyle(tone ?? secondaryText).frame(chromeButtonSize=32 × 32) }，
 * 再外擴觸控目標到 44×44（視覺維持 32pt，frame minWidth/minHeight 不放大版面）。
 *
 * catalog 元件 scene 畫布透明（component-isolated，corner srgba 0）：surface
 * 為 44pt touch box + scene wrapper .padding(24) 的 intrinsic 緊裹盒，crop 截取、
 * shots transparent:true。Toned tone = SwiftUI .accentColor（系統藍），非 appSkin。
 */
export function VocabChromeIconButtonScreen({
  scenario,
}: {
  scenario: ScenarioId<'vocab-chrome-icon-button'>
}) {
  const { Icon, ariaLabel, toned } = VOCAB_CHROME_ICON_BUTTON_FIXTURES[scenario]
  return (
    <div className="vocab-chrome-icon-button-surface">
      <button type="button" className="vocab-chrome-icon-button" aria-label={ariaLabel}>
        <span className="vocab-chrome-icon-button-card">
          <Icon
            className={
              toned
                ? 'vocab-chrome-icon-button-glyph vocab-chrome-icon-button-glyph--toned'
                : 'vocab-chrome-icon-button-glyph'
            }
          />
        </span>
      </button>
    </div>
  )
}
