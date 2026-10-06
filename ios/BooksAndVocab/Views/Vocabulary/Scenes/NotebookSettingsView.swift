import Foundation
import SwiftUI
import SwiftData

/// Settings for one notebook. The draft is resolved from the notebook
/// projection first and falls back to the existing global stores per group.
/// Saving is optimistic locally; the API is a best-effort sync boundary so an
/// offline or legacy server cannot discard a user's notebook-scoped choice.
struct NotebookSettingsView: View {
    @ObserveInjection private var inject
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore
    @Environment(\.reviewCardLayoutStore) private var reviewCardLayoutStore

    @Query private var notebooks: [Notebook]
    @Query private var projections: [NotebookSettingsProjection]

    let notebookId: String

    @State private var draftPolicy = ReviewPolicy.default
    @State private var draftLayout = ReviewCardLayoutProfile.default
    @State private var hasLoadedDraft = false
    @State private var saveGeneration = 0
    @State private var errorMessage: String?
    @State private var pendingRetry: PendingRetry?
    @State private var isLayoutEditorPresented = false

    private enum PendingRetry: Equatable {
        case reviewPolicy(ReviewPolicy?)
        case cardLayout(ReviewCardLayoutProfile?)
    }

    init(notebookId: String) {
        self.notebookId = notebookId
        let id = notebookId
        _notebooks = Query(filter: #Predicate<Notebook> { $0.remoteId == id })
        _projections = Query(filter: #Predicate<NotebookSettingsProjection> { $0.notebookId == id })
    }

    private var notebookName: String {
        notebooks.first?.name ?? L10n.string("notebookSettings.notebookFallback")
    }

    private var projection: NotebookSettingsProjection? {
        projections.first
    }

    private var resolver: NotebookSettingsResolver {
        NotebookSettingsResolver(
            globalReviewStore: reviewSettingsStore,
            globalCardLayoutStore: reviewCardLayoutStore,
            projections: projections
        )
    }

    private var resolution: NotebookSettingsResolution {
        resolver.resolve(notebookId: notebookId)
    }

    var body: some View {
        Form {
            NotebookSettingsHeader(notebookName: notebookName)
            NotebookReviewPolicySection(
                draftPolicy: $draftPolicy,
                hasLoadedDraft: hasLoadedDraft,
                globalSettings: reviewSettingsStore.settings,
                resolution: resolution,
                onSave: saveReviewPolicy
            )
            NotebookCardLayoutSection(
                resolution: resolution,
                onOpen: { isLayoutEditorPresented = true },
                onReset: {
                    draftLayout = reviewCardLayoutStore.profile
                    saveCardLayout(nil)
                }
            )

            if let errorMessage {
                Section {
                    Label(errorMessage, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.red)
                    if let pendingRetry {
                        Button(L10n.string("notebookSettings.retry")) {
                            self.pendingRetry = nil
                            switch pendingRetry {
                            case let .reviewPolicy(policy): saveReviewPolicy(policy)
                            case let .cardLayout(profile): saveCardLayout(profile)
                            }
                        }
                    }
                }
                .accessibilityIdentifier("notebook.settings.error")
            }
        }
        .navigationTitle(L10n.string("notebookSettings.title"))
        .inlineNavigationBarTitle()
        .task { loadDraftIfNeeded() }
        .sheet(isPresented: $isLayoutEditorPresented) {
            ReviewCardLayoutEditorSheet(
                profile: scopedLayoutBinding,
                onReset: {
                    draftLayout = reviewCardLayoutStore.profile
                    saveCardLayout(nil)
                },
                onDone: { isLayoutEditorPresented = false }
            )
            .appAppearanceScheme()
        }
        .enableInjection()
    }

    private var scopedLayoutBinding: Binding<ReviewCardLayoutProfile> {
        Binding(
            get: { draftLayout },
            set: { newValue in
                draftLayout = newValue
                guard hasLoadedDraft else { return }
                saveCardLayout(newValue)
            }
        )
    }

    private func loadDraftIfNeeded() {
        guard !hasLoadedDraft else { return }
        let current = resolution
        draftPolicy = current.reviewPolicy
        draftLayout = current.cardLayout
        hasLoadedDraft = true
    }

    private func ensureProjection() -> NotebookSettingsProjection {
        if let projection { return projection }
        let created = NotebookSettingsProjection(notebookId: notebookId)
        modelContext.insert(created)
        return created
    }

    private func nextTimestamp(_ previous: Double?) -> Double {
        let now = Date().timeIntervalSince1970
        guard let previous else { return now }
        return now > previous ? now : previous.nextUp
    }

    private func saveReviewPolicy(_ policy: ReviewPolicy?) {
        let projection = ensureProjection()
        let timestamp = nextTimestamp(projection.reviewPolicyUpdatedAt)
        projection.applyLocalReviewPolicy(policy, updatedAt: timestamp)
        guard modelContext.safeSave() else { return }

        saveGeneration += 1
        let generation = saveGeneration
        Task { @MainActor in
            do {
                let remote = try await kgService.updateNotebookSettings(
                    id: notebookId,
                    reviewPolicy: KGNotebookSettingsPatchGroup(
                        value: policy.map(KGNotebookReviewPolicy.init),
                        updatedAt: timestamp
                    ),
                    cardLayout: nil
                )
                guard generation == saveGeneration else { return }
                guard let settings = remote.settings else {
                    throw NotebookSettingsViewError.serverDidNotReturnSettings
                }
                projection.applyRemote(settings)
                draftPolicy = settings.reviewPolicy.value?.reviewPolicy
                    ?? ReviewPolicy(reviewSettingsStore.settings)
                errorMessage = nil
                pendingRetry = nil
                modelContext.safeSave()
            } catch {
                guard generation == saveGeneration else { return }
                // Keep the optimistic projection. This is the durable local
                // state used by review immediately, and the retry records the
                // exact intent without reverting the user's visible choice.
                projection.syncState = .failed
                projection.syncError = error.localizedDescription
                errorMessage = L10n.format("notebookSettings.syncFailedDetail", error.localizedDescription)
                pendingRetry = .reviewPolicy(policy)
                modelContext.safeSave()
                toastCoordinator.error(L10n.string("notebookSettings.syncFailed"))
            }
        }
    }

    private func saveCardLayout(_ profile: ReviewCardLayoutProfile?) {
        let projection = ensureProjection()
        let timestamp = nextTimestamp(projection.cardLayoutUpdatedAt)
        projection.applyLocalCardLayout(profile, updatedAt: timestamp)
        guard modelContext.safeSave() else { return }

        saveGeneration += 1
        let generation = saveGeneration
        Task { @MainActor in
            do {
                let remote = try await kgService.updateNotebookSettings(
                    id: notebookId,
                    reviewPolicy: nil,
                    cardLayout: KGNotebookSettingsPatchGroup(
                        value: profile.map(KGNotebookCardLayout.init),
                        updatedAt: timestamp
                    )
                )
                guard generation == saveGeneration else { return }
                guard let settings = remote.settings else {
                    throw NotebookSettingsViewError.serverDidNotReturnSettings
                }
                projection.applyRemote(settings)
                draftLayout = settings.cardLayout.value?.profile ?? reviewCardLayoutStore.profile
                errorMessage = nil
                pendingRetry = nil
                modelContext.safeSave()
            } catch {
                guard generation == saveGeneration else { return }
                projection.syncState = .failed
                projection.syncError = error.localizedDescription
                errorMessage = L10n.format("notebookSettings.syncFailedDetail", error.localizedDescription)
                pendingRetry = .cardLayout(profile)
                modelContext.safeSave()
                toastCoordinator.error(L10n.string("notebookSettings.syncFailed"))
            }
        }
    }
}

private struct NotebookSettingsHeader: View {
    let notebookName: String

    var body: some View {
        Section {
            VStack(alignment: .leading, spacing: AppSpacing.s1) {
                Text(L10n.format("notebookSettings.header", notebookName))
                    .font(.headline)
                Text(L10n.string("notebookSettings.fallbackDescription"))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .padding(.vertical, AppSpacing.s1)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("notebook.settings.header")
        }
    }
}

private struct NotebookReviewPolicySection: View {
    @Binding var draftPolicy: ReviewPolicy
    let hasLoadedDraft: Bool
    let globalSettings: ReviewSettings
    let resolution: NotebookSettingsResolution
    let onSave: (ReviewPolicy?) -> Void

    var body: some View {
        Section {
            Picker(L10n.string("notebookSettings.reviewMode"), selection: policyBinding(\.mode)) {
                ForEach(ReviewSettingsMode.allCases, id: \.rawValue) { mode in
                    Text(mode.displayName).tag(mode)
                }
            }
            .accessibilityIdentifier("notebook.settings.reviewMode")

            if draftPolicy.mode == .custom {
                policyStepper(
                    L10n.string("notebookSettings.initialIntervalHours"),
                    value: policyBinding(\.customInitialIntervalHours),
                    range: 1...1440,
                    step: 1,
                    identifier: "customInitialIntervalHours"
                )
                policyStepper(
                    L10n.string("notebookSettings.rememberedMultiplier"),
                    value: policyBinding(\.customRememberedMultiplier),
                    range: 0.1...10,
                    step: 0.1,
                    identifier: "customRememberedMultiplier"
                )
                policyStepper(
                    L10n.string("notebookSettings.forgotMultiplier"),
                    value: policyBinding(\.customForgotMultiplier),
                    range: 0.1...10,
                    step: 0.05,
                    identifier: "customForgotMultiplier"
                )
                policyStepper(
                    L10n.string("notebookSettings.minimumIntervalHours"),
                    value: policyBinding(\.customMinimumIntervalHours),
                    range: 1...1440,
                    step: 1,
                    identifier: "customMinimumIntervalHours"
                )
                policyStepper(
                    L10n.string("notebookSettings.maximumIntervalHours"),
                    value: policyBinding(\.customMaximumIntervalHours),
                    range: 1...8760,
                    step: 1,
                    identifier: "customMaximumIntervalHours"
                )
            }

            Button(L10n.string("notebookSettings.resetGlobal"), role: .destructive) {
                draftPolicy = ReviewPolicy(globalSettings)
                onSave(nil)
            }
            .disabled(resolution.reviewPolicySource == .user)
            .accessibilityIdentifier("notebook.settings.reviewReset")
        } header: {
            SettingsSectionHeader(title: L10n.string("notebookSettings.reviewPace"), icon: "clock.arrow.circlepath")
        } footer: {
            VStack(alignment: .leading, spacing: AppSpacing.s1) {
                Text(L10n.string("notebookSettings.reviewScopeNote"))
                Text(L10n.format(
                    "notebookSettings.sourceStatus",
                    resolution.reviewPolicySource == .notebook
                        ? L10n.string("notebookSettings.notebookOverride")
                        : L10n.string("notebookSettings.globalFallback")
                ))
            }
        }
        .accessibilityIdentifier("notebook.settings.reviewSection")
    }

    private func policyStepper(
        _ title: String,
        value: Binding<Double>,
        range: ClosedRange<Double>,
        step: Double,
        identifier: String
    ) -> some View {
        Stepper(value: value, in: range, step: step) {
            HStack {
                Text(title)
                Spacer()
                Text(String(format: "%.2f", value.wrappedValue))
                    .foregroundStyle(.secondary)
            }
        }
        .accessibilityIdentifier("notebook.settings.\(identifier)")
    }

    private func policyBinding<Value>(_ keyPath: WritableKeyPath<ReviewPolicy, Value>) -> Binding<Value> {
        Binding(
            get: { draftPolicy[keyPath: keyPath] },
            set: { newValue in
                var updated = draftPolicy
                updated[keyPath: keyPath] = newValue
                updated.customMinimumIntervalHours = min(
                    updated.customMinimumIntervalHours,
                    updated.customMaximumIntervalHours
                )
                updated.customMaximumIntervalHours = max(
                    updated.customMaximumIntervalHours,
                    updated.customMinimumIntervalHours
                )
                draftPolicy = updated
                if hasLoadedDraft { onSave(updated) }
            }
        )
    }
}

private struct NotebookCardLayoutSection: View {
    let resolution: NotebookSettingsResolution
    let onOpen: () -> Void
    let onReset: () -> Void

    var body: some View {
        Section {
            Button(action: onOpen) {
                HStack {
                    Label(L10n.string("notebookSettings.editCardLayout"), systemImage: "rectangle.split.2x1")
                    Spacer()
                    Text(resolution.cardLayoutSource == .notebook
                        ? L10n.string("notebookSettings.notebook")
                        : L10n.string("notebookSettings.global"))
                        .foregroundStyle(.secondary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("notebook.settings.cardLayoutEditor")

            Button(L10n.string("notebookSettings.resetGlobal"), role: .destructive, action: onReset)
                .disabled(resolution.cardLayoutSource == .user)
                .accessibilityIdentifier("notebook.settings.layoutReset")
        } header: {
            SettingsSectionHeader(title: L10n.string("notebookSettings.cardLayout"), icon: "rectangle.split.2x1")
        } footer: {
            Text(L10n.string("notebookSettings.cardLayoutFooter"))
        }
        .accessibilityIdentifier("notebook.settings.layoutSection")
    }
}

private enum NotebookSettingsViewError: LocalizedError {
    case serverDidNotReturnSettings

    var errorDescription: String? {
        switch self {
        case .serverDidNotReturnSettings:
            return L10n.string("notebookSettings.serverUnsupported")
        }
    }
}

#Preview {
    NavigationStack {
        NotebookSettingsView(notebookId: "default")
    }
    .modelContainer(for: [Notebook.self, NotebookSettingsProjection.self], inMemory: true)
}
