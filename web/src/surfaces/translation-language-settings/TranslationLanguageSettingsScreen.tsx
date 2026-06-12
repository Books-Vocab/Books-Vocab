import type { ReactNode } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import {
  SOURCE_LANGUAGES,
  TARGET_LANGUAGES,
  TRANSLATION_LANG_FIXTURES,
  type TranslationLanguage,
} from './fixtures'
import { BookIcon, CharacterBubbleIcon, CheckmarkIcon } from './icons'
import './translation-language-settings.css'

/**
 * TranslationLanguageSettings surface — iOS `TranslationLanguageSettingsView`
 * （翻譯語言設定）的 web 鏡像。
 *
 * iOS = ScrollView{ VStack(sectionSpacing=24)[ source section, target section ] }，
 * page padding(h20 t12 b48)、themed pageBackground（**非** 系統 grouped）、inline nav title
 * 「翻譯語言」在此 themed 背景上幾近隱形（catalog ref 量測 nav 區無深色像素）→ nav 區留空。
 *
 * 每 section = VStack(sectionGap=14)[
 *   SettingsSectionHeader = Label(icon + title, caption=sans12bold / secondaryText, leading inset s1=4),
 *   settingsCard = AppSectionCard(.settings)：cardBackground 白 + cardBorder 1pt + radius card=8，內含
 *     ForEach 語言列（列間 SettingsDivider 1pt / leadingInset 50），
 *   SettingsSectionFooter = caption(sans12bold) / tertiaryText / lineSpacing 3 / inset s1=4
 * ]
 *
 * 語言列 = SettingsSelectableRow：HStack(inlineGap=8)[flag(body15), name(body15 primary), Spacer,
 *   selected→checkmark(iconSmall symbol12 / accent)]，padding(h cardPadding=18 / v rowPadding=9)，
 *   selected 背景 accent.opacity(0.08)。
 *
 * 量自 ref（1179×2556 native，÷3=pt）：pageBg #F7F6F3(=--page-bg)、card 白、selected 列 tint
 * #F1F4F7(=accent#4D7396@0.08 疊白)、checkmark #4D7396(=--accent)、header 文字 ≈#6F6E6A(=--text-secondary)。
 *
 * catalog scene = .fill opaque（4 scene alpha-mean 皆=1）→ 全 phone-frame 不透明捕捉，無 transparent flag。
 */
export function TranslationLanguageSettingsScreen({
  scenario,
}: {
  scenario: ScenarioId<'translation-language-settings'>
}) {
  const fx = TRANSLATION_LANG_FIXTURES[scenario]

  return (
    <div className="tls-surface">
      {/* inline nav bar — 標題於 themed bg 近隱形（ref 無深色像素）→ 留空 103pt */}
      <div className="tls-nav" />

      <div className="tls-scroll">
        <Section
          icon={<BookIcon className="tls-header-icon" />}
          title="閱讀語言"
          footer="書籍的語言"
          languages={SOURCE_LANGUAGES}
          selectedId={fx.sourceId}
        />
        <Section
          icon={<CharacterBubbleIcon className="tls-header-icon" />}
          title="翻譯語言"
          footer="翻譯與解釋會以此語言呈現"
          languages={TARGET_LANGUAGES}
          selectedId={fx.targetId}
        />
      </div>
    </div>
  )
}

function Section({
  icon,
  title,
  footer,
  languages,
  selectedId,
}: {
  icon: ReactNode
  title: string
  footer: string
  languages: TranslationLanguage[]
  selectedId: string
}) {
  return (
    <section className="tls-section">
      <div className="tls-header">
        {icon}
        <span className="tls-header-title">{title}</span>
      </div>

      <div className="tls-card">
        {languages.map((lang, index) => (
          <div key={lang.id}>
            {index > 0 ? <div className="tls-divider" /> : null}
            <LanguageRow lang={lang} selected={lang.id === selectedId} />
          </div>
        ))}
      </div>

      <div className="tls-footer">{footer}</div>
    </section>
  )
}

function LanguageRow({
  lang,
  selected,
}: {
  lang: TranslationLanguage
  selected: boolean
}) {
  return (
    <div className="tls-row" data-selected={selected ? '1' : undefined}>
      <span className="tls-flag">{lang.flag}</span>
      <span className="tls-name">{lang.nativeName}</span>
      <span className="tls-spacer" />
      {selected ? <CheckmarkIcon className="tls-check" /> : null}
    </div>
  )
}
