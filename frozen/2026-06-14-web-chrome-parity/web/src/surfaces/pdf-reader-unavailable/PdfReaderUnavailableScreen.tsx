import type { ScenarioId } from '../../harness/scenarios'
import { PDF_READER_UNAVAILABLE_FIXTURES } from './fixtures'
import './pdf-reader-unavailable.css'

/**
 * PDF Reader Unavailable surface — iOS `PDFReaderView.errorView` 的 web 鏡像。
 *
 * Scene（PDFReaderViewScenarios，layout=.fill）：
 *   PDFReaderView 對 fileName 無實體檔的 synthetic Book → loadDocument() 短路到
 *   loadError（isReadableFile=false 分支）→ body 走 errorView(message)。
 *
 * errorView：
 *   ScrollView { VStack[ Spacer(minLength s7=32) ·
 *     AppEmptyStateCard(style=.themed).padding(.h, pageHorizontalPadding s5=20) ·
 *     Spacer(minLength s7=32) ].frame(maxWidth:.infinity) }
 *   ZStack(.bottom) 無 PDF 底色 → 透明畫布，白卡浮於上緣。
 *
 * AppEmptyStateCard(style=.themed)：AppSectionCard(.themed) 包 AppEmptyStateContent：
 *   VStack(spacing 14)[
 *     Image(exclamationmark.triangle).font(hero light=serif40) / tertiaryText ·
 *     Text("無法開啟 PDF").font(h2 semibold=serif22 bold) / primaryText ·
 *     Text(description).font(body=sans17) / secondaryText, centered ·
 *     Button(.appAction(.outline)) Label(arrow.clockwise + "重試載入") ]
 *   .padding(.vertical, 12)
 *
 * 量測（catalog PNG 1179×2556 dpr3，÷3 得 pt）：
 *   corner alpha=0（透明畫布）、card alpha=1 srgba(255,255,255,1)=#fff。
 *   card top y≈270→90pt（safe-area≈59 + Spacer s7=32）、left x≈55→18pt（≈s5）。
 *   icon srgba(138,137,131)=#8A8983=--text-tertiary ✓
 *   desc srgba(107,106,101)=#6B6A65=--text-secondary ✓
 *   → manifest transparent:true，CSS phone-frame 透明。
 */
export function PdfReaderUnavailableScreen({
  scenario,
}: {
  scenario: ScenarioId<'pdf-reader-unavailable'>
}) {
  const fixture = PDF_READER_UNAVAILABLE_FIXTURES[scenario]
  const Icon = fixture.icon
  const Action = fixture.action
  return (
    <div className="pdf-unavail-surface">
      <div className="pdf-unavail-scroll">
        <div className="pdf-unavail-card">
          <div className="pdf-unavail-content">
            <Icon className="pdf-unavail-icon" size={40} strokeWidth={1.2} />
            <div className="pdf-unavail-title">{fixture.title}</div>
            <div className="pdf-unavail-description">{fixture.description}</div>
            <button type="button" className="pdf-unavail-action">
              <Action.icon className="pdf-unavail-action-icon" size={16} />
              <span>{Action.title}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
