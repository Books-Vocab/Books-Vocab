import Foundation
import SwiftData
import os

final class LocalDataCleanerService: LocalDataClearing {
    func clearLocalData(container: ModelContainer, reason: String) async {
        let actor = BackgroundSyncActor(modelContainer: container)
        AppLog.sync.info("clearLocalData requested. reason=\(reason)")
        do {
            try await actor.clearVocabularyData(reason: reason)
        } catch {
            AppLog.sync.error("clearVocabularyData failed: \(error.localizedDescription)")
        }
        let defaults = UserDefaults.standard
        defaults.removeObject(forKey: "kg_last_incremental_sync")
        defaults.removeObject(forKey: "kg_review_payload_version")
        defaults.removeObject(forKey: "activeNotebookId")
        defaults.removeObject(forKey: NotebookFilter.storageKey)
    }
}
