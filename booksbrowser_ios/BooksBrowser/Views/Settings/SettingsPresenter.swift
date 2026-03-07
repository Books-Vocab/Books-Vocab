import SwiftUI

struct SettingsPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: SettingsPresenterState
    let mochiApiKey: Binding<String>
    let manualLoginUserId: Binding<String>?
    let actions: SettingsPresenterActions

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    authSection
                    if let subscription = state.subscription {
                        subscriptionSection(subscription)
                    }
                    if let kg = state.kg {
                        kgSection(kg)
                    }
                    if let mochi = state.mochi {
                        mochiSection(mochi)
                    }
                    aboutSection
                    if let danger = state.danger {
                        dangerSection(danger)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 48)
            }
            .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成", action: actions.dismiss)
                        .fontWeight(.semibold)
                }
            }
        }
    }

    private var authSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "帳號", icon: "person.crop.circle")

            VStack(spacing: 0) {
                if state.auth.isLoggedIn {
                    loggedInView
                        .transition(.asymmetric(
                            insertion: .scale(scale: 0.97).combined(with: .opacity),
                            removal: .opacity
                        ))
                } else {
                    loginView
                        .transition(.asymmetric(
                            insertion: .scale(scale: 0.97).combined(with: .opacity),
                            removal: .opacity
                        ))
                }
            }
            .settingsCard()
            .animation(.spring(response: 0.45, dampingFraction: 0.85), value: state.auth.isLoggedIn)
        }
    }

    private var loginView: some View {
        VStack(spacing: 0) {
            VStack(spacing: 10) {
                Image(systemName: "sparkles")
                    .font(vocabSkin.typography.symbolHero)
                    .foregroundStyle(.tertiary)
                    .opacity(state.auth.iconBreathing ? 0.45 : 0.75)
                    .animation(.easeInOut(duration: 2.8).repeatForever(autoreverses: true), value: state.auth.iconBreathing)

                VStack(spacing: 4) {
                    Text("解鎖完整功能")
                        .font(vocabSkin.typography.displayTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)
                    Text("AI 翻譯・知識圖譜・雲端同步")
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }
            }
            .padding(.vertical, 24)
            .frame(maxWidth: .infinity)

            Rectangle()
                .fill(vocabSkin.palette.divider)
                .frame(height: 1)

            VStack(spacing: 10) {
                Button(action: actions.loginWithGoogle) {
                    HStack(spacing: 12) {
                        ZStack {
                            Circle()
                                .fill(.white)
                                .frame(width: 22, height: 22)
                                .shadow(color: .black.opacity(0.08), radius: 2, y: 1)
                            Text("G")
                                .font(vocabSkin.typography.captionStrong)
                                .foregroundStyle(Color(red: 0.87, green: 0.19, blue: 0.19))
                        }
                        Text("以 Google 繼續")
                            .fontWeight(.medium)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(vocabSkin.typography.iconTiny)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }
                }
                .buttonStyle(.plain)
                .padding()
                .background(vocabSkin.palette.pageBackground)
                .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.control))
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control)
                        .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                )

#if DEBUG
                if let manualLoginUserId, let debug = state.auth.debug {
                    Rectangle()
                        .fill(vocabSkin.palette.divider)
                        .frame(height: 1)
                        .padding(.vertical, 8)

                    HStack(spacing: 8) {
                        TextField("帳號 ID（手動）", text: manualLoginUserId)
                            .font(vocabSkin.typography.monoLabel)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)

                        Button("登入", action: actions.manualLogin)
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                    }

                    HStack(spacing: 8) {
                        Button("設為開發者帳號", action: actions.setDeveloperAccount)
                            .buttonStyle(.bordered)
                            .controlSize(.small)

                        Button("清除開發者帳號", action: actions.clearDeveloperAccount)
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                    }

                    if !debug.developerAccountId.isEmpty {
                        Text("目前開發者帳號：\(debug.developerAccountId)")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
#endif

                if let error = state.auth.authError {
                    Text(error)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 8)
                        .padding(.bottom, 4)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 16)
        }
    }

    private var loggedInView: some View {
        VStack(spacing: 0) {
            HStack(spacing: 14) {
                ZStack {
                    Circle()
                        .fill(vocabSkin.palette.mutedFill)
                        .frame(width: 46, height: 46)

                    if let avatarURL = state.auth.avatarURL {
                        AsyncImage(url: avatarURL) { image in
                            image.resizable().scaledToFill()
                        } placeholder: {
                            Image(systemName: "person.fill")
                                .font(vocabSkin.typography.symbolLarge)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                        }
                        .frame(width: 46, height: 46)
                        .clipShape(Circle())
                    } else if let initials = state.auth.userInitials {
                        Text(initials)
                            .font(vocabSkin.typography.sectionTitle)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    } else {
                        Image(systemName: "person.fill")
                            .font(vocabSkin.typography.symbolLarge)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                }

                VStack(alignment: .leading, spacing: 3) {
                    Text(state.auth.displayName)
                        .font(vocabSkin.typography.sectionTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)
                        .lineLimit(1)
                    if let email = state.auth.email {
                        Text(email)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                            .lineLimit(1)
                    }
                }

                Spacer()

                VStack(alignment: .trailing, spacing: 6) {
                    Image(systemName: "checkmark.circle.fill")
                        .font(vocabSkin.typography.symbolLarge)
                        .foregroundStyle(vocabSkin.palette.success)
                        .symbolEffect(.bounce, value: state.auth.isLoggedIn)
#if DEBUG
                    if state.auth.isDeveloper {
                        Text("DEVELOPER")
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(.orange)
                    }
#endif
                }
            }
            .padding(vocabSkin.spacing.cardPadding)

            Rectangle()
                .fill(vocabSkin.palette.divider)
                .frame(height: 1)

            Button(role: .destructive, action: actions.logout) {
                Text("登出帳號")
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.destructive)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 13)
            }
            .buttonStyle(.plain)
        }
    }

    private func kgSection(_ kg: SettingsPresenterState.KGSection) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "Knowledge Graph", icon: "brain.head.profile")

            VStack(spacing: 0) {
                SettingsRow(icon: "server.rack", label: "伺服器") {
                    Text(kg.serverURL)
                        .font(vocabSkin.typography.monoLabel)
                        .multilineTextAlignment(.trailing)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                SettingsDivider()

                SettingsRow(icon: "antenna.radiowaves.left.and.right", label: "連線狀態") {
                    HStack(spacing: 8) {
                        Circle()
                            .fill(kg.isConnected ? vocabSkin.palette.success : Color.orange)
                            .frame(width: 8, height: 8)
                            .shadow(
                                color: (kg.isConnected ? vocabSkin.palette.success : Color.orange).opacity(0.6),
                                radius: kg.connectionPulse ? 5 : 2
                            )
                        Text(kg.isConnected ? "已連線" : "離線")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                }

                if kg.isConnected {
                    SettingsDivider()

                    SettingsRow(icon: "text.book.closed", label: "字庫卡片") {
                        Text("\(kg.serverCardCount) 張")
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                    .transition(.move(edge: .top).combined(with: .opacity))

                    if let lastSyncDescription = kg.lastSyncDescription {
                        SettingsDivider()

                        SettingsRow(icon: "arrow.clockwise", label: "最後同步") {
                            Text(lastSyncDescription)
                                .font(vocabSkin.typography.caption)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                        }
                        .transition(.move(edge: .top).combined(with: .opacity))
                    }
                }
            }
            .settingsCard()
            .animation(.spring(response: 0.35, dampingFraction: 0.8), value: kg.isConnected)
            .animation(.spring(response: 0.35, dampingFraction: 0.8), value: kg.serverCardCount)

            SettingsSectionFooter("KG 伺服器負責生詞 AI 增強與 Mochi 同步。")
        }
    }

    private func subscriptionSection(_ subscription: SettingsPresenterState.SubscriptionSection) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "訂閱", icon: "sparkles.rectangle.stack")

            VStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .top, spacing: 12) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(subscription.planName)
                                .font(vocabSkin.typography.sectionTitle)
                                .foregroundStyle(vocabSkin.palette.primaryText)

                            Text(subscription.summary)
                                .font(vocabSkin.typography.body)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                                .lineSpacing(4)
                        }

                        Spacer()

                        subscriptionBadge(subscription)
                    }

                    Text(subscription.detail)
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)

                    Button(action: actions.showSubscriptionPaywall) {
                        HStack(spacing: 10) {
                            if subscription.isRefreshing {
                                ProgressView()
                                    .controlSize(.small)
                            } else {
                                Image(systemName: "arrow.right.circle.fill")
                                    .font(vocabSkin.typography.iconMedium)
                            }

                            Text(subscription.ctaTitle)
                                .font(vocabSkin.typography.body.weight(.medium))

                            Spacer()
                        }
                        .foregroundStyle(vocabSkin.palette.primaryText)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 12)
                        .background(vocabSkin.palette.pageBackground)
                        .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(subscription.isRefreshing)
                }
                .padding(vocabSkin.spacing.cardPadding)
            }
            .settingsCard()

            SettingsSectionFooter("目前先以狀態卡與 paywall 骨架接上，購買與 restore 流程下一步接 StoreKit 2。")
        }
    }

    private func mochiSection(_ mochi: SettingsPresenterState.MochiSection) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "第三方整合", icon: "puzzlepiece.extension")

            VStack(spacing: 0) {
                SettingsRow(icon: "m.square.fill", label: "Mochi API Key") {
                    HStack(spacing: 6) {
                        SecureField("可選", text: mochiApiKey)
                            .font(vocabSkin.typography.monoLabel)
                            .multilineTextAlignment(.trailing)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                            .disabled(!mochi.isEnabled)

                        Button(action: actions.showMochiInfo) {
                            Image(systemName: "info.circle")
                                .font(vocabSkin.typography.iconMedium)
                                .foregroundStyle(vocabSkin.palette.secondaryText)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .settingsCard()

            SettingsSectionFooter("可選。這是你的使用者層 Mochi 設定，填入後自動將生詞同步至 Mochi 單字卡。")
        }
    }

    private var aboutSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "關於", icon: "info.circle")

            VStack(spacing: 0) {
                SettingsRow(icon: "tag", label: "版本") {
                    Text(state.about.version)
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                SettingsDivider()

                SettingsRow(icon: "person.circle", label: "開發者") {
                    Text(state.about.developerName)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

#if DEBUG
                if let developerAccountId = state.about.developerAccountId {
                    SettingsDivider()

                    SettingsRow(icon: "wrench.and.screwdriver", label: "開發者帳號 ID") {
                        Text(developerAccountId.isEmpty ? "未設定" : developerAccountId)
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                            .lineLimit(1)
                    }
                }
#endif
            }
            .settingsCard()
        }
    }

    private func dangerSection(_ danger: SettingsPresenterState.DangerSection) -> some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "危險操作", icon: "exclamationmark.triangle")

            VStack(spacing: 0) {
                Button(role: .destructive, action: actions.requestDeleteAccount) {
                    HStack {
                        Text(danger.isDeletingAccount ? "刪除中..." : "刪除帳號與雲端資料")
                            .font(vocabSkin.typography.body)
                            .foregroundStyle(vocabSkin.palette.destructive)
                        Spacer()
                        Image(systemName: "trash")
                            .font(vocabSkin.typography.iconTiny)
                            .foregroundStyle(vocabSkin.palette.destructive)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 13)
                    .padding(.horizontal, 16)
                }
                .buttonStyle(.plain)
                .disabled(danger.isDeletingAccount)
            }
            .background(vocabSkin.palette.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                    .stroke(vocabSkin.palette.destructive.opacity(0.5), lineWidth: 1)
            )

            SettingsSectionFooter("此操作不可逆，會刪除帳號與所有雲端資料。")
        }
    }
}

private extension SettingsPresenter {
    func subscriptionBadge(_ subscription: SettingsPresenterState.SubscriptionSection) -> some View {
        let tone: Color
        switch subscription.badgeTone {
        case .neutral:
            tone = vocabSkin.palette.secondaryText
        case .accent:
            tone = vocabSkin.palette.accent
        case .success:
            tone = vocabSkin.palette.success
        }

        return Text(subscription.badgeText)
            .font(vocabSkin.typography.monoLabel)
            .foregroundStyle(tone)
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
            .background(tone.opacity(0.12))
            .clipShape(Capsule())
    }
}

private struct SettingsSectionHeader: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let icon: String

    var body: some View {
        Label(title, systemImage: icon)
            .font(vocabSkin.typography.captionStrong)
            .foregroundStyle(vocabSkin.palette.secondaryText)
            .padding(.leading, 4)
    }
}

private struct SettingsSectionFooter: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(vocabSkin.typography.caption)
            .foregroundStyle(vocabSkin.palette.tertiaryText)
            .lineSpacing(3)
            .padding(.horizontal, 4)
    }
}

private struct SettingsDivider: View {
    @Environment(\.vocabSkin) private var vocabSkin

    var body: some View {
        Rectangle()
            .fill(vocabSkin.palette.divider)
            .frame(height: 1)
            .padding(.leading, 50)
    }
}

private struct SettingsRow<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let icon: String
    let label: String
    let content: Content

    init(icon: String, label: String, @ViewBuilder content: () -> Content) {
        self.icon = icon
        self.label = label
        self.content = content()
    }

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(vocabSkin.typography.iconSmall)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .frame(width: 22, alignment: .center)

            Text(label)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.primaryText)

            Spacer()

            content
        }
        .padding(.horizontal, vocabSkin.spacing.cardPadding)
        .padding(.vertical, 13)
        .frame(minHeight: 50)
    }
}

private extension View {
    func settingsCard() -> some View {
        modifier(SettingsCardModifier())
    }
}

private struct SettingsCardModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        content
            .background(vocabSkin.palette.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                    .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
            )
    }
}

struct MochiInfoSheetView: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(vocabSkin.typography.symbolHero)
                        .foregroundStyle(vocabSkin.palette.accent)
                        .padding(.bottom, 8)

                    Text("關於 Mochi 同步")
                        .font(vocabSkin.typography.displayTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    Text("如果你有在使用 Mochi (mochi.cards) 來複習單字，BooksBrowser 可以自動將你查過並儲存的單字建立成 Mochi 卡片。這個 API Key 會綁定在你的帳號設定，不是伺服器全域設定。")
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .lineSpacing(6)

                    Rectangle()
                        .fill(vocabSkin.palette.divider)
                        .frame(height: 1)

                    Text("如何取得 API Key？")
                        .font(vocabSkin.typography.sectionTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    VStack(alignment: .leading, spacing: 12) {
                        Label("1. 登入網頁版的 app.mochi.cards", systemImage: "1.circle.fill")
                        Label("2. 點擊右上角設定 (Settings)", systemImage: "2.circle.fill")
                        Label("3. 選擇 API 分頁", systemImage: "3.circle.fill")
                        Label("4. 點擊 Generate API key 並複製貼上到前面設定中", systemImage: "4.circle.fill")
                    }
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.secondaryText)

                    Text("這是一個可選功能，就算不填寫 API Key，BooksBrowser 也能完美獨立運作！")
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                        .padding(.top, 16)
                }
                .padding(24)
            }
            .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}

struct SubscriptionPaywallSheet: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.authManager) private var authManager
    @Environment(\.kgService) private var kgService

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Image(systemName: "sparkles.rectangle.stack.fill")
                        .font(vocabSkin.typography.symbolHero)
                        .foregroundStyle(vocabSkin.palette.accent)

                    Text("BooksBrowser Pro")
                        .font(vocabSkin.typography.displayTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    Text(paywallSummaryText)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .lineSpacing(6)

                    VStack(alignment: .leading, spacing: 6) {
                        Text(priceLine)
                            .font(vocabSkin.typography.sectionTitle)
                            .foregroundStyle(vocabSkin.palette.primaryText)
                        Text("來源：\(sourceLine)")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        paywallFeatureRow("AI 翻譯與語境解釋")
                        paywallFeatureRow("知識庫同步與跨裝置狀態")
                        paywallFeatureRow("關聯圖與 Mochi 同步")
                    }
                    .padding(vocabSkin.spacing.cardPadding)
                    .background(vocabSkin.palette.cardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                            .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                    )

                    VStack(spacing: 10) {
                        Button {
                            Task {
                                if subscriptionManager.hasProAccess {
                                    await subscriptionManager.refresh(using: kgService, authManager: authManager)
                                } else {
                                    await subscriptionManager.purchasePro(using: kgService, authManager: authManager)
                                }
                            }
                        } label: {
                            HStack {
                                if subscriptionManager.isLoading {
                                    ProgressView()
                                        .controlSize(.small)
                                }
                                Text(subscriptionManager.hasProAccess ? "重新同步訂閱狀態" : "開始免費試用")
                                Spacer()
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.vocabAction(.primary))
                        .disabled(subscriptionManager.isLoading)

                        Button {
                            Task {
                                await subscriptionManager.restorePurchases(using: kgService, authManager: authManager)
                            }
                        } label: {
                            Text("恢復購買")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.vocabAction(.neutral))
                        .disabled(subscriptionManager.isLoading)
                    }

                    if let purchaseStatusMessage = subscriptionManager.purchaseStatusMessage {
                        Text(purchaseStatusMessage)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }

                    Text("價格與免費試用長度會以 App Store 與你的地區顯示為準。")
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }
                .padding(20)
            }
            .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("訂閱")
            .navigationBarTitleDisplayMode(.inline)
            .task {
                await subscriptionManager.loadProducts()
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }

    private var paywallSummaryText: String {
        if subscriptionManager.hasProAccess {
            return "目前帳號已具備 Pro 權限。若狀態顯示不一致，可重新同步或恢復購買。"
        }
        return "解鎖閱讀器 AI、知識庫同步、關聯圖與 Mochi 整合。免費試用與價格會直接來自 App Store。"
    }

    private var priceLine: String {
        if let product = subscriptionManager.proProduct {
            let days = subscriptionManager.entitlements.pro.trial_days ?? 7
            return "\(product.displayPrice) / month · \(days) 天免費試用"
        }
        if let remotePrice = subscriptionManager.entitlements.pro.price_display, !remotePrice.isEmpty {
            return remotePrice
        }
        return "載入 App Store 價格中…"
    }

    private var sourceLine: String {
        switch subscriptionManager.activePaywallSource {
        case .settings:
            return "設定"
        case .sync:
            return "同步"
        case .graph:
            return "關聯圖"
        case .reader:
            return "閱讀器 AI"
        case .knowledge:
            return "知識庫"
        case nil:
            return "訂閱"
        }
    }

    private func paywallFeatureRow(_ text: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "checkmark.circle.fill")
                .font(vocabSkin.typography.iconMedium)
                .foregroundStyle(vocabSkin.palette.success)
            Text(text)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.primaryText)
            Spacer()
        }
    }
}
