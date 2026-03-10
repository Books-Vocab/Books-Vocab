import SwiftUI

/// 全域 Environment 注入點
/// App root 注入具體實例，View 與 Handler 依賴 protocol 類型
extension EnvironmentValues {
    @Entry var authManager: any AuthManaging = AuthManager.shared
    @Entry var kgService: any KGServing = KGService()
    @Entry var subscriptionManager: any SubscriptionManaging = SubscriptionManager.shared
    @Entry var readiumService: any ReadiumServing = ReadiumService.shared
    @Entry var bookshelfImportService: any BookshelfImporting = BookshelfImportService(readiumService: ReadiumService.shared)
    @Entry var bookFileManager: any BookFileManaging = LocalBookFileManager()
}
