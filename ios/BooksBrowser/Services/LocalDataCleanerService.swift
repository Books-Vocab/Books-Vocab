import Foundation
import SwiftData

final class LocalDataCleanerService: LocalDataClearing {
    func clearLocalData(container: ModelContainer, reason: String) async {
        let actor = BackgroundSyncActor(modelContainer: container)
        AppLog.sync.info("clearLocalData requested. reason=\(reason)")
        do {
            try await actor.clearUserData(reason: reason)
        } catch {
            AppLog.sync.error("clearUserData failed: \(error.localizedDescription)")
        }
        let defaults = UserDefaults.standard
        // 用 KGService.SyncKeys 常數，與 sync 路徑單一真相對齊（勿用 magic string）。
        defaults.removeObject(forKey: KGService.SyncKeys.incrementalBoundary)
        defaults.removeObject(forKey: KGService.SyncKeys.payloadVersion)
        // 漏清會讓 account-switch 後 B 沿用 A 的 review-event pull cursor，
        // incremental pull 可能漏抓 B 在該 cursor 之前的 review events。
        defaults.removeObject(forKey: KGService.SyncKeys.reviewEventPullBoundary)
        ActiveNotebookStore.shared.clear()
        defaults.removeObject(forKey: NotebookFilter.storageKey)
        // Today-review session snapshots are keyed per-user in a single
        // UserDefaults blob. Logout and account-switch both route through here,
        // so clear every user's snapshot to prevent a stale session from being
        // restored on re-login (or surviving until the 7-day maxAge expiry).
        TodayReviewSessionSnapshotStore.clear(for: nil)
        // QuotaStore is a process-wide singleton holding account A's remaining quota.
        // clearUserData drops SwiftData rows but never touches it, so after an
        // account-switch account B briefly sees A's quota number until the next
        // response header overwrites it. Reset on the main actor (where the
        // @Observable mutation is observed, matching KGService+Health's update hop).
        await MainActor.run { QuotaStore.shared.reset() }
        // Downloaded podcast .mp3s live on disk under Documents/podcast-downloads/,
        // not in SwiftData — clearUserData drops the rows but leaves the audio.
        // Purge the whole tree so a reused remoteId can't surface account A's
        // audio under account B after a switch (#726 follow-up).
        #if os(iOS)
        PodcastDownloadManager.purgeDownloads()
        // Downloaded podcast series covers live under Documents/podcast-covers/
        // (written by PodcastSyncService.cacheCoverIfNeeded), not in SwiftData.
        // Purge so a reused remoteId can't surface account A's cover under B.
        Self.purgePodcastCovers()
        // User-uploaded notebook covers live on disk under Documents/NotebookCovers/
        // (written by NotebookEditSheet), not in SwiftData. clearUserData drops the
        // Notebook rows but leaves the .jpg files as orphans, so they survive an
        // account-switch and accumulate on disk. Purge the whole tree (every cover
        // is necessarily orphaned once its owning row is gone). Books/Originals are
        // deliberately NOT touched here — book files have no server backing and
        // deleting them would permanently lose the user's library (#758 follow-up).
        Self.purgeNotebookCovers()
        #endif
    }

    #if os(iOS)
    static func coversRoot() -> URL {
        FileManager.default
            .urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("NotebookCovers", isDirectory: true)
    }

    /// Wipe the entire on-disk notebook-cover tree. Called on logout /
    /// account-switch so a residual `<uuid>.jpg` can't leak into another account
    /// or linger as a disk-space orphan after its Notebook row is dropped.
    ///
    /// `static` with an injectable `root` so tests can target a temp directory.
    /// Idempotent: a missing directory is a clean no-op, not an error — and the
    /// `catch` only logs (matching the podcast purge / `clearUserData failed`
    /// fault tolerance), never throwing into the logout/switch path.
    static func purgeNotebookCovers(root: URL = LocalDataCleanerService.coversRoot()) {
        guard FileManager.default.fileExists(atPath: root.path) else {
            AppLog.sync.info("purgeNotebookCovers: no NotebookCovers dir, nothing to remove")
            return
        }
        do {
            try FileManager.default.removeItem(at: root)
            AppLog.sync.info("purgeNotebookCovers: removed NotebookCovers tree at \(root.path, privacy: .public)")
        } catch {
            AppLog.sync.error("purgeNotebookCovers failed: \(error.localizedDescription)")
        }
    }

    /// Wipe the downloaded podcast-cover cache (`Documents/podcast-covers/`).
    /// Mirrors `purgeNotebookCovers` fault tolerance: missing dir = clean no-op,
    /// `catch` only logs — never throws into the logout/switch path.
    static func purgePodcastCovers(root: URL = PodcastSyncService.coversRoot()) {
        NotebookCoverImageCache.removeAll()
        guard FileManager.default.fileExists(atPath: root.path) else {
            AppLog.sync.info("purgePodcastCovers: no podcast-covers dir, nothing to remove")
            return
        }
        do {
            try FileManager.default.removeItem(at: root)
            AppLog.sync.info("purgePodcastCovers: removed podcast-covers tree at \(root.path, privacy: .public)")
        } catch {
            AppLog.sync.error("purgePodcastCovers failed: \(error.localizedDescription)")
        }
    }
    #endif
}
