import { useCallback, useState } from 'react'
import type { ReactNode } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { useAuth } from '../../auth'
import './delete-account-sheet.css'
import {
  ACKNOWLEDGEMENT_ROWS,
  CONSEQUENCE_ROWS,
  DELETE_ACCOUNT_COPY,
  DELETE_ACCOUNT_FIXTURES,
} from './fixtures'
import {
  BookClosedIcon,
  BooksVerticalIcon,
  CheckmarkSealIcon,
  CheckmarkSquareIcon,
  ExclamationTriangleFillIcon,
  GraphConnectedIcon,
  KeyboardIcon,
  PersonCropCircleIcon,
  TrashFillIcon,
  TrashIcon,
} from './icons'

/**
 * SettingsDeleteAccountSheet surface — iOS 多步驟刪除帳號確認 sheet 的 web 鏡像。
 *
 * 視圖樹：NavigationStack{ ScrollView{ VStack(spacing sheetSectionSpacing=20)[
 *   hero（exclamationmark.triangle.fill symbolHero 44 / displayTitle serif 24 bold /
 *        body sans 15 secondaryText centered, lineSpacing 4） ·
 *   consequencesCard（SettingsSectionHeader(caption sans12 bold) +
 *        destructiveBg 卡 radius card=8、destructive @22% 描邊、5 列 icon+body） ·
 *   acknowledgementsCard（header + settingsCard 白卡、3 toggle row + divider，
 *        toggle 預設 off → 灰膠囊） ·
 *   confirmationTypeCard（header + 白卡內 caption 提示 + 空 TextField(placeholder DELETE)
 *        pageBackground 底、cardBorder 描邊 radius control=6） ·
 *   actionStack（destructive 主鈕 0.55 不透明(disabled) + neutral 取消鈕）
 * ] .padding(sheetPaddingCompact=20) }
 *   .background(pageBackground #F7F6F3) .navigationTitle("確認刪除帳號") inline + 取消 toolbar }
 *
 * 兩 scenario 可見內容相同；deleting 時 delete 鈕內為 ProgressView + 「刪除中…」，
 * idle 時為 trash.fill + 「永久刪除帳號」。toggle/confirm 為內部 @State，catalog 兩態皆
 * 初始（全 off、confirm 空、按鈕 disabled @0.55）。
 *
 * catalog scene = .fill opaque（pageBackground 不透明）→ 全 phone-frame 不透明捕捉，無
 * transparent flag。
 */

export function DeleteAccountSheetScreen({
  scenario,
}: {
  scenario: ScenarioId<'delete-account-sheet'>
}) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    return <DeleteAccountSheetScreenApi />
  }
  return <DeleteAccountSheetScreenFixture scenario={scenario} />
}

function DeleteAccountSheetScreenFixture({ scenario }: { scenario: ScenarioId<'delete-account-sheet'> }) {
  const fx = DELETE_ACCOUNT_FIXTURES[scenario]
  return <DeleteAccountSheetBody isDeleting={fx.isDeleting} />
}

function DeleteAccountSheetScreenApi() {
  const { logout } = useAuth()
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const handleDelete = useCallback(async () => {
    setIsDeleting(true)
    setDeleteError(null)
    try {
      // Try DELETE /api/user/account — backend may not have this endpoint yet
      const res = await fetch('/api/user/account', { method: 'DELETE' })
      if (!res.ok) {
        throw new Error('DELETE endpoint not available')
      }
      // Success: logout
      logout()
    } catch {
      // Backend endpoint not available — logout only
      setDeleteError('後端刪除帳號端點尚未實作，僅執行登出。')
      logout()
    } finally {
      setIsDeleting(false)
    }
  }, [logout])

  return <DeleteAccountSheetBody isDeleting={isDeleting} onDelete={handleDelete} deleteError={deleteError} />
}

function DeleteAccountSheetBody({
  isDeleting,
  onDelete,
  deleteError,
}: {
  isDeleting: boolean
  onDelete?: () => void
  deleteError?: string | null
}) {
  const c = DELETE_ACCOUNT_COPY
  const [confirmText, setConfirmText] = useState('')
  const [acknowledgements, setAcknowledgements] = useState<boolean[]>(() =>
    ACKNOWLEDGEMENT_ROWS.map(() => false),
  )

  const allAcked = acknowledgements.every(Boolean)
  const canDelete = allAcked && confirmText === c.confirmationPhrase && !isDeleting

  return (
    <div className="das-surface">
      {/* inline nav bar：status 59 + bar 44；取消 cancellationAction（leading）+ 置中標題 */}
      <div className="das-nav">
        <span className="das-nav-cancel">{c.cancelTitle}</span>
        <span className="das-nav-title">{c.navigationTitle}</span>
      </div>

      <div className="das-scroll">
        <div className="das-content">
          {/* hero */}
          <div className="das-hero">
            <ExclamationTriangleFillIcon className="das-hero-icon" size={44} />
            <div className="das-hero-title">{c.heroTitle}</div>
            <div className="das-hero-desc">{c.heroDescription}</div>
          </div>

          {/* consequences — destructiveBg 卡 */}
          <section className="das-section">
            <SectionHeader icon={<TrashIcon className="das-header-icon" size={13} />}>
              {c.consequencesTitle}
            </SectionHeader>
            <div className="das-card das-card--consequences">
              {CONSEQUENCE_ROWS.map((row) => (
                <div key={row.icon} className="das-consequence-row">
                  <span className="das-consequence-icon">
                    <ConsequenceGlyph icon={row.icon} />
                  </span>
                  <span className="das-consequence-text">{row.text}</span>
                </div>
              ))}
            </div>
          </section>

          {/* acknowledgements — 白卡 + 3 toggle row */}
          <section className="das-section">
            <SectionHeader
              icon={<CheckmarkSquareIcon className="das-header-icon" size={13} />}
            >
              {c.acknowledgementsTitle}
            </SectionHeader>
            <div className="das-card das-card--settings">
              {ACKNOWLEDGEMENT_ROWS.map((title, i) => (
                <div key={title}>
                  {i > 0 ? <div className="das-divider" /> : null}
                  <div className="das-ack-row">
                    <span className="das-ack-title">{title}</span>
                    <button
                      type="button"
                      className="das-toggle"
                      data-on={acknowledgements[i]}
                      onClick={() =>
                        setAcknowledgements((prev) => {
                          const next = [...prev]
                          next[i] = !next[i]
                          return next
                        })
                      }
                    />
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* type-to-confirm — 白卡內提示 + 空 TextField */}
          <section className="das-section">
            <SectionHeader icon={<KeyboardIcon className="das-header-icon" size={13} />}>
              {c.confirmationTitle}
            </SectionHeader>
            <div className="das-card das-card--settings das-card--confirm">
              <div className="das-confirm-prompt">{c.confirmationPrompt}</div>
              <input
                className="das-textfield"
                type="text"
                placeholder={c.confirmationPhrase}
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
              />
            </div>
          </section>

          {/* action stack */}
          <div className="das-actions">
            <button
              type="button"
              className="das-btn das-btn--destructive"
              disabled={!canDelete}
              onClick={onDelete}
            >
              {isDeleting ? (
                <span className="das-spinner" aria-hidden="true" />
              ) : (
                <TrashFillIcon className="das-btn-icon" size={14} />
              )}
              <span className="das-btn-label">
                {isDeleting ? c.deletingTitle : c.deleteTitle}
              </span>
            </button>
            <button type="button" className="das-btn das-btn--neutral">
              {c.cancelTitle}
            </button>
          </div>

          {deleteError && (
            <p className="das-error">{deleteError}</p>
          )}
        </div>
      </div>
    </div>
  )
}

function SectionHeader({
  icon,
  children,
}: {
  icon: ReactNode
  children: ReactNode
}) {
  // SettingsSectionHeader = AppSectionHeader → Label(title, systemImage) caption(sans12 bold)
  // /secondaryText，.padding(.leading s1=4)。
  return (
    <div className="das-section-header">
      {icon}
      <span>{children}</span>
    </div>
  )
}

function ConsequenceGlyph({ icon }: { icon: string }) {
  const cls = 'das-consequence-glyph'
  switch (icon) {
    case 'person.crop.circle':
      return <PersonCropCircleIcon className={cls} size={14} />
    case 'books.vertical':
      return <BooksVerticalIcon className={cls} size={14} />
    case 'point.3.connected.trianglepath.dotted':
      return <GraphConnectedIcon className={cls} size={14} />
    case 'book.closed':
      return <BookClosedIcon className={cls} size={14} />
    case 'checkmark.seal':
      return <CheckmarkSealIcon className={cls} size={14} />
    default:
      return null
  }
}
