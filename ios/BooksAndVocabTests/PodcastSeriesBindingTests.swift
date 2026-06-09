#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Phase 3：podcast 系列綁定恰好一本真實單字本（與 Book 共用 NotebookBindable）。
struct PodcastSeriesBindingTests {
    private func makeSeries() -> PodcastSeries {
        PodcastSeries(remoteId: "s1", title: "S", hostNames: [])
    }

    @Test func seedsBindingWhenUnbound() {
        let series = makeSeries()
        #expect(series.preferredNotebookId == nil)
        let resolved = series.ensureBoundNotebook(seed: "nb-x")
        #expect(resolved == "nb-x")
        #expect(series.preferredNotebookId == "nb-x")
    }

    @Test func doesNotOverrideExistingBinding() {
        let series = makeSeries()
        series.preferredNotebookId = "nb-a"
        #expect(series.ensureBoundNotebook(seed: "nb-y") == "nb-a")
        #expect(series.preferredNotebookId == "nb-a")
    }

    @Test func seedGateRejectsSentinelAbsentFromLive() {
        #expect(PodcastSeries.canSeedBinding(seed: "nb-x", liveNotebookIds: ["nb-x"]))
        #expect(!PodcastSeries.canSeedBinding(seed: "default", liveNotebookIds: ["nb-x"]))
        #expect(!PodcastSeries.canSeedBinding(seed: "nb-x", liveNotebookIds: []))
    }
}
#endif
