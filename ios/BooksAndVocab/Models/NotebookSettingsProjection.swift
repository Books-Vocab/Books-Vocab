import Foundation
import SwiftData

enum NotebookSettingsSyncState: String, Codable, Sendable {
    case synced
    case pending
    case failed
}

/// Local mirror of notebook review settings. It is separate from Notebook so
/// metadata and learning policy retain independent ownership/timestamps.
@Model
final class NotebookSettingsProjection {
    @Attribute(.unique)
    var notebookId: String = ""

    var reviewPolicyModeRaw: String?
    var reviewPolicyCustomInitialIntervalHours: Double?
    var reviewPolicyCustomRememberedMultiplier: Double?
    var reviewPolicyCustomForgotMultiplier: Double?
    var reviewPolicyCustomMinimumIntervalHours: Double?
    var reviewPolicyCustomMaximumIntervalHours: Double?
    var reviewPolicyUpdatedAt: Double?

    var cardLayoutRecognitionRaw: String?
    var cardLayoutProductionRaw: String?
    var cardLayoutUpdatedAt: Double?

    var syncStateRaw: String = NotebookSettingsSyncState.synced.rawValue
    var syncError: String?

    init(notebookId: String) {
        self.notebookId = notebookId
    }

    var syncState: NotebookSettingsSyncState {
        get { NotebookSettingsSyncState(rawValue: syncStateRaw) ?? .synced }
        set { syncStateRaw = newValue.rawValue }
    }

    var reviewPolicyOverride: ReviewPolicy? {
        guard let modeRaw = reviewPolicyModeRaw,
              let mode = ReviewSettingsMode(rawValue: modeRaw),
              let initial = reviewPolicyCustomInitialIntervalHours,
              let remembered = reviewPolicyCustomRememberedMultiplier,
              let forgot = reviewPolicyCustomForgotMultiplier,
              let minimum = reviewPolicyCustomMinimumIntervalHours,
              let maximum = reviewPolicyCustomMaximumIntervalHours
        else { return nil }
        return ReviewPolicy(
            mode: mode,
            customInitialIntervalHours: initial,
            customRememberedMultiplier: remembered,
            customForgotMultiplier: forgot,
            customMinimumIntervalHours: minimum,
            customMaximumIntervalHours: maximum
        )
    }

    var cardLayoutOverride: ReviewCardLayoutProfile? {
        guard let recognitionRaw = cardLayoutRecognitionRaw,
              let recognition = ReviewCardLayoutPreset(rawValue: recognitionRaw),
              let productionRaw = cardLayoutProductionRaw,
              let production = ReviewCardLayoutPreset(rawValue: productionRaw)
        else { return nil }
        return ReviewCardLayoutProfile(recognition: recognition, production: production)
    }

    struct Snapshot: Equatable, Sendable {
        let reviewPolicy: ReviewPolicy?
        let reviewPolicyUpdatedAt: Double?
        let cardLayout: ReviewCardLayoutProfile?
        let cardLayoutUpdatedAt: Double?
        let syncState: NotebookSettingsSyncState
        let syncError: String?
    }

    func snapshot() -> Snapshot {
        Snapshot(
            reviewPolicy: reviewPolicyOverride,
            reviewPolicyUpdatedAt: reviewPolicyUpdatedAt,
            cardLayout: cardLayoutOverride,
            cardLayoutUpdatedAt: cardLayoutUpdatedAt,
            syncState: syncState,
            syncError: syncError
        )
    }

    func restore(_ snapshot: Snapshot) {
        setReviewPolicy(snapshot.reviewPolicy)
        reviewPolicyUpdatedAt = snapshot.reviewPolicyUpdatedAt
        setCardLayout(snapshot.cardLayout)
        cardLayoutUpdatedAt = snapshot.cardLayoutUpdatedAt
        syncState = snapshot.syncState
        syncError = snapshot.syncError
    }

    func setReviewPolicy(_ policy: ReviewPolicy?) {
        reviewPolicyModeRaw = policy?.mode.rawValue
        reviewPolicyCustomInitialIntervalHours = policy?.customInitialIntervalHours
        reviewPolicyCustomRememberedMultiplier = policy?.customRememberedMultiplier
        reviewPolicyCustomForgotMultiplier = policy?.customForgotMultiplier
        reviewPolicyCustomMinimumIntervalHours = policy?.customMinimumIntervalHours
        reviewPolicyCustomMaximumIntervalHours = policy?.customMaximumIntervalHours
    }

    func setCardLayout(_ profile: ReviewCardLayoutProfile?) {
        cardLayoutRecognitionRaw = profile?.recognition.rawValue
        cardLayoutProductionRaw = profile?.production.rawValue
    }

    func applyRemote(_ settings: KGNotebookSettings) {
        applyRemoteReviewPolicy(settings.reviewPolicy)
        applyRemoteCardLayout(settings.cardLayout)
        syncState = .synced
        syncError = nil
    }

    func applyRemoteReviewPolicy(_ group: KGNotebookSettingsGroup<KGNotebookReviewPolicy>) {
        guard let remoteUpdatedAt = group.updatedAt else { return }
        guard reviewPolicyUpdatedAt == nil || remoteUpdatedAt >= reviewPolicyUpdatedAt! else { return }
        setReviewPolicy(group.value?.reviewPolicy)
        reviewPolicyUpdatedAt = remoteUpdatedAt
    }

    func applyRemoteCardLayout(_ group: KGNotebookSettingsGroup<KGNotebookCardLayout>) {
        guard let remoteUpdatedAt = group.updatedAt else { return }
        guard cardLayoutUpdatedAt == nil || remoteUpdatedAt >= cardLayoutUpdatedAt! else { return }
        setCardLayout(group.value?.profile)
        cardLayoutUpdatedAt = remoteUpdatedAt
    }

    func applyLocalReviewPolicy(_ policy: ReviewPolicy?, updatedAt: Double) {
        setReviewPolicy(policy)
        reviewPolicyUpdatedAt = updatedAt
        syncState = .pending
        syncError = nil
    }

    func applyLocalCardLayout(_ profile: ReviewCardLayoutProfile?, updatedAt: Double) {
        setCardLayout(profile)
        cardLayoutUpdatedAt = updatedAt
        syncState = .pending
        syncError = nil
    }
}
