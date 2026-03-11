import Foundation
import SwiftData
import os

final class LocalDataCleanerService: LocalDataClearing {
    func clearLocalData(container: ModelContainer, reason: String) async {
        let actor = BackgroundSyncActor(modelContainer: container)
        AppLog.sync.info("clearLocalData requested. reason=\(reason)")
        try? await actor.clearVocabularyData(reason: reason)
        UserDefaults.standard.removeObject(forKey: "kg_last_incremental_sync")
    }
}
