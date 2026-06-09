#if os(iOS)
import Foundation
import SwiftData
import os

@MainActor
protocol VocabularyContextStore: VocabularyContextProtocol {
    var vocabulary: [VocabularyEntry] { get }
    var modelContext: ModelContext { get }
    var toastCoordinator: AppToastCoordinator { get }
    var queuedDeleteLogPrefix: String { get }
    var localDeleteLogPrefix: String { get }
    var fetchFailureLogPrefix: String? { get }
}

extension VocabularyContextStore {
    var fetchFailureLogPrefix: String? { nil }

    static func entryMatches(_ entry: VocabularyEntry, wordLower: String) -> Bool {
        let normalized = entry.word.lowercased()
        if normalized == wordLower { return true }
        if entry.rootForm?.lowercased() == wordLower { return true }
        return entry.inflections.contains { $0.lowercased() == wordLower }
    }

    func existingEntry(matching word: String) -> VocabularyEntry? {
        let wordLower = word.lowercased()
        let scope = notebookId
        return vocabulary.first { entry in
            guard entry.notebookId == scope else { return false }
            return Self.entryMatches(entry, wordLower: wordLower)
        }
    }

    func deleteEntry(matching word: String) {
        // Snapshot lookup may miss entries inserted in the same event cycle
        // because saveEntry uses deferSave() and @Query refresh is async.
        let entry = existingEntry(matching: word) ?? fetchEntryFromContext(matching: word)
        guard let entry else { return }

        if entry.isSynced {
            entry.queueDelete()
            AppLog.reader.info("\(queuedDeleteLogPrefix): \(word)")
        } else {
            modelContext.delete(entry)
            AppLog.reader.info("\(localDeleteLogPrefix): \(word)")
        }
        modelContext.safeSaveWithToast(toastCoordinator)
    }

    func restoreExistingEntryForSave(
        matching word: String,
        translation: String,
        rootForm: String?
    ) -> Bool? {
        guard let existing = existingEntry(matching: word) else { return nil }
        if existing.syncAction == .delete {
            existing.restorePendingEntry()
            existing.translation = translation
            if let rootForm { existing.rootForm = rootForm }
            modelContext.safeSaveWithToast(toastCoordinator)
            return true
        }
        return false
    }

    func deferSave() {
        let ctx = modelContext
        let toast = toastCoordinator
        DispatchQueue.main.async {
            ctx.safeSaveWithToast(toast)
        }
    }

    static func lookedUpWords(from vocabulary: [VocabularyEntry], notebookId: String? = nil) -> [String] {
        vocabulary.filter { entry in
            guard entry.shouldAppearInReader else { return false }
            if let notebookId {
                return entry.notebookId == notebookId
            }
            return true
        }.flatMap { entry in
            var all = Set([entry.word.lowercased()] + entry.inflections.map { $0.lowercased() })
            if let root = entry.rootForm?.lowercased() { all.insert(root) }
            return Array(all)
        }
    }

    private func fetchEntryFromContext(matching word: String) -> VocabularyEntry? {
        let nbId = notebookId
        let descriptor = FetchDescriptor<VocabularyEntry>(
            predicate: #Predicate<VocabularyEntry> { $0.notebookId == nbId }
        )
        let candidates: [VocabularyEntry]
        do {
            candidates = try modelContext.fetch(descriptor)
        } catch {
            if let fetchFailureLogPrefix {
                AppLog.reader.error("\(fetchFailureLogPrefix, privacy: .public): \(error.localizedDescription, privacy: .public)")
            }
            return nil
        }
        let wordLower = word.lowercased()
        return candidates.first { Self.entryMatches($0, wordLower: wordLower) }
    }
}
#endif
