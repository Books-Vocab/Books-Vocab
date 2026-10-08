import Foundation

/// Whether the Add Link sheet can do server work right now (#2039).
///
/// Linking an existing word and creating a new one both need the server, so while
/// the device is offline the sheet says so up front and refuses to start either —
/// before any optimistic local write, instead of after a failed round trip. The
/// signal is the app's own `NetworkMonitor.isConnected` (device reachability),
/// never `KGService.isConnected` (server health).
enum AddLinkConnectivity: Equatable {
    case online
    case offline

    init(isConnected: Bool) {
        self = isConnected ? .online : .offline
    }

    var allowsServerWork: Bool { self == .online }

    /// Pill shown when the sheet opens offline or the device drops offline.
    var noticeMessage: String? {
        switch self {
        case .online: nil
        case .offline: L10n.string("addLink.offline.notice")
        }
    }

    /// Why the create entry is disabled; nil while it is usable.
    var createDisabledReason: String? {
        switch self {
        case .online: nil
        case .offline: L10n.string("addLink.offline.createReason")
        }
    }

    /// Pill for a transition: offline → warning, back online → "restored";
    /// nil when nothing changed.
    static func transitionMessage(from old: AddLinkConnectivity, to new: AddLinkConnectivity) -> String? {
        guard old != new else { return nil }
        switch new {
        case .offline: return L10n.string("addLink.offline.notice")
        case .online: return L10n.string("addLink.offline.restored")
        }
    }
}
