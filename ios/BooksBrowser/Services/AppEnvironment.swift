import SwiftUI

/// 全域 Environment 注入點
/// App root 注入具體實例，View 與 Handler 依賴 protocol 類型
///
/// 設計：MainActor-isolated services 的 EnvironmentKey defaults 改用
/// computed `static var`，將 `MainActor.assumeIsolated { ... }` 延遲到
/// SwiftUI 實際讀取 default 的時點（保證在 main thread）。
/// 相較於 `nonisolated(unsafe) static let`，避免靜態初始化時序未定的隱患。

private struct SubscriptionManagerEnvironmentKey: EnvironmentKey {
    static var defaultValue: any SubscriptionManaging {
        MainActor.assumeIsolated { SubscriptionManager.shared }
    }
}

#if os(iOS)
private struct ReadiumServiceEnvironmentKey: EnvironmentKey {
    static var defaultValue: any ReadiumServing {
        MainActor.assumeIsolated { ReadiumService.shared }
    }
}

private struct BookshelfImportServiceEnvironmentKey: EnvironmentKey {
    static var defaultValue: any BookshelfImporting {
        MainActor.assumeIsolated {
            BookshelfImportService(readiumService: ReadiumService.shared)
        }
    }
}
#endif

private struct AuthManagerEnvironmentKey: EnvironmentKey {
    static var defaultValue: any AuthManaging {
        MainActor.assumeIsolated { AuthManager.shared }
    }
}

private struct KGServiceEnvironmentKey: EnvironmentKey {
    static var defaultValue: any KGServing {
        MainActor.assumeIsolated { KGService() }
    }
}

private struct ICloudDownloadManagerKey: EnvironmentKey {
    static var defaultValue: ICloudDownloadManager {
        MainActor.assumeIsolated { ICloudDownloadManager() }
    }
}

private struct SyncCoordinatorKey: EnvironmentKey {
    static var defaultValue: SyncCoordinator {
        MainActor.assumeIsolated { SyncCoordinator() }
    }
}

private struct AppToastCoordinatorKey: EnvironmentKey {
    static var defaultValue: AppToastCoordinator {
        MainActor.assumeIsolated { AppToastCoordinator() }
    }
}

private struct AppCommandCoordinatorKey: EnvironmentKey {
    static var defaultValue: AppCommandCoordinator {
        MainActor.assumeIsolated { AppCommandCoordinator() }
    }
}

private struct NetworkMonitorKey: EnvironmentKey {
    static let defaultValue: NetworkMonitor = .shared
}

private struct BookFileManagerKey: EnvironmentKey {
    static let defaultValue: any BookFileManaging = LocalBookFileManager()
}

private struct QuotaStoreKey: EnvironmentKey {
    static let defaultValue: any QuotaProviding = QuotaStore.shared
}

private struct SpeechServiceKey: EnvironmentKey {
    static let defaultValue: any Speaking = SpeechService.shared
}

enum CatalogTaskPolicy: Equatable {
    case live
    case disabled

    var runsTasks: Bool { self == .live }
}

private struct CatalogTaskPolicyKey: EnvironmentKey {
    static let defaultValue: CatalogTaskPolicy = .live
}

#if os(iOS)
private struct ReaderSettingsKey: EnvironmentKey {
    static let defaultValue: ReaderSettings = .shared
}
#endif

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
    var appCommandCoordinator: AppCommandCoordinator {
        get { self[AppCommandCoordinatorKey.self] }
        set { self[AppCommandCoordinatorKey.self] = newValue }
    }
    var authManager: any AuthManaging {
        get { self[AuthManagerEnvironmentKey.self] }
        set { self[AuthManagerEnvironmentKey.self] = newValue }
    }

    var kgService: any KGServing {
        get { self[KGServiceEnvironmentKey.self] }
        set { self[KGServiceEnvironmentKey.self] = newValue }
    }
    var networkMonitor: NetworkMonitor {
        get { self[NetworkMonitorKey.self] }
        set { self[NetworkMonitorKey.self] = newValue }
    }
    var bookFileManager: any BookFileManaging {
        get { self[BookFileManagerKey.self] }
        set { self[BookFileManagerKey.self] = newValue }
    }
    var quotaStore: any QuotaProviding {
        get { self[QuotaStoreKey.self] }
        set { self[QuotaStoreKey.self] = newValue }
    }
    var speechService: any Speaking {
        get { self[SpeechServiceKey.self] }
        set { self[SpeechServiceKey.self] = newValue }
    }
    var catalogTaskPolicy: CatalogTaskPolicy {
        get { self[CatalogTaskPolicyKey.self] }
        set { self[CatalogTaskPolicyKey.self] = newValue }
    }
    #if os(iOS)
    var readerSettings: ReaderSettings {
        get { self[ReaderSettingsKey.self] }
        set { self[ReaderSettingsKey.self] = newValue }
    }
    #endif

    var subscriptionManager: any SubscriptionManaging {
        get { self[SubscriptionManagerEnvironmentKey.self] }
        set { self[SubscriptionManagerEnvironmentKey.self] = newValue }
    }

    #if os(iOS)
    var readiumService: any ReadiumServing {
        get { self[ReadiumServiceEnvironmentKey.self] }
        set { self[ReadiumServiceEnvironmentKey.self] = newValue }
    }

    var bookshelfImportService: any BookshelfImporting {
        get { self[BookshelfImportServiceEnvironmentKey.self] }
        set { self[BookshelfImportServiceEnvironmentKey.self] = newValue }
    }
    #endif
}
