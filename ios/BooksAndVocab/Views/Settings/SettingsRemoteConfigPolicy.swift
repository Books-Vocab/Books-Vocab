/// Pure decisions shared by Settings' remote configuration and explicit sync
/// flows. The coordinator remains responsible for I/O and MainActor state.
enum SettingsRemoteConfigPolicy {
    enum FetchOutcome: Sendable {
        case success
        case failure
    }

    enum FetchDisposition: Equatable, Sendable {
        case apply
        case preserveLocalValues
        case ignoreLateResult
    }

    struct ResyncRequest: Equatable, Sendable {
        let accountGeneration: Int
        let requestID: Int
        let userID: String?
    }

    static func fetchDisposition(
        outcome: FetchOutcome,
        isCancelled: Bool,
        isLoggedIn: Bool,
        isDemoMode: Bool,
        requestedUserID: String,
        currentUserID: String?
    ) -> FetchDisposition {
        switch outcome {
        case .success:
            guard !isCancelled,
                  isLoggedIn,
                  !isDemoMode,
                  currentUserID == requestedUserID
            else {
                return .ignoreLateResult
            }
            return .apply
        case .failure:
            // Preserve the existing failure fallback: the coordinator keeps
            // local/iCloud values visible and reports the fetch issue.
            return .preserveLocalValues
        }
    }

    static func acceptsResyncResult(
        request: ResyncRequest,
        currentAccountGeneration: Int,
        currentRequestID: Int,
        isCancelled: Bool,
        isLoggedIn: Bool,
        isDemoMode: Bool,
        currentUserID: String?
    ) -> Bool {
        !isCancelled &&
            request.accountGeneration == currentAccountGeneration &&
            request.requestID == currentRequestID &&
            isLoggedIn &&
            !isDemoMode &&
            request.userID == currentUserID
    }

    static func acceptsMutationFailure(token: Int, currentGeneration: Int) -> Bool {
        token == currentGeneration
    }
}

/// Monotonic guard for optimistic settings mutations. A late failure from an
/// older request must not roll back a newer user intent.
struct SettingsMutationGeneration: Equatable, Sendable {
    private(set) var current = 0

    mutating func begin() -> Int {
        current &+= 1
        return current
    }

    func accepts(_ token: Int) -> Bool {
        SettingsRemoteConfigPolicy.acceptsMutationFailure(
            token: token,
            currentGeneration: current
        )
    }
}
