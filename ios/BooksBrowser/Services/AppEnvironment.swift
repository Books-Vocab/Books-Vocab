import SwiftUI

/// 全域 Environment 注入點
/// App root 注入具體實例，View 與 Handler 依賴 protocol 類型

// MainActor-isolated services need manual EnvironmentKey because @Entry default
// evaluates in nonisolated context. nonisolated(unsafe) + MainActor.assumeIsolated
// is correct here: SwiftUI always evaluates EnvironmentKey defaults on the main
// thread, and static let ensures one-time initialization.
private struct SubscriptionManagerEnvironmentKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue: any SubscriptionManaging = MainActor.assumeIsolated {
        SubscriptionManager.shared
    }
}

private struct ReadiumServiceEnvironmentKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue: any ReadiumServing = MainActor.assumeIsolated {
        ReadiumService.shared
    }
}

private struct BookshelfImportServiceEnvironmentKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue: any BookshelfImporting = MainActor.assumeIsolated {
        BookshelfImportService(readiumService: ReadiumService.shared)
    }
}

private struct AuthManagerEnvironmentKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue: any AuthManaging = MainActor.assumeIsolated {
        AuthManager.shared
    }
}

private struct KGServiceEnvironmentKey: EnvironmentKey {
    nonisolated(unsafe) static let defaultValue: any KGServing = MainActor.assumeIsolated {
        KGService()
    }
}

private struct ICloudDownloadManagerKey: EnvironmentKey {
    static let defaultValue = MainActor.assumeIsolated {
        ICloudDownloadManager()
    }
}

private struct SyncCoordinatorKey: EnvironmentKey {
    static let defaultValue: SyncCoordinator = MainActor.assumeIsolated {
        SyncCoordinator()
    }
}

private struct AppToastCoordinatorKey: EnvironmentKey {
    static let defaultValue: AppToastCoordinator = MainActor.assumeIsolated {
        AppToastCoordinator()
    }
}

extension EnvironmentValues {
    var iCloudDownloadManager: ICloudDownloadManager {
        get { self[ICloudDownloadManagerKey.self] }
        set { self[ICloudDownloadManagerKey.self] = newValue }
    }
    var syncCoordinator: SyncCoordinator {
        get { self[SyncCoordinatorKey.self] }
        set { self[SyncCoordinatorKey.self] = newValue }
    }
    var toastCoordinator: AppToastCoordinator {
        get { self[AppToastCoordinatorKey.self] }
        set { self[AppToastCoordinatorKey.self] = newValue }
    }
    var authManager: any AuthManaging {
        get { self[AuthManagerEnvironmentKey.self] }
        set { self[AuthManagerEnvironmentKey.self] = newValue }
    }

    var kgService: any KGServing {
        get { self[KGServiceEnvironmentKey.self] }
        set { self[KGServiceEnvironmentKey.self] = newValue }
    }
    @Entry var networkMonitor: NetworkMonitor = .shared
    @Entry var bookFileManager: any BookFileManaging = LocalBookFileManager()
    @Entry var quotaStore: any QuotaProviding = QuotaStore.shared
    @Entry var speechService: any Speaking = SpeechService.shared
    @Entry var readerSettings: ReaderSettings = .shared

    var subscriptionManager: any SubscriptionManaging {
        get { self[SubscriptionManagerEnvironmentKey.self] }
        set { self[SubscriptionManagerEnvironmentKey.self] = newValue }
    }

    var readiumService: any ReadiumServing {
        get { self[ReadiumServiceEnvironmentKey.self] }
        set { self[ReadiumServiceEnvironmentKey.self] = newValue }
    }

    var bookshelfImportService: any BookshelfImporting {
        get { self[BookshelfImportServiceEnvironmentKey.self] }
        set { self[BookshelfImportServiceEnvironmentKey.self] = newValue }
    }
}
