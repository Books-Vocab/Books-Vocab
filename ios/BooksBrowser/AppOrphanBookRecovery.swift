//
//  AppOrphanBookRecovery.swift
//  Books & Vocab
//
//  Store reset 後掃描磁碟與 DB 對齊 — 為磁碟上有檔但 DB 沒記錄的書補建 Book。
//  與 AppBootstrap 解耦：bootstrap 關心「拿到 container」，本檔關心「磁碟 vs DB 對齊」。
//

import Foundation
import SwiftData

enum AppOrphanBookRecovery {
    @MainActor
    static func run(container: ModelContainer, allowBareFileRecovery: Bool = false) {
        do {
            let result = try BookLibraryReconciler().reconcile(
                context: ModelContext(container),
                allowBareFileRecovery: allowBareFileRecovery
            )
            AppLog.app.info("recoverOrphanBooks: recovered=\(result.recoveredRows), manifests=\(result.writtenManifests), duplicatesRemoved=\(result.duplicateRowsRemoved), updated=\(result.updatedRows)")
        } catch {
            AppLog.app.error("recoverOrphanBooks: reconcile failed: \(error.localizedDescription)")
        }
    }
}
