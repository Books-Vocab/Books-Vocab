import Testing
@testable import BooksAndVocab

struct SettingsRemoteConfigPolicyTests {
    @Test
    func currentSuccessfulFetchIsApplied() {
        let disposition = SettingsRemoteConfigPolicy.fetchDisposition(
            outcome: .success,
            isCancelled: false,
            isLoggedIn: true,
            isDemoMode: false,
            requestedUserID: "account-a",
            currentUserID: "account-a"
        )

        #expect(disposition == .apply)
    }

    @Test
    func currentFetchFailurePreservesLocalValues() {
        let disposition = SettingsRemoteConfigPolicy.fetchDisposition(
            outcome: .failure,
            isCancelled: false,
            isLoggedIn: true,
            isDemoMode: false,
            requestedUserID: "account-a",
            currentUserID: "account-a"
        )

        #expect(disposition == .preserveLocalValues)
    }

    @Test
    func cancelledOrLateFetchIsIgnored() {
        let cancelled = SettingsRemoteConfigPolicy.fetchDisposition(
            outcome: .success,
            isCancelled: true,
            isLoggedIn: true,
            isDemoMode: false,
            requestedUserID: "account-a",
            currentUserID: "account-a"
        )
        let accountSwitched = SettingsRemoteConfigPolicy.fetchDisposition(
            outcome: .success,
            isCancelled: false,
            isLoggedIn: true,
            isDemoMode: false,
            requestedUserID: "account-a",
            currentUserID: "account-b"
        )

        #expect(cancelled == .ignoreLateResult)
        #expect(accountSwitched == .ignoreLateResult)
    }

    @Test
    func resyncResultRequiresCurrentGenerationRequestAndAccount() {
        let request = SettingsRemoteConfigPolicy.ResyncRequest(
            accountGeneration: 4,
            requestID: 9,
            userID: "account-a"
        )

        #expect(
            SettingsRemoteConfigPolicy.acceptsResyncResult(
                request: request,
                currentAccountGeneration: 4,
                currentRequestID: 9,
                isCancelled: false,
                isLoggedIn: true,
                isDemoMode: false,
                currentUserID: "account-a"
            )
        )
        #expect(
            !SettingsRemoteConfigPolicy.acceptsResyncResult(
                request: request,
                currentAccountGeneration: 5,
                currentRequestID: 9,
                isCancelled: false,
                isLoggedIn: true,
                isDemoMode: false,
                currentUserID: "account-a"
            )
        )
        #expect(
            !SettingsRemoteConfigPolicy.acceptsResyncResult(
                request: request,
                currentAccountGeneration: 4,
                currentRequestID: 10,
                isCancelled: false,
                isLoggedIn: true,
                isDemoMode: false,
                currentUserID: "account-a"
            )
        )
        #expect(
            !SettingsRemoteConfigPolicy.acceptsResyncResult(
                request: request,
                currentAccountGeneration: 4,
                currentRequestID: 9,
                isCancelled: false,
                isLoggedIn: true,
                isDemoMode: false,
                currentUserID: "account-b"
            )
        )
    }

    @Test
    func cancelledOrUnauthenticatedResyncIsRejected() {
        let request = SettingsRemoteConfigPolicy.ResyncRequest(
            accountGeneration: 1,
            requestID: 1,
            userID: "account-a"
        )

        #expect(
            !SettingsRemoteConfigPolicy.acceptsResyncResult(
                request: request,
                currentAccountGeneration: 1,
                currentRequestID: 1,
                isCancelled: true,
                isLoggedIn: true,
                isDemoMode: false,
                currentUserID: "account-a"
            )
        )
        #expect(
            !SettingsRemoteConfigPolicy.acceptsResyncResult(
                request: request,
                currentAccountGeneration: 1,
                currentRequestID: 1,
                isCancelled: false,
                isLoggedIn: false,
                isDemoMode: false,
                currentUserID: "account-a"
            )
        )
        #expect(
            !SettingsRemoteConfigPolicy.acceptsResyncResult(
                request: request,
                currentAccountGeneration: 1,
                currentRequestID: 1,
                isCancelled: false,
                isLoggedIn: true,
                isDemoMode: true,
                currentUserID: "account-a"
            )
        )
    }

    @Test
    func onlyCurrentMutationCanRollbackAfterLateFailure() {
        var generation = SettingsMutationGeneration()
        let first = generation.begin()
        let second = generation.begin()

        #expect(
            !SettingsRemoteConfigPolicy.acceptsMutationFailure(
                token: first,
                currentGeneration: generation.current
            )
        )
        #expect(
            SettingsRemoteConfigPolicy.acceptsMutationFailure(
                token: second,
                currentGeneration: generation.current
            )
        )
    }
}
