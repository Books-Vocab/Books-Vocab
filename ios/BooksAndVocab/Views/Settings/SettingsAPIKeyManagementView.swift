import SwiftUI

struct SettingsAPIKeyManagementView: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.kgService) private var kgService
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.toastCoordinator) private var toastCoordinator

    @State private var keys: [KGExternalAPIKey] = []
    @State private var label = ""
    @State private var isShowingCreateForm = false
    @State private var isLoading = false
    @State private var isWorking = false
    @State private var errorMessage: String?
    @State private var revealedAPIKey: String?
    @State private var revokeTarget: KGExternalAPIKey?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppShellMetrics.sectionSpacing) {
                if subscriptionManager.hasProAccess {
                    instructionsSection
                    keyListSection
                } else {
                    VocabStateMessageCard(
                        title: SettingsAPIKeyCopy.proRequired,
                        systemImage: "lock.fill",
                        description: SettingsAPIKeyCopy.description
                    )
                    .accessibilityIdentifier("settings.apiKeys.proRequired")
                }
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppShellMetrics.pageTopPadding)
            .padding(.bottom, AppShellMetrics.pageBottomPadding)
        }
        .accessibilityIdentifier("settings.apiKeys.scrollView")
        .background(appSkin.palette.pageBackground.ignoresSafeArea())
        .navigationTitle(SettingsAPIKeyCopy.navigationTitle)
        .inlineNavigationBarTitle()
        .settingsDetailNavigationBackButton()
        .task {
            await loadKeys()
        }
        .onDisappear {
            // The plaintext must not remain in view state after leaving the page.
            revealedAPIKey = nil
        }
        .alert(
            SettingsAPIKeyCopy.revokeConfirmationTitle,
            isPresented: Binding(
                get: { revokeTarget != nil },
                set: { if !$0 { revokeTarget = nil } }
            )
        ) {
            Button(SettingsAPIKeyCopy.revokeTitle, role: .destructive) {
                guard let target = revokeTarget else { return }
                revokeTarget = nil
                Task { await revokeKey(target) }
            }
            Button(SettingsAPIKeyCopy.cancelTitle, role: .cancel) {
                revokeTarget = nil
            }
        } message: {
            Text(SettingsAPIKeyCopy.revokeConfirmationMessage)
        }
        .enableInjection()
    }

    private var instructionsSection: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: SettingsAPIKeyCopy.sectionTitle, icon: "key.horizontal")

            VocabStateMessageCard(
                title: SettingsAPIKeyCopy.newKeyTitle,
                systemImage: "shield.lefthalf.filled",
                description: SettingsAPIKeyCopy.description
            )

            if let revealedAPIKey {
                secretCard(revealedAPIKey)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.apiKeys.instructions")
    }

    private var keyListSection: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: SettingsAPIKeyCopy.sectionTitle, icon: "list.bullet.rectangle")

            if let errorMessage {
                VocabStateMessageCard(
                    title: errorMessage,
                    systemImage: "exclamationmark.triangle",
                    accessory: {
                        SettingsCompactActionButton(title: SettingsAPIKeyCopy.retryTitle) {
                            Task { await loadKeys() }
                        }
                    }
                )
                .accessibilityIdentifier("settings.apiKeys.error")
            } else if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, minHeight: 80)
                    .accessibilityLabel(L10n.string("正在載入 API 金鑰"))
            } else if keys.isEmpty {
                VocabStateMessageCard(
                    title: SettingsAPIKeyCopy.emptyTitle,
                    systemImage: "key",
                    description: SettingsAPIKeyCopy.emptyDescription
                )
                .accessibilityIdentifier("settings.apiKeys.empty")
            } else {
                keyList
            }

            if isShowingCreateForm {
                createForm
            } else {
                SettingsNavigationRow(
                    icon: "plus",
                    label: SettingsAPIKeyCopy.createButtonTitle,
                    action: { isShowingCreateForm = true },
                    accessibilityIdentifier: "settings.apiKeys.createButton"
                )
                .settingsCard()
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.apiKeys.listSection")
    }

    private var keyList: some View {
        VStack(spacing: 0) {
            ForEach(Array(keys.enumerated()), id: \.element.id) { index, key in
                keyRow(key)

                if index < keys.count - 1 {
                    SettingsDivider()
                }
            }
        }
        .settingsCard()
        .accessibilityIdentifier("settings.apiKeys.keyList")
    }

    private func keyRow(_ key: KGExternalAPIKey) -> some View {
        HStack(alignment: .center, spacing: appSkin.spacing.controlGap) {
            VStack(alignment: .leading, spacing: AppSpacing.tinyGap) {
                Text(key.label)
                    .font(appSkin.typography.body.weight(.medium))
                    .foregroundStyle(appSkin.palette.primaryText)
                    .lineLimit(1)

                Text(SettingsAPIKeyCopy.createdAt(key.createdAt))
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .lineLimit(1)
            }

            Spacer(minLength: appSkin.spacing.inlineGap)

            SettingsStatusBadge(
                text: key.isRevoked ? SettingsAPIKeyCopy.revokedTitle : SettingsAPIKeyCopy.activeTitle,
                tone: key.isRevoked ? appSkin.palette.tertiaryText : appSkin.palette.success
            )

            if !key.isRevoked {
                Button {
                    revokeTarget = key
                } label: {
                    Image(systemName: "xmark.circle")
                        .font(appSkin.typography.iconMedium)
                        .foregroundStyle(appSkin.palette.destructive)
                        .frame(width: 32, height: 32)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(SettingsAPIKeyCopy.revokeTitle)
                .accessibilityIdentifier("settings.apiKeys.revoke.\(key.id)")
                .disabled(isWorking)
            }
        }
        .padding(.horizontal, appSkin.spacing.cardPadding)
        .padding(.vertical, appSkin.spacing.actionButtonVerticalPadding)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.apiKeys.key.\(key.id)")
    }

    private var createForm: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.controlGap) {
            Text(SettingsAPIKeyCopy.labelFieldTitle)
                .font(appSkin.typography.body.weight(.medium))
                .foregroundStyle(appSkin.palette.primaryText)

            TextField(SettingsAPIKeyCopy.labelPlaceholder, text: $label)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.sentences)
                .accessibilityIdentifier("settings.apiKeys.labelField")

            HStack(spacing: appSkin.spacing.controlGap) {
                SettingsCompactActionButton(title: SettingsAPIKeyCopy.cancelTitle) {
                    label = ""
                    isShowingCreateForm = false
                }

                SettingsCompactActionButton(
                    title: SettingsAPIKeyCopy.createButtonTitle,
                    isEnabled: !label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !isWorking
                ) {
                    Task { await createKey() }
                }
                .accessibilityIdentifier("settings.apiKeys.confirmCreateButton")
            }
        }
        .padding(appSkin.spacing.cardPadding)
        .settingsCard()
        .accessibilityIdentifier("settings.apiKeys.createForm")
    }

    private func secretCard(_ secret: String) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.controlGap) {
            Text(secret)
                .font(appSkin.typography.monoLabel)
                .foregroundStyle(appSkin.palette.primaryText)
                .textSelection(.enabled)
                .lineLimit(4)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("settings.apiKeys.plaintext")

            HStack {
                SettingsCompactActionButton(title: SettingsAPIKeyCopy.copyTitle) {
                    PlatformClipboard.copy(secret)
                    toastCoordinator.success(SettingsAPIKeyCopy.copiedToast)
                }
                .accessibilityIdentifier("settings.apiKeys.copyButton")

                Spacer(minLength: appSkin.spacing.inlineGap)
            }

            Text(SettingsAPIKeyCopy.oneTimeWarning)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)
        }
        .padding(appSkin.spacing.cardPadding)
        .background(appSkin.palette.cardBackground)
        .clipShape(AppRoundedRect(roundness: appSkin.roundness.card))
        .overlay {
            AppRoundedRect(roundness: appSkin.roundness.card)
                .stroke(appSkin.palette.cardBorder, lineWidth: 1)
        }
        .accessibilityIdentifier("settings.apiKeys.newSecret")
    }

    @MainActor
    private func loadKeys() async {
        guard subscriptionManager.hasProAccess, !isLoading else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            keys = try await kgService.fetchExternalAPIKeys().map(\.redacted)
        } catch is CancellationError {
            return
        } catch {
            errorMessage = SettingsAPIKeyCopy.errorMessage(for: error)
        }
    }

    @MainActor
    private func createKey() async {
        guard !isWorking else { return }
        isWorking = true
        errorMessage = nil
        defer { isWorking = false }

        do {
            let created = try await kgService.createExternalAPIKey(label: label)
            guard let secret = created.apiKey, !secret.isEmpty else {
                errorMessage = SettingsAPIKeyCopy.genericError
                return
            }
            keys.insert(created.redacted, at: 0)
            revealedAPIKey = secret
            label = ""
            isShowingCreateForm = false
        } catch is CancellationError {
            return
        } catch {
            errorMessage = SettingsAPIKeyCopy.errorMessage(for: error)
        }
    }

    @MainActor
    private func revokeKey(_ key: KGExternalAPIKey) async {
        guard !isWorking else { return }
        isWorking = true
        errorMessage = nil
        defer { isWorking = false }

        do {
            let revoked = try await kgService.revokeExternalAPIKey(id: key.id)
            keys = keys.map { $0.id == revoked.id ? revoked.redacted : $0 }
        } catch is CancellationError {
            return
        } catch {
            errorMessage = SettingsAPIKeyCopy.errorMessage(for: error)
        }
    }
}
