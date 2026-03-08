import SwiftUI

/// 全域 Environment 注入點
/// App root 注入具體實例，View 與 Handler 依賴 protocol 類型
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

private struct BookFileManagerEnvironmentKey: EnvironmentKey {
    static let defaultValue: any BookFileManaging = LocalBookFileManager()
}

extension EnvironmentValues {
    @Entry var authManager: any AuthManaging = AuthManager.shared
    @Entry var kgService: any KGServing = KGService()

    var readiumService: any ReadiumServing {
        get { self[ReadiumServiceEnvironmentKey.self] }
        set { self[ReadiumServiceEnvironmentKey.self] = newValue }
    }

    var bookshelfImportService: any BookshelfImporting {
        get { self[BookshelfImportServiceEnvironmentKey.self] }
        set { self[BookshelfImportServiceEnvironmentKey.self] = newValue }
    }

    var bookFileManager: any BookFileManaging {
        get { self[BookFileManagerEnvironmentKey.self] }
        set { self[BookFileManagerEnvironmentKey.self] = newValue }
    }
}
