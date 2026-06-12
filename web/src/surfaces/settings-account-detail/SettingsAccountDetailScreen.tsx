import type { ScenarioId } from '../../harness/scenarios'
import { SETTINGS_ACCOUNT_DETAIL_FIXTURES, type AccountDetailFixture, type DangerSection } from './fixtures'
import {
  ChevronRightIcon,
  EnvelopeIcon,
  HourglassIcon,
  PersonCircleIcon,
  PersonIcon,
  SquareArrowUpIcon,
  TrashIcon,
  TrayArrowUpIcon,
  WarningTriangleFillIcon,
  WarningTriangleIcon,
} from './icons'
import './settings-account-detail.css'

/**
 * Settings Account Detail surface — iOS `SettingsAccountDetailView` 的 web 鏡像。
 *
 * 結構（SettingsAccountDetailView.swift）：
 *   NavigationStack { ScrollView {
 *     VStack(spacing sectionSpacing=24)[
 *       accountInfoCard      // 帳號資訊（名稱 列 + 信箱 列）
 *       (isLoggedIn) dataManagementCard  // 資料管理（匯出 CSV nav 列 + footer）
 *       (danger != nil) dangerCard       // 危險操作（狀態卡 + 刪除鈕 + footer）
 *     ]
 *     .padding(h pageHorizontalPadding=20 / top pageTopPadding=12 / bottom pageBottomPadding=64)
 *   }.background(pageBackground).navigationTitle("帳號詳情").inline }
 *
 * 每個 section = VStack(spacing sectionGap=14)[SettingsSectionHeader · .settingsCard · (footer)]。
 *   - SettingsSectionHeader：Label(icon, title)、caption→measured 14 bold / secondaryText、leading s1=4。
 *   - .settingsCard：AppSectionCard(padding 0, .settings) — cardBg、cardBorder 1px、radius card(measured ≈12)。
 *   - AppKeyValueRow.settings：HStack(s3=12)[icon(w22, iconSmall 12 / secondary) · label(body 15 / primary)
 *       · Spacer · content]、padding h cardPadding=18 / v 13、minHeight 50。
 *   - SettingsStatusValue：caption 12 / secondaryText、trailing、lineLimit 1（長字串 ellipsis）。
 *   - SettingsDivider(default inset 50)：hairline / divider 色、左內縮 50。
 *   - SettingsNavigationRow：AppKeyValueRow + trailing chevron.right(iconTiny 10 / tertiary)。
 *   - SettingsSectionFooter：caption 12 / tertiaryText、lineSpacing 3、leading s1=4。
 *
 * danger 卡：VocabStateMessageCard(.vocab)（AppStateMessageCard：cardBg、cardBorder 1px、
 *   radius control=6、padding v12/h14、VStack(s2=8)[head(iconSmall accent + title body semibold)
 *   · desc(caption / secondary)]）+ 刪除鈕(.appAction destructive：destructive 10% fill /
 *   22% border、label body 15 / destructive + trash trailing) + footer。
 *
 * catalog scene = .fill（1179×2556、alpha-mean=1 不透明全幅 pageBackground）：渲染完整
 * NavigationStack 螢幕，含 inline nav title「帳號詳情」（measured：light 為比背景亮的白字）。
 * 故**不透明捕捉**（無 transparent flag）；幾何沿用 `settings` 全螢幕 surface（同 nav/page/
 * section 家族、同一 catalog）已校準的 measured 值。
 */
export function SettingsAccountDetailScreen({ scenario }: { scenario: ScenarioId<'settings-account-detail'> }) {
  const fixture: AccountDetailFixture = SETTINGS_ACCOUNT_DETAIL_FIXTURES[scenario]
  return (
    <div className="sad">
      <header className="sad-nav">
        <h1 className="sad-nav-title">帳號詳情</h1>
      </header>

      <div className="sad-scroll">
        {/* 帳號資訊 */}
        <section className="sad-section">
          <h2 className="sad-section-header">
            <PersonCircleIcon size={15} />
            帳號資訊
          </h2>
          <div className="sad-card">
            <div className="sad-row">
              <span className="sad-row-icon">
                <PersonIcon size={15} />
              </span>
              <span className="sad-row-label">名稱</span>
              <span className="sad-spacer" />
              <span className="sad-status-value">{fixture.displayName}</span>
            </div>

            {fixture.email && fixture.email.length > 0 ? (
              <>
                <div className="sad-divider" />
                <div className="sad-row">
                  <span className="sad-row-icon">
                    <EnvelopeIcon size={15} />
                  </span>
                  <span className="sad-row-label">信箱</span>
                  <span className="sad-spacer" />
                  <span className="sad-status-value">{fixture.email}</span>
                </div>
              </>
            ) : null}
          </div>
        </section>

        {/* 資料管理（僅已登入） */}
        {fixture.isLoggedIn ? (
          <section className="sad-section">
            <h2 className="sad-section-header">
              <TrayArrowUpIcon size={15} />
              資料管理
            </h2>
            <div className="sad-card">
              <button className="sad-row sad-nav-row" type="button">
                <span className="sad-row-icon">
                  <SquareArrowUpIcon size={15} />
                </span>
                <span className="sad-row-label">匯出全部單字 CSV</span>
                <span className="sad-spacer" />
                <ChevronRightIcon className="sad-nav-chevron" size={10} strokeWidth={1.2} />
              </button>
            </div>
            <p className="sad-footer">將所有單字本內的單字匯出為 CSV，方便備份或匯入其他工具。</p>
          </section>
        ) : null}

        {/* 危險操作 */}
        {fixture.danger ? <DangerSectionView danger={fixture.danger} /> : null}
      </div>
    </div>
  )
}

function DangerSectionView({ danger }: { danger: DangerSection }) {
  const deleting = danger.isDeletingAccount
  return (
    <section className="sad-section">
      <h2 className="sad-section-header">
        <WarningTriangleIcon size={15} />
        危險操作
      </h2>

      {/* VocabStateMessageCard(.vocab) */}
      <div className="sad-state-card">
        <div className="sad-state-head">
          {deleting ? (
            <HourglassIcon className="sad-state-icon" size={12} />
          ) : (
            <WarningTriangleFillIcon className="sad-state-icon" size={12} />
          )}
          <span className="sad-state-title">{deleting ? '正在刪除帳號' : '此操作不可逆'}</span>
        </div>
        <p className="sad-state-desc">
          {deleting
            ? '系統正在刪除帳號與雲端資料，完成前請勿關閉 app。'
            : '刪除後會移除帳號與所有雲端資料，且無法復原。'}
        </p>
      </div>

      {/* 刪除鈕 — .settingsCard 包 Button(.appAction destructive) */}
      <div className="sad-card sad-delete-card">
        <button className="sad-delete-button" type="button" disabled={deleting}>
          <span className="sad-delete-label">{deleting ? '刪除中...' : '刪除帳號與雲端資料'}</span>
          <span className="sad-delete-spacer" />
          <TrashIcon className="sad-delete-icon" size={10} strokeWidth={1.4} />
        </button>
      </div>

      <p className="sad-footer">此操作不可逆，會刪除帳號與所有雲端資料。</p>
    </section>
  )
}
