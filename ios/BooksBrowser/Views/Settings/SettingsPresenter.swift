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
    @State private var syncRotation: Double = 0

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
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
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
                    .inlineNavigationBarTitle()
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

                // 今日額度 (always when logged in)
                if state.auth.isLoggedIn {
                    quotaRow
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
        Button {
            actions.resync()
        } label: {
            AppKeyValueRow(
                icon: "arrow.triangle.2.circlepath",
                label: "同步狀態".localized,
                style: .settings(vocabSkin)
            ) {
                if summary.isSyncing {
                    HStack(spacing: vocabSkin.spacing.inlineGap) {
                        Image(systemName: "arrow.triangle.2.circlepath")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.accent)
                            .rotationEffect(.degrees(syncRotation))
                            .onAppear {
                                withAnimation(AppMotion.breathing) {
                                    syncRotation = 360
                                }
                            }
                            .onDisappear { syncRotation = 0 }
                        Text("同步中…".localized)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                } else {
                    SettingsStatusSummaryValue(
                        text: summary.summaryText,
                        color: summary.isConnected ? vocabSkin.palette.success : appTheme.palette.warning
                    )
                }
            }
        }
        .buttonStyle(.plain)
        .disabled(summary.isSyncing)
    }

    private func externalActionRow(_ item: ExternalActionItem) -> some View {
        SettingsNavigationRow(
            icon: item.icon,
            label: item.label.localized,
            action: item.action
        )
    }
}
