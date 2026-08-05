import SwiftUI

// Section 一律是獨立 View struct，不是 computed property —— 真機 main thread
// stack 只有 1MB，Debug -Onone 下 inline 展開的 section 樹會把 body 單次求值
// 的泛型 frame 撐到 stack overflow（2026-06-11 取證 dump 定讞；sim 8MB 測不出）。
// 新 section 跟著 SettingsAccountSection / SettingsOtherSection 的模式走。
struct SettingsPresenter: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) var appSkin

    let state: SettingsPresenterState
    let translationSourceLang: Binding<TranslationLanguage>
    let translationTargetLang: Binding<TranslationLanguage>
    let onTranslationLanguageChanged: (TranslationLanguage, TranslationLanguage) async -> Bool
    /// pause review clock 切換(穿透給 SettingsReviewSection)。default no-op 讓
    /// preview / scenario 既有建構零改動,只 SettingsView 注入真實 push closure。
    // var(非 let):let-with-default 不會進 Swift memberwise init,SettingsView 無從注入。
    var onPauseReviewClockChanged: (Bool) async -> Void = { _ in }
    /// mode / 自訂 SRS 參數變更(穿透給 SettingsReviewSection)。同 pause 用 var 以進 memberwise init。
    var onReviewModeChanged: (ReviewSettings) async -> Void = { _ in }
    let manualLoginUserId: Binding<String>?
    let debugLocalServerURL: Binding<String>?
    let actions: SettingsPresenterActions

    @State private var showAccountDetail = false
    @State private var showSubscriptionDetail = false
    @State private var showTranslationLanguage = false
    @State private var showReviewSection = false
    @State private var showReviewCardLayout = false

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
                        SettingsDebugBackendSection(
                            kg: kg,
                            debugLocalServerURL: debugLocalServerURL,
                            actions: actions
                        )
                    }
                    #endif
                }
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                .padding(.top, AppShellMetrics.pageTopPadding)
                .padding(.bottom, AppShellMetrics.pageBottomPadding)
            }
            .background(appSkin.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("設定".localized)
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成".localized, action: actions.dismiss)
                        .fontWeight(.semibold)
                }
            }
            .navigationDestination(isPresented: $showReviewSection) {
                SettingsReviewSection(
                    onPauseChanged: onPauseReviewClockChanged,
                    onModeChanged: onReviewModeChanged
                )
            }
            .navigationDestination(isPresented: $showReviewCardLayout) {
                ReviewCardLayoutEditor()
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
                    .background(appSkin.palette.pageBackground.ignoresSafeArea())
                    .navigationTitle("訂閱".localized)
                    .inlineNavigationBarTitle()
                }
            }
        }
        .enableInjection()
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
            onShowReviewSettings: { showReviewSection = true },
            onShowReviewCardLayout: { showReviewCardLayout = true }
        )
    }

    // MARK: - Section 3: 其他

    // child View struct（原 computed property）；不得改回內聯 —
    // 見 SettingsOtherSection.swift 檔頭的 stack 約束。
    private var otherSection: some View {
        SettingsOtherSection(
            syncSummary: state.syncSummary,
            bookSync: state.bookSync,
            isLoggedIn: state.auth.isLoggedIn,
            version: state.about.version,
            actions: actions
        )
    }
}
