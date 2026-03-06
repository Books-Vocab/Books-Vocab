//
//  SettingsView.swift
//  BooksBrowser
//

import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var colorScheme

    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
#if DEBUG
    @AppStorage("developer_account_id") private var developerAccountId: String = ""
    @State private var manualLoginUserId: String = ""
#endif
    @State private var mochiApiKey: String = ""
    @State private var fetchedKey: String = ""
    @State private var saveTask: Task<Void, Never>? = nil
    @State private var showMochiInfo: Bool = false
    @State private var connectionPulse: Bool = false
    @State private var iconBreathing: Bool = false
    @State private var showDeleteAccountConfirm: Bool = false
    @State private var isDeletingAccount: Bool = false
    @State private var deleteAccountError: String?

    private var userInitials: String? {
        guard let name = authManager.displayName, !name.isEmpty else { return nil }
        let parts = name.split(separator: " ")
        if parts.count >= 2 {
            return String(parts[0].prefix(1)) + String(parts[1].prefix(1))
        }
        return String(name.prefix(2)).uppercased()
    }

#if DEBUG
    private var isCurrentAccountDeveloper: Bool {
        guard let userId = authManager.userId else { return false }
        return !developerAccountId.isEmpty && developerAccountId == userId
    }
#endif

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    authSection
                    if authManager.isLoggedIn {
                        kgSection
                        mochiSection
                    }
                    aboutSection
                    if authManager.isLoggedIn {
                        dangerSection
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 48)
            }
            .background(Color(uiColor: .systemGroupedBackground).ignoresSafeArea())
            .navigationTitle("設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                        .fontWeight(.semibold)
                }
            }
            .task(id: authManager.isLoggedIn) {
                await kgService.healthCheck()
                connectionPulse.toggle()

                if authManager.isLoggedIn {
                    if let config = try? await kgService.fetchUserConfig() {
                        let fetched = config.mochi_api_key ?? ""
                        fetchedKey = fetched
                        mochiApiKey = fetched
                    }
                } else {
                    fetchedKey = ""
                    mochiApiKey = ""
                }
            }
            .onChange(of: mochiApiKey) {
                guard mochiApiKey != fetchedKey else { return }
                saveTask?.cancel()
                saveTask = Task {
                    try? await Task.sleep(for: .milliseconds(600))
                    guard !Task.isCancelled else { return }
                    if authManager.isLoggedIn {
                        _ = try? await kgService.updateUserConfig(mochiKey: mochiApiKey.isEmpty ? nil : mochiApiKey)
                        fetchedKey = mochiApiKey
                    }
                }
            }
#if DEBUG
            .onAppear {
                manualLoginUserId = developerAccountId
            }
#endif
            .sheet(isPresented: $showMochiInfo) {
                MochiInfoSheetView()
            }
            .alert("刪除帳號與雲端資料？", isPresented: $showDeleteAccountConfirm) {
                Button("取消", role: .cancel) {}
                Button("確認刪除", role: .destructive) {
                    Task { await deleteAccount() }
                }
            } message: {
                Text("此操作會永久刪除帳號、雲端生詞資料與同步設定，且無法復原。")
            }
            .alert("刪除失敗", isPresented: Binding(
                get: { deleteAccountError != nil },
                set: { if !$0 { deleteAccountError = nil } }
            )) {
                Button("好") { deleteAccountError = nil }
            } message: {
                Text(deleteAccountError ?? "請稍後再試")
            }
        }
    }

    // MARK: - 帳號區塊

    @ViewBuilder
    private var authSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "帳號", icon: "person.crop.circle")

            GlassEffectContainer {
                VStack(spacing: 0) {
                    if authManager.isLoggedIn {
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
            }
            .animation(.spring(response: 0.45, dampingFraction: 0.85), value: authManager.isLoggedIn)
            .glassEffect(in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
    }

    // 未登入
    @ViewBuilder
    private var loginView: some View {
        VStack(spacing: 0) {
            // Hero
            VStack(spacing: 10) {
                Image(systemName: "sparkles")
                    .font(.system(size: 36, weight: .light))
                    .foregroundStyle(.tertiary)
                    .opacity(iconBreathing ? 0.45 : 0.75)
                    .animation(.easeInOut(duration: 2.8).repeatForever(autoreverses: true), value: iconBreathing)
                    .onAppear { iconBreathing = true }

                VStack(spacing: 4) {
                    Text("解鎖完整功能")
                        .font(.headline)
                    Text("AI 翻譯・知識圖譜・雲端同步")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.vertical, 24)
            .frame(maxWidth: .infinity)

            Divider().opacity(0.4)

            // 登入按鈕
            VStack(spacing: 10) {
                Button {
                    authManager.loginWithGoogle(modelContainer: modelContext.container)
                } label: {
                    HStack(spacing: 12) {
                        ZStack {
                            Circle()
                                .fill(.white)
                                .frame(width: 22, height: 22)
                                .shadow(color: .black.opacity(0.08), radius: 2, y: 1)
                            Text("G")
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(Color(red: 0.87, green: 0.19, blue: 0.19))
                        }
                        Text("以 Google 繼續")
                            .fontWeight(.medium)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
                .buttonStyle(.morandi(colorScheme: colorScheme))

                Button {
                    authManager.loginWithApple(modelContainer: modelContext.container)
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: "apple.logo")
                            .font(.system(size: 15))
                            .frame(width: 22)
                        Text("以 Apple 繼續")
                            .fontWeight(.medium)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
                .buttonStyle(.morandi(colorScheme: colorScheme))

#if DEBUG
                Divider().opacity(0.4)

                HStack(spacing: 8) {
                    TextField("帳號 ID（手動）", text: $manualLoginUserId)
                        .font(.system(size: 13, design: .monospaced))
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)

                    Button("登入") {
                        let id = manualLoginUserId.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !id.isEmpty else { return }
                        authManager.login(customToken: id)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }

                HStack(spacing: 8) {
                    Button("設為開發者帳號") {
                        developerAccountId = manualLoginUserId.trimmingCharacters(in: .whitespacesAndNewlines)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)

                    Button("清除開發者帳號") {
                        developerAccountId = ""
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
#endif

                if let error = authManager.authError {
                    Text(error)
                        .font(.caption)
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

    // 已登入
    @ViewBuilder
    private var loggedInView: some View {
        VStack(spacing: 0) {
            HStack(spacing: 14) {
                // 頭像
                ZStack {
                    Circle()
                        .fill(AppColors.accent(colorScheme).opacity(0.12))
                        .frame(width: 46, height: 46)

                    if let avatarURL = authManager.avatarURL {
                        AsyncImage(url: avatarURL) { image in
                            image.resizable().scaledToFill()
                        } placeholder: {
                            Image(systemName: "person.fill")
                                .font(.system(size: 19))
                                .foregroundStyle(AppColors.accent(colorScheme))
                        }
                        .frame(width: 46, height: 46)
                        .clipShape(Circle())
                    } else if let initials = userInitials {
                        Text(initials)
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(AppColors.accent(colorScheme))
                    } else {
                        Image(systemName: "person.fill")
                            .font(.system(size: 19))
                            .foregroundStyle(AppColors.accent(colorScheme))
                    }
                }

                VStack(alignment: .leading, spacing: 3) {
                    Text(authManager.displayName ?? authManager.userEmail ?? "已登入")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .lineLimit(1)
                    if let email = authManager.userEmail, authManager.displayName != nil {
                        Text(email)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }

                Spacer()

                VStack(alignment: .trailing, spacing: 6) {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.title3)
                        .foregroundStyle(AppColors.saved(colorScheme))
                        .symbolEffect(.bounce, value: authManager.isLoggedIn)
#if DEBUG
                    if isCurrentAccountDeveloper {
                        Text("DEVELOPER")
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.orange)
                    }
#endif
                }
            }
            .padding(16)

            Divider().opacity(0.4)

            Button(role: .destructive) {
                authManager.logout(modelContainer: modelContext.container)
            } label: {
                Text("登出帳號")
                    .font(.subheadline)
                    .foregroundStyle(AppColors.destructive(colorScheme))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 13)
            }
            .buttonStyle(.plain)
        }
    }

    @MainActor
    private func deleteAccount() async {
        guard authManager.isLoggedIn, !isDeletingAccount else { return }
        isDeletingAccount = true
        defer { isDeletingAccount = false }

        do {
            try await kgService.deleteAccount()
            authManager.logout(modelContainer: modelContext.container)
        } catch {
            deleteAccountError = "無法刪除帳號：\(error.localizedDescription)"
        }
    }

    // MARK: - KG 區塊

    @ViewBuilder
    private var kgSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Knowledge Graph", icon: "brain.head.profile")

            GlassEffectContainer {
                VStack(spacing: 0) {
                    // 伺服器位址
                    SettingsGlassRow(icon: "server.rack", label: "伺服器") {
                        Text(KGService.getServerURL())
                            .font(.system(size: 12, design: .monospaced))
                            .multilineTextAlignment(.trailing)
                            .foregroundStyle(.secondary)
                    }

                    Divider().opacity(0.4).padding(.leading, 50)

                    // 連線狀態
                    SettingsGlassRow(icon: "antenna.radiowaves.left.and.right", label: "連線狀態") {
                        HStack(spacing: 8) {
                            Circle()
                                .fill(kgService.isConnected ? Color.green : Color.orange)
                                .frame(width: 8, height: 8)
                                .shadow(
                                    color: (kgService.isConnected ? Color.green : Color.orange).opacity(0.6),
                                    radius: connectionPulse ? 5 : 2
                                )
                                .animation(
                                    kgService.isConnected
                                        ? .easeInOut(duration: 1.2).repeatForever(autoreverses: true)
                                        : .default,
                                    value: connectionPulse
                                )
                            Text(kgService.isConnected ? "已連線" : "離線")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }

                    if kgService.isConnected {
                        Divider().opacity(0.4).padding(.leading, 50)

                        SettingsGlassRow(icon: "text.book.closed", label: "字庫卡片") {
                            Text("\(kgService.serverCardCount) 張")
                                .font(.system(size: 13, design: .monospaced))
                                .foregroundStyle(.secondary)
                        }
                        .transition(.move(edge: .top).combined(with: .opacity))

                        if let lastSync = kgService.lastSyncDate {
                            Divider().opacity(0.4).padding(.leading, 50)

                            SettingsGlassRow(icon: "arrow.clockwise", label: "最後同步") {
                                Text(lastSync, format: .relative(presentation: .named))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            .transition(.move(edge: .top).combined(with: .opacity))
                        }
                    }
                }
            }
            .animation(.spring(response: 0.35, dampingFraction: 0.8), value: kgService.isConnected)
            .animation(.spring(response: 0.35, dampingFraction: 0.8), value: kgService.serverCardCount)
            .glassEffect(in: RoundedRectangle(cornerRadius: 18, style: .continuous))

            SectionFooter("KG 伺服器負責生詞 AI 增強與 Mochi 同步。")
        }
    }

    // MARK: - Mochi 區塊

    @ViewBuilder
    private var mochiSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "第三方整合", icon: "puzzlepiece.extension")

            GlassEffectContainer {
                VStack(spacing: 0) {
                    SettingsGlassRow(icon: "m.square.fill", label: "Mochi API Key") {
                        HStack(spacing: 6) {
                            SecureField("可選", text: $mochiApiKey)
                                .font(.system(size: 12, design: .monospaced))
                                .multilineTextAlignment(.trailing)
                                .autocorrectionDisabled()
                                .textInputAutocapitalization(.never)
                                .disabled(!authManager.isLoggedIn)

                            Button {
                                showMochiInfo = true
                            } label: {
                                Image(systemName: "info.circle")
                                    .font(.callout)
                                    .foregroundStyle(AppColors.accent(colorScheme).opacity(0.7))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .glassEffect(in: RoundedRectangle(cornerRadius: 18, style: .continuous))

            SectionFooter("可選。填入後自動將生詞同步至 Mochi 單字卡。")
        }
    }

    // MARK: - 關於區塊

    @ViewBuilder
    private var aboutSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "關於", icon: "info.circle")

            GlassEffectContainer {
                VStack(spacing: 0) {
                    SettingsGlassRow(icon: "tag", label: "版本") {
                        Text("1.1.0")
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }

                    Divider().opacity(0.4).padding(.leading, 50)

                    SettingsGlassRow(icon: "person.circle", label: "開發者") {
                        Text("陳亮宇")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }

#if DEBUG
                    Divider().opacity(0.4).padding(.leading, 50)

                    SettingsGlassRow(icon: "wrench.and.screwdriver", label: "開發者帳號 ID") {
                        Text(developerAccountId.isEmpty ? "未設定" : developerAccountId)
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
#endif
                }
            }
            .glassEffect(in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
    }

    // MARK: - 危險操作區塊

    @ViewBuilder
    private var dangerSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "危險操作", icon: "exclamationmark.triangle")

            GlassEffectContainer {
                VStack(spacing: 0) {
                    Button(role: .destructive) {
                        showDeleteAccountConfirm = true
                    } label: {
                        HStack {
                            Text(isDeletingAccount ? "刪除中..." : "刪除帳號與雲端資料")
                                .font(.subheadline)
                                .foregroundStyle(AppColors.destructive(colorScheme))
                            Spacer()
                            Image(systemName: "trash")
                                .font(.caption)
                                .foregroundStyle(AppColors.destructive(colorScheme))
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 13)
                        .padding(.horizontal, 16)
                    }
                    .buttonStyle(.plain)
                    .disabled(isDeletingAccount)
                }
            }
            .glassEffect(in: RoundedRectangle(cornerRadius: 18, style: .continuous))

            SectionFooter("此操作不可逆，會刪除帳號與所有雲端資料。")
        }
    }
}

// MARK: - 子組件

private struct SectionHeader: View {
    let title: String
    let icon: String

    var body: some View {
        Label(title, systemImage: icon)
            .font(.footnote)
            .fontWeight(.medium)
            .foregroundStyle(.secondary)
            .padding(.leading, 4)
    }
}

private struct SectionFooter: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(.caption2)
            .foregroundStyle(.tertiary)
            .lineSpacing(3)
            .padding(.horizontal, 4)
    }
}

private struct SettingsGlassRow<Content: View>: View {
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
                .font(.system(size: 14))
                .foregroundStyle(.secondary)
                .frame(width: 22, alignment: .center)

            Text(label)
                .font(.subheadline)
                .foregroundStyle(.primary)

            Spacer()

            content
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
        .frame(minHeight: 50)
    }
}

// MARK: - Mochi Info Sheet

struct MochiInfoSheetView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(.system(size: 48))
                        .foregroundStyle(.blue)
                        .padding(.bottom, 8)

                    Text("關於 Mochi 同步")
                        .font(.title)
                        .fontWeight(.bold)

                    Text("如果你有在使用 Mochi (mochi.cards) 來複習單字，BooksBrowser 可以自動將你查過並儲存的單字建立成 Mochi 卡片！")
                        .font(.body)
                        .lineSpacing(4)

                    Divider()

                    Text("如何取得 API Key？")
                        .font(.headline)

                    VStack(alignment: .leading, spacing: 12) {
                        Label("1. 登入網頁版的 app.mochi.cards", systemImage: "1.circle.fill")
                        Label("2. 點擊右上角設定 (Settings)", systemImage: "2.circle.fill")
                        Label("3. 選擇 API 分頁", systemImage: "3.circle.fill")
                        Label("4. 點擊 Generate API key 並複製貼上到前面設定中", systemImage: "4.circle.fill")
                    }
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                    Text("這是一個可選功能，就算不填寫 API Key，BooksBrowser 也能完美獨立運作！")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.top, 16)
                }
                .padding(24)
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}

#Preview {
    SettingsView()
}
