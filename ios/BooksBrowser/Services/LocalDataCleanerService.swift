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
        UserDefaults.standard.removeObject(forKey: "kg_last_incremental_sync")
    }
}
