#if os(iOS)
import SwiftUI
import Testing
@testable import BooksAndVocab

struct SubscriptionPaywallFeatureCatalogTests {

    @Test func comparisonRows_followSingleCatalog() {
        #expect(SubscriptionPaywallFeatureCatalog.descriptors.count == 8)
        #expect(SubscriptionPaywallFeatureCatalog.comparisonRows.count == SubscriptionPaywallFeatureCatalog.descriptors.count)

        let quotaRow = SubscriptionPaywallFeatureCatalog.comparisonRows.last
        #expect(quotaRow?.title == L10n.string("每日 AI 額度"))
        #expect(quotaRow?.freeMark == .label("1x"))
        #expect(quotaRow?.proMark == .label("10x"))
    }

    @Test func activeAndPaywallLists_areDerivedFromSameDescriptors() {
        let activeItems = SubscriptionPaywallFeatureCatalog.activeItems(successTone: .green)
        let paywallItems = SubscriptionPaywallFeatureCatalog.paywallItems(accentTone: .blue)

        #expect(activeItems.count == 3)
        #expect(paywallItems.count == 3)
        #expect(activeItems.map(\.title) == paywallItems.map(\.title))
        #expect(paywallItems.allSatisfy { $0.description?.isEmpty == false })
        #expect(activeItems.allSatisfy { $0.description == nil })
    }
}
#endif
