import Testing
@testable import BooksAndVocab

@Suite("AutoSyncMonitor")
struct AutoSyncMonitorTests {
    @Test func shouldTriggerWhenAllConditionsMet() {
        let result = AutoSyncMonitor.shouldTrigger(
            pendingCount: 5,
            isEnabled: true,
            isRunning: false,
            isLoggedIn: true,
            isDemoMode: false,
            isConnected: true
        )
        #expect(result == true)
    }

    @Test func shouldNotTriggerWhenDisabled() {
        let result = AutoSyncMonitor.shouldTrigger(
            pendingCount: 5,
            isEnabled: false,
            isRunning: false,
            isLoggedIn: true,
            isDemoMode: false,
            isConnected: true
        )
        #expect(result == false)
    }

    @Test func shouldNotTriggerBelowThreshold() {
        let result = AutoSyncMonitor.shouldTrigger(
            pendingCount: 4,
            isEnabled: true,
            isRunning: false,
            isLoggedIn: true,
            isDemoMode: false,
            isConnected: true
        )
        #expect(result == false)
    }

    @Test func shouldNotTriggerWhileRunning() {
        let result = AutoSyncMonitor.shouldTrigger(
            pendingCount: 5,
            isEnabled: true,
            isRunning: true,
            isLoggedIn: true,
            isDemoMode: false,
            isConnected: true
        )
        #expect(result == false)
    }

    @Test func shouldNotTriggerWhenOffline() {
        let result = AutoSyncMonitor.shouldTrigger(
            pendingCount: 5,
            isEnabled: true,
            isRunning: false,
            isLoggedIn: true,
            isDemoMode: false,
            isConnected: false
        )
        #expect(result == false)
    }

    @Test func shouldNotTriggerWhenLoggedOut() {
        let result = AutoSyncMonitor.shouldTrigger(
            pendingCount: 5,
            isEnabled: true,
            isRunning: false,
            isLoggedIn: false,
            isDemoMode: false,
            isConnected: true
        )
        #expect(result == false)
    }

    @Test func shouldNotTriggerInDemoMode() {
        let result = AutoSyncMonitor.shouldTrigger(
            pendingCount: 5,
            isEnabled: true,
            isRunning: false,
            isLoggedIn: true,
            isDemoMode: true,
            isConnected: true
        )
        #expect(result == false)
    }

    @Test func shouldScheduleEvaluationOnlyWhenConnectivityRestores() {
        #expect(AutoSyncMonitor.shouldScheduleOnConnectivityChange(wasConnected: false, isConnected: true))
        #expect(!AutoSyncMonitor.shouldScheduleOnConnectivityChange(wasConnected: true, isConnected: true))
        #expect(!AutoSyncMonitor.shouldScheduleOnConnectivityChange(wasConnected: true, isConnected: false))
        #expect(!AutoSyncMonitor.shouldScheduleOnConnectivityChange(wasConnected: false, isConnected: false))
    }
}
