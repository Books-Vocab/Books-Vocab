import Foundation
import Observation
import SwiftUI

/// Optional content blocks that can be arranged around the review card's core
/// prompt and answer. The core prompt/answer are mode semantics and deliberately
/// do not participate in this persisted layout profile.
enum ReviewCardField: String, CaseIterable, Codable, Hashable {
    case partOfSpeech
    case difficultyTier
    case example
    case explanation
    case collocations
    case graphLinks
}

struct ReviewCardModeLayout: Equatable {
    var front: [ReviewCardField]
    var back: [ReviewCardField]

    init(front: [ReviewCardField], back: [ReviewCardField]) {
        self.front = front
        self.back = back
    }

    fileprivate var sanitized: Self {
        Self(
            front: Self.removingDuplicates(from: front),
            back: Self.removingDuplicates(from: back)
        )
    }

    private static func removingDuplicates(from fields: [ReviewCardField]) -> [ReviewCardField] {
        var seen = Set<ReviewCardField>()
        return fields.filter { seen.insert($0).inserted }
    }
}

struct ReviewCardLayoutProfile: Equatable, Codable {
    var recognition: ReviewCardModeLayout
    var production: ReviewCardModeLayout

    init(recognition: ReviewCardModeLayout, production: ReviewCardModeLayout) {
        self.recognition = recognition
        self.production = production
    }

    static let `default` = ReviewCardLayoutProfile(
        recognition: ReviewCardModeLayout(
            front: [.partOfSpeech],
            back: [.difficultyTier, .graphLinks, .example, .explanation, .collocations]
        ),
        production: ReviewCardModeLayout(
            front: [.partOfSpeech, .example],
            back: [.difficultyTier, .graphLinks, .example, .explanation, .collocations]
        )
    )

    func layout(for mode: VocabularyCardMode) -> ReviewCardModeLayout {
        switch mode {
        case .recognition: recognition
        case .production: production
        }
    }

    mutating func setLayout(_ layout: ReviewCardModeLayout, for mode: VocabularyCardMode) {
        switch mode {
        case .recognition: recognition = layout.sanitized
        case .production: production = layout.sanitized
        }
    }

    fileprivate var sanitized: Self {
        Self(recognition: recognition.sanitized, production: production.sanitized)
    }

    private enum CodingKeys: String, CodingKey {
        case recognition
        case production
    }

    private enum ModeCodingKeys: String, CodingKey {
        case front
        case back
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        recognition = Self.decodeLayout(
            from: container,
            key: .recognition,
            fallback: Self.default.recognition
        )
        production = Self.decodeLayout(
            from: container,
            key: .production,
            fallback: Self.default.production
        )
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try Self.encode(recognition.sanitized, to: &container, key: .recognition)
        try Self.encode(production.sanitized, to: &container, key: .production)
    }

    private static func decodeLayout(
        from container: KeyedDecodingContainer<CodingKeys>,
        key: CodingKeys,
        fallback: ReviewCardModeLayout
    ) -> ReviewCardModeLayout {
        guard container.contains(key),
              let nested = try? container.nestedContainer(keyedBy: ModeCodingKeys.self, forKey: key)
        else { return fallback }

        let front = decodeFields(from: nested, key: .front) ?? fallback.front
        let back = decodeFields(from: nested, key: .back) ?? fallback.back
        return ReviewCardModeLayout(front: front, back: back)
    }

    private static func decodeFields(
        from container: KeyedDecodingContainer<ModeCodingKeys>,
        key: ModeCodingKeys
    ) -> [ReviewCardField]? {
        guard container.contains(key),
              let rawValues = try? container.decode([String].self, forKey: key)
        else { return nil }

        var seen = Set<ReviewCardField>()
        return rawValues.compactMap(ReviewCardField.init(rawValue:)).filter {
            seen.insert($0).inserted
        }
    }

    private static func encode(
        _ layout: ReviewCardModeLayout,
        to container: inout KeyedEncodingContainer<CodingKeys>,
        key: CodingKeys
    ) throws {
        var nested = container.nestedContainer(keyedBy: ModeCodingKeys.self, forKey: key)
        try nested.encode(layout.front.map(\.rawValue), forKey: .front)
        try nested.encode(layout.back.map(\.rawValue), forKey: .back)
    }
}

@Observable
final class ReviewCardLayoutStore {
    static let storageKey = "review_card_layout_profile_v1"
    static let shared = ReviewCardLayoutStore()

    /// JSON/Date hard bound (start of year 10000 UTC, exclusive).
    static let maximumSupportedUnixTimestamp: TimeInterval = 253_402_300_800
    /// Legacy v1 envelopes are only trusted through this lower ceiling. That
    /// leaves a practical year of timestamp headroom before the hard bound.
    static let maximumLegacyUnixTimestamp: TimeInterval =
        maximumSupportedUnixTimestamp - (366 * 24 * 60 * 60)
    /// v2 envelopes retain a smaller independent reserve so a corrupt v2
    /// clock cannot reach the JSON/Date hard bound and poison future writes.
    static let maximumV2UnixTimestamp: TimeInterval =
        maximumSupportedUnixTimestamp - (24 * 60 * 60)

    private static let legacySchemaVersion = 1
    private static let schemaVersion = 2

    private struct Envelope: Codable {
        let version: Int
        let updatedAt: TimeInterval
        let profile: ReviewCardLayoutProfile
    }

    @ObservationIgnored private let defaults: UserDefaults?
    @ObservationIgnored private let cloud: CloudKeyValueStore?
    @ObservationIgnored private let now: () -> Date
    @ObservationIgnored private let notificationCenter: NotificationCenter?
    @ObservationIgnored private var cloudObserver: NSObjectProtocol?
    @ObservationIgnored private var resolvedUpdatedAt: TimeInterval?

    private(set) var profile: ReviewCardLayoutProfile

    convenience init() {
        self.init(defaults: .standard, cloud: CloudPreferencesSync.shared)
    }

    init(
        defaults: UserDefaults,
        cloud: CloudKeyValueStore = CloudPreferencesSync.shared,
        now: @escaping () -> Date = Date.init,
        notificationCenter: NotificationCenter = .default,
        cloudNotificationObject: Any? = NSUbiquitousKeyValueStore.default
    ) {
        self.defaults = defaults
        self.cloud = cloud
        self.now = now
        self.notificationCenter = notificationCenter

        let local = Self.decodeEnvelope(defaults.string(forKey: Self.storageKey))
        let remote = Self.decodeEnvelope(cloud.string(forKey: Self.storageKey))
        let resolved = Self.resolve(local: local, cloud: remote)
        self.profile = resolved?.profile.sanitized ?? .default
        self.resolvedUpdatedAt = resolved?.updatedAt

        cloudObserver = notificationCenter.addObserver(
            forName: NSUbiquitousKeyValueStore.didChangeExternallyNotification,
            object: cloudNotificationObject,
            queue: .main
        ) { [weak self] notification in
            self?.handleCloudChange(notification)
        }
    }

    private init(inMemoryProfile: ReviewCardLayoutProfile, now: @escaping () -> Date) {
        defaults = nil
        cloud = nil
        self.now = now
        notificationCenter = nil
        cloudObserver = nil
        resolvedUpdatedAt = nil
        profile = inMemoryProfile.sanitized
    }

    deinit {
        if let cloudObserver, let notificationCenter {
            notificationCenter.removeObserver(cloudObserver)
        }
    }

    static func inMemory(
        profile: ReviewCardLayoutProfile = .default,
        now: @escaping () -> Date = Date.init
    ) -> ReviewCardLayoutStore {
        ReviewCardLayoutStore(inMemoryProfile: profile, now: now)
    }

    func update(_ profile: ReviewCardLayoutProfile) {
        let sanitized = profile.sanitized
        guard defaults != nil, cloud != nil else {
            self.profile = sanitized
            return
        }

        let timestamp = nextTimestamp()
        guard let encoded = Self.encodeEnvelope(profile: sanitized, updatedAt: timestamp) else {
            return
        }
        defaults?.set(encoded, forKey: Self.storageKey)
        cloud?.set(encoded, forKey: Self.storageKey)
        self.profile = sanitized
        resolvedUpdatedAt = timestamp
    }

    func setLayout(_ layout: ReviewCardModeLayout, for mode: VocabularyCardMode) {
        var changed = profile
        changed.setLayout(layout, for: mode)
        update(changed)
    }

    func reset(_ mode: VocabularyCardMode) {
        setLayout(ReviewCardLayoutProfile.default.layout(for: mode), for: mode)
    }

    func resetAll() {
        update(.default)
    }

    private func nextTimestamp() -> TimeInterval {
        let rawCandidate = now().timeIntervalSince1970
        let candidate = Self.isSelfDecodableTimestamp(rawCandidate) ? rawCandidate : 0
        guard let resolvedUpdatedAt, candidate <= resolvedUpdatedAt else { return candidate }
        let bumped = resolvedUpdatedAt.nextUp
        // An exhausted v2 clock is only reachable after impractically many
        // writes. Prefer a finite repair over crashing; a stale high remote
        // value may still win LWW until the next normal timestamp overtakes it.
        return Self.isSelfDecodableTimestamp(bumped) ? bumped : candidate
    }

    private func handleCloudChange(_ notification: Notification) {
        guard let keys = notification.userInfo?[NSUbiquitousKeyValueStoreChangedKeysKey] as? [String],
              keys.contains(Self.storageKey),
              let remote = Self.decodeEnvelope(cloud?.string(forKey: Self.storageKey))
        else { return }
        if let resolvedUpdatedAt, remote.updatedAt < resolvedUpdatedAt { return }

        profile = remote.profile.sanitized
        resolvedUpdatedAt = remote.updatedAt
    }

    private static func resolve(local: Envelope?, cloud: Envelope?) -> Envelope? {
        switch (local, cloud) {
        case let (local?, cloud?):
            return cloud.updatedAt >= local.updatedAt ? cloud : local
        case let (local?, nil):
            return local
        case let (nil, cloud?):
            return cloud
        case (nil, nil):
            return nil
        }
    }

    private static func decodeEnvelope(_ string: String?) -> Envelope? {
        guard let string,
              let envelope = try? JSONDecoder().decode(Envelope.self, from: Data(string.utf8)),
              isAcceptedPersistedTimestamp(envelope.updatedAt, version: envelope.version)
        else { return nil }
        return envelope
    }

    private static func encodeEnvelope(
        profile: ReviewCardLayoutProfile,
        updatedAt: TimeInterval
    ) -> String? {
        guard isSelfDecodableTimestamp(updatedAt) else { return nil }
        let envelope = Envelope(
            version: schemaVersion,
            updatedAt: updatedAt,
            profile: profile
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        guard let data = try? encoder.encode(envelope) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func isAcceptedPersistedTimestamp(
        _ timestamp: TimeInterval,
        version: Int
    ) -> Bool {
        switch version {
        case legacySchemaVersion:
            timestamp.isFinite
                && timestamp >= 0
                && timestamp <= maximumLegacyUnixTimestamp
        case schemaVersion:
            isSelfDecodableTimestamp(timestamp)
        default:
            false
        }
    }

    private static func isSelfDecodableTimestamp(_ timestamp: TimeInterval) -> Bool {
        timestamp.isFinite
            && timestamp >= 0
            && timestamp < maximumV2UnixTimestamp
    }
}

private struct ReviewCardLayoutStoreKey: EnvironmentKey {
    static let defaultValue: ReviewCardLayoutStore = .shared
}

extension EnvironmentValues {
    var reviewCardLayoutStore: ReviewCardLayoutStore {
        get { self[ReviewCardLayoutStoreKey.self] }
        set { self[ReviewCardLayoutStoreKey.self] = newValue }
    }
}
