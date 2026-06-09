import Testing
@testable import BooksAndVocab

/// `PodcastQueue.nextPlayable` 的 tier × 順序 × 可用性矩陣。auto-advance 的決策核心，
/// entitlement 邊界必須擋住 free/guest 跨集（鏡射後端 + `PodcastAccess`）。
@Suite("PodcastQueue")
struct PodcastQueueTests {
    /// 建測試 episode（ModelContext 外建構，僅供純函式測試）。
    private func ep(_ n: Int, audio: Bool = true, preview: Bool = false) -> PodcastEpisode {
        let e = PodcastEpisode(remoteId: "s_ep_\(n)", episodeNumber: n, title: "Ep \(n)", durationSec: 600)
        e.audioAvailable = audio
        e.previewAvailable = preview
        return e
    }

    @Test func proAdvancesToImmediateNext() {
        let eps = [ep(1), ep(2), ep(3)]
        let next = PodcastQueue.nextPlayable(in: eps, after: eps[0], tier: .pro)
        #expect(next?.episodeNumber == 2)
    }

    @Test func proStopsAtLastEpisode() {
        let eps = [ep(1), ep(2)]
        #expect(PodcastQueue.nextPlayable(in: eps, after: eps[1], tier: .pro) == nil)
    }

    @Test func freeStopsAfterPreviewEpisodeOne() {
        // free 播完 ep1（preview 可播）後不自動跨到 Pro-only ep2。
        let eps = [ep(1, preview: true), ep(2)]
        #expect(PodcastQueue.nextPlayable(in: eps, after: eps[0], tier: .free) == nil)
    }

    @Test func guestNeverAdvances() {
        let eps = [ep(1, preview: true), ep(2)]
        #expect(PodcastQueue.nextPlayable(in: eps, after: eps[0], tier: .guest) == nil)
    }

    @Test func skipsEpisodesWithoutAudioThenGates() {
        // ep2 無音訊跳過；ep3 有音訊 → pro 可續播 ep3。
        let eps = [ep(1), ep(2, audio: false), ep(3)]
        let next = PodcastQueue.nextPlayable(in: eps, after: eps[0], tier: .pro)
        #expect(next?.episodeNumber == 3)
    }

    @Test func unsortedInputResolvesByEpisodeNumber() {
        // 輸入亂序仍依 episodeNumber 取嚴格次大者。
        let e1 = ep(1), e2 = ep(2), e3 = ep(3)
        let next = PodcastQueue.nextPlayable(in: [e3, e1, e2], after: e1, tier: .pro)
        #expect(next?.episodeNumber == 2)
    }

    @Test func currentNotInListReturnsNil() {
        let eps = [ep(1), ep(2)]
        #expect(PodcastQueue.nextPlayable(in: eps, after: ep(9), tier: .pro) == nil)
    }
}
