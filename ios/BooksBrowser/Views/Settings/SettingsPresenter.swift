import SwiftUI

struct SettingsPresenter: View {
    @Environment(\.appTheme) var appTheme
    @Environment(\.vocabSkin) var vocabSkin
    @Environment(\.quotaStore) var quotaStore

    private struct ExternalActionItem: Identifiable {
        let icon: String
        let label: String
        let action: () -> Void

        var id: String { label }
    }

    let state: SettingsPresenterState
    let optionalIntegrationApiKey: Binding<String>
    let translationSourceLang: Binding<TranslationLanguage>
    let translationTargetLang: Binding<TranslationLanguage>
    let onTranslationLanguageChanged: (TranslationLanguage, TranslationLanguage) -> Void
    let manualLoginUserId: Binding<String>?
    let debugLocalServerURL: Binding<String>?
    let actions: SettingsPresenterActions

    @State private var showAccountDetail = false
    @State private var showSubscriptionDetail = false
    @State private var showTranslationLanguage = false
    @State private var showReviewSection = false

    private var externalActionItems: [ExternalActionItem] {
        [
            .init(icon: "hand.raised", label: "隱私政策", action: actions.openPrivacyPolicy),
            .init(icon: "doc.text", label: "服務條款", action: actions.openTermsOfService),
            .init(icon: "questionmark.circle", label: "支援", action: actions.openSupport),
            .init(icon: "star", label: "為 App 評分", action: actions.requestAppRating)
        ]
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: AppShellMetrics.sectionSpacing) {
                    // Section 1: 帳號
                    accountSection

                    // Section 2: 偏好
                    preferencesSection

                    // Section 3: 其他
                    otherSection

                    // DEBUG 後端切換
                    #if DEBUG
                    if let kg = state.kg, let debugLocalServerURL {
                        debugBackendSection(kg: kg, debugLocalServerURL: debugLocalServerURL)
                    }
                    #endif
                }
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                .padding(.top, AppShellMetrics.pageTopPadding)
                .padding(.bottom, AppShellMetrics.pageBottomPadding)
            }
            .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("設定".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成".localized, action: actions.dismiss)
                        .fontWeight(.semibold)
                }
            }
            .navigationDestination(isPresented: $showReviewSection) {
                SettingsReviewSection()
            }
            .navigationDestination(isPresented: $showAccountDetail) {
                SettingsAccountDetailView(
                    authState: state.auth,
                    dangerState: state.danger,
                    actions: actions
                )
            }
            .navigationDestination(isPresented: $showTranslationLanguage) {
                TranslationLanguageSettingsView(
                    sourceLang: translationSourceLang,
                    targetLang: translationTargetLang,
                    onChanged: onTranslationLanguageChanged
                )
            }
            .navigationDestination(isPresented: $showSubscriptionDetail) {
                if let subscription = state.subscription {
                    ScrollView {
                        VStack(spacing: AppShellMetrics.sectionSpacing) {
                            SettingsSubscriptionSection(
                                state: subscription,
                                actions: actions
                            )
                        }
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        .padding(.top, AppShellMetrics.pageTopPadding)
                        .padding(.bottom, AppShellMetrics.pageBottomPadding)
                    }
                    .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
                    .navigationTitle("訂閱".localized)
                    .navigationBarTitleDisplayMode(.inline)
                }
            }
        }
    }

    // MARK: - Section 1: 帳號

    private var accountSection: some View {
        SettingsAccountSection(
            state: state.auth,
            subscription: state.subscription,
            manualLoginUserId: manualLoginUserId,
            actions: actions,
            onShowAccountDetail: { showAccountDetail = true },
            onShowSubscriptionDetail: { showSubscriptionDetail = true }
        )
    }

    // MARK: - Section 2: 偏好

    private var preferencesSection: some View {
        SettingsPreferencesSection(
            state: state.preferences,
            actions: actions,
            onShowTranslationLanguage: { showTranslationLanguage = true },
            onShowReviewSettings: { showReviewSection = true }
        )
    }

    // MARK: - Section 3: 其他

    private var otherSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "其他".localized, icon: "ellipsis.circle")

            VStack(spacing: 0) {
                // 同步狀態 (only when logged in)
                if let syncSummary = state.syncSummary {
                    syncSummaryRow(syncSummary)
                    SettingsDivider()
                }

                // 今日額度 (only when logged in and used)
                if quotaStore.fraction < 1.0, state.auth.isLoggedIn {
                    quotaRow
                    SettingsDivider()
                }

                // Mochi 整合 (only when logged in)
                if let optionalIntegration = state.optionalIntegration {
                    mochiRow(optionalIntegration)
                    SettingsDivider()
                }

                ForEach(Array(externalActionItems.enumerated()), id: \.element.id) { index, item in
                    externalActionRow(item)

                    if index < externalActionItems.count - 1 {
                        SettingsDivider()
                    }
                }
            }
            .settingsCard()

            // Version footer
            Text("\("版本".localized) \(state.about.version)")
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .frame(maxWidth: .infinity)
                .padding(.top, vocabSkin.spacing.tinyGap)
        }
    }

    // MARK: - Sync Summary Row

    private func syncSummaryRow(_ summary: SettingsPresenterState.SyncSummaryState) -> some View {
        SettingsRow(icon: "arrow.triangle.2.circlepath", label: "同步狀態".localized) {
            HStack(spacing: 6) {
                Circle()
                    .fill(summary.isConnected ? vocabSkin.palette.success : appTheme.palette.warning)
                    .frame(width: 8, height: 8)
                Text(summary.summaryText)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .lineLimit(1)
            }
        }
    }

    private func externalActionRow(_ item: ExternalActionItem) -> some View {
        Button(action: item.action) {
            SettingsRow(icon: item.icon, label: item.label.localized) {
                SettingsTrailingChevronIcon()
            }
        }
        .buttonStyle(.plain)
    }
}
