import type { ScenarioId } from '../../harness/scenarios'
import appIconUrl from '../../assets/app_icon.png'
import { WELCOME_FIXTURES, WELCOME_PAGES } from './fixtures'
import { SparklesIcon, PersonCircleFillIcon } from './icons'
import './welcome.css'

/**
 * 鏡像 ios/BooksAndVocab/Views/Welcome/WelcomeView.swift 的靜態快照面。
 *（中文文案逐字取自 WelcomeView.swift——iOS 端改文案時此處須同步）
 *
 * 版面 = VStack(spacing 0)：
 *   tryItHint（accent.opacity(0.08) 帶、border accent.opacity(0.2)、radius md）
 *   Spacer(min s4) → AppHeroIcon(80, radius appIcon 18, .bottom 12)
 *   TabView(height 240) 內單頁：halo(accent.opacity(0.10) 圓 80=64+16) + hero icon(40)
 *     + STEP n(caption semibold accent, tracking 1.4) + title(h1 serif 28) + subtitle(body 17)
 *   stepIndicator（自繪 capsule page control，.top s2）
 *   Spacer() → ctaStack（登入帳號 primary、開始使用 outline、caption 說明、.bottom 40）
 *
 * catalog scene layout = .fill（全裝置幀，corner = pageBackground 不透明）→ 全 phone-frame
 * 不透明捕捉（無 crop、無 transparent），surface bg = page-bg，與 bookshelf 同模式。
 * Step 3 / Review 與 Step 3 / Dark 在離線 catalog 皆渲染 light 第 3 頁（preferredColorScheme
 * .dark 不生效），故兩 scenario 視覺等同。CTA 為靜態快照（不接真互動）。
 */
export function WelcomeScreen({ scenario }: { scenario: ScenarioId<'welcome'> }) {
  const { activePage } = WELCOME_FIXTURES[scenario]
  const page = WELCOME_PAGES[activePage]
  const Icon = page.icon

  return (
    <div className="welcome">
      {/* tryItHint — 試用提示帶 */}
      <div className="welcome-hint">
        <SparklesIcon className="welcome-hint-spark" size={15} />
        <span className="welcome-hint-text">不用註冊也能先體驗 Demo</span>
        <span className="welcome-hint-action">試用</span>
      </div>

      <div className="welcome-spacer-top" />

      {/* AppHeroIcon — 80×80 app icon，radius appIcon 18 */}
      <img className="welcome-hero-icon" src={appIconUrl} alt="" width={80} height={80} />

      {/* TabView 當前頁（自繪，非可滑動）：halo + icon + STEP + title + subtitle */}
      <div className="welcome-page">
        <div className="welcome-page-halo">
          <Icon className="welcome-page-icon" size={40} strokeWidth={1.7} />
        </div>
        <div className="welcome-page-titles">
          <span className="welcome-page-step">STEP {page.step}</span>
          <span className="welcome-page-title">{page.title}</span>
        </div>
        <p className="welcome-page-subtitle">{page.subtitle}</p>
      </div>

      {/* stepIndicator — 自繪 capsule page control */}
      <div className="welcome-indicator">
        {WELCOME_PAGES.map((_, index) => (
          <span
            key={index}
            className="welcome-dot"
            data-active={index === activePage ? '1' : undefined}
          />
        ))}
      </div>

      <div className="welcome-spacer-bottom" />

      {/* ctaStack — 登入帳號 / 開始使用 / 說明 */}
      <div className="welcome-cta">
        <button type="button" className="welcome-btn welcome-btn-primary">
          <PersonCircleFillIcon className="welcome-btn-icon" size={18} />
          <span>登入帳號</span>
        </button>
        <button type="button" className="welcome-btn welcome-btn-outline">
          開始使用
        </button>
        <p className="welcome-cta-note">登入後可在多裝置同步詞彙與筆記</p>
      </div>
    </div>
  )
}
