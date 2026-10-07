import Foundation

/// Durable description of one in-flight "create missing target + link" job.
///
/// The record is the only thing that must survive an app kill: with the
/// operation id (or the idempotency key when the POST never answered) the next
/// launch can ask the server what happened instead of losing the work.
struct PendingLinkCreationRecord: Codable, Equatable, Identifiable {
    enum State: String, Codable {
        case creating
        case failed
    }

    var jobKey: String
    var word: String
    var sourceCardID: String
    var notebookId: String
    var idempotencyKey: String
    var operationId: String?
    /// True once the server reported a terminal failure for `operationId`.
    /// A terminal failure can never be resumed; a transport failure can.
    var operationTerminal: Bool = false
    var state: State
    var message: String?
    var createdAt: Date

    var id: String { jobKey }

    var retryPlan: AddLinkCreationRetryPlan {
        AddLinkCreationRetryPlan.make(
            operationId: operationId,
            operationTerminal: operationTerminal,
            idempotencyKey: idempotencyKey
        )
    }
}

protocol PendingLinkCreationStoring: AnyObject {
    func load() -> [PendingLinkCreationRecord]
    func save(_ records: [PendingLinkCreationRecord])
}

final class UserDefaultsPendingLinkCreationStore: PendingLinkCreationStoring {
    private let defaults: UserDefaults
    private let key: String

    init(defaults: UserDefaults = .standard, key: String = "kg.addLink.pendingCreations.v1") {
        self.defaults = defaults
        self.key = key
    }

    func load() -> [PendingLinkCreationRecord] {
        guard let data = defaults.data(forKey: key),
              let records = try? JSONDecoder().decode([PendingLinkCreationRecord].self, from: data)
        else { return [] }
        return records
    }

    func save(_ records: [PendingLinkCreationRecord]) {
        if records.isEmpty {
            defaults.removeObject(forKey: key)
            return
        }
        guard let data = try? JSONEncoder().encode(records) else { return }
        defaults.set(data, forKey: key)
    }
}

/// Non-persisting store: unit tests, and `-isolatedAuthSession` UI-test runs
/// (same hermetic contract as `EphemeralAuthSessionStore`) so a pending record
/// from one UI test can never surface in the next one.
final class EphemeralPendingLinkCreationStore: PendingLinkCreationStoring {
    private(set) var records: [PendingLinkCreationRecord]

    init(records: [PendingLinkCreationRecord] = []) { self.records = records }

    func load() -> [PendingLinkCreationRecord] { records }
    func save(_ records: [PendingLinkCreationRecord]) { self.records = records }
}

enum PendingLinkCreationStores {
    /// Composition root: persistent in the app, ephemeral under isolated UI tests.
    static func makeDefault(
        arguments: [String] = ProcessInfo.processInfo.arguments,
        defaults: UserDefaults = .standard
    ) -> any PendingLinkCreationStoring {
        if AppRuntimeOptions.shouldUseIsolatedAuthSession(arguments: arguments) {
            return EphemeralPendingLinkCreationStore()
        }
        return UserDefaultsPendingLinkCreationStore(defaults: defaults)
    }
}

/// Review-card projection of pending creations, keyed by source card id.
///
/// `CardPresentation` is a pure value built off the main actor by the card
/// cache, so the projection is a tiny lock-protected value store rather than a
/// main-actor object. The hub is the only writer.
final class PendingLinkProjection: @unchecked Sendable {
    static let shared = PendingLinkProjection()

    private let lock = NSLock()
    private var linksBySourceCardID: [String: [KGCardLinkSummary]] = [:]

    func links(forSourceCardID sourceCardID: String?) -> [KGCardLinkSummary] {
        guard let sourceCardID, !sourceCardID.isEmpty else { return [] }
        lock.lock()
        defer { lock.unlock() }
        return linksBySourceCardID[sourceCardID] ?? []
    }

    func replaceAll(with links: [String: [KGCardLinkSummary]]) {
        lock.lock()
        linksBySourceCardID = links
        lock.unlock()
    }
}

extension KGCardLinkSummary {
    enum CreationState: String {
        case creating
        case failed
    }

    static let pendingCreationIDPrefix = "pending-create:"
    private static let pendingCreationReasonPrefix = "creation:"

    /// Placeholder for a link whose target card does not exist yet. It has no
    /// `cardId` (the server has not minted one), so identity is the job key
    /// (source card + normalized word). The `pending-` prefix keeps it a
    /// regular `isPending` placeholder for every existing renderer.
    static func pendingCreation(
        jobKey: String,
        word: String,
        state: CreationState
    ) -> KGCardLinkSummary {
        KGCardLinkSummary(
            id: pendingCreationIDPrefix + jobKey,
            cardId: "",
            word: word,
            kind: "shares_usage",
            label: L10n.string("相關"),
            confidence: 0,
            reason: pendingCreationReasonPrefix + state.rawValue,
            hidden: false
        )
    }

    var pendingCreationJobKey: String? {
        guard id.hasPrefix(Self.pendingCreationIDPrefix) else { return nil }
        return String(id.dropFirst(Self.pendingCreationIDPrefix.count))
    }

    var pendingCreationState: CreationState? {
        guard pendingCreationJobKey != nil,
              reason.hasPrefix(Self.pendingCreationReasonPrefix)
        else { return nil }
        return CreationState(rawValue: String(reason.dropFirst(Self.pendingCreationReasonPrefix.count)))
    }

    var isPendingCreation: Bool { pendingCreationJobKey != nil }
}
