import Foundation
import Testing
@testable import BooksAndVocab

/// #2039: offline is announced up front and the create entry is disabled and
/// explained — not hidden — so nothing starts server work the device cannot do.
@Suite("Add Link connectivity (#2039)")
struct AddLinkConnectivityTests {
    @Test("device reachability maps onto online/offline")
    func mapping() {
        #expect(AddLinkConnectivity(isConnected: true) == .online)
        #expect(AddLinkConnectivity(isConnected: false) == .offline)
    }

    @Test("online: server work allowed, no notice, no disabled reason")
    func onlineState() {
        let state = AddLinkConnectivity.online
        #expect(state.allowsServerWork)
        #expect(state.noticeMessage == nil)
        #expect(state.createDisabledReason == nil)
    }

    @Test("offline: server work refused, with a notice and a reason for the create entry")
    func offlineState() {
        let state = AddLinkConnectivity.offline
        #expect(!state.allowsServerWork)
        #expect(state.noticeMessage == L10n.string("addLink.offline.notice"))
        #expect(state.createDisabledReason == L10n.string("addLink.offline.createReason"))
        #expect(state.noticeMessage != "addLink.offline.notice", "key must be localized")
        #expect(state.createDisabledReason != "addLink.offline.createReason", "key must be localized")
    }

    @Test("only a change of state produces a pill")
    func transitions() {
        #expect(AddLinkConnectivity.transitionMessage(from: .online, to: .online) == nil)
        #expect(AddLinkConnectivity.transitionMessage(from: .offline, to: .offline) == nil)
        #expect(
            AddLinkConnectivity.transitionMessage(from: .online, to: .offline)
                == L10n.string("addLink.offline.notice")
        )
        #expect(
            AddLinkConnectivity.transitionMessage(from: .offline, to: .online)
                == L10n.string("addLink.offline.restored")
        )
    }

    @Test("the copy is translated in every locale")
    func copyIsLocalized() {
        let languages: [AppLanguage] = [.english, .traditionalChinese, .simplifiedChinese, .japanese, .korean]
        for key in ["addLink.offline.notice", "addLink.offline.restored", "addLink.offline.createReason"] {
            for language in languages {
                let value = L10n.string(key, language: language)
                #expect(value != key, "\(key) missing in \(language)")
                #expect(!value.isEmpty)
            }
        }
    }

    @Test("the create entry copy used while offline is the disabled reason, not the notebook line")
    func createRowShowsReasonInsteadOfNotebook() {
        // The row replaces the notebook line with the reason; both exist as copy.
        let notebook = AddLinkCreateCopy.notebookLine(notebookName: "Reading", language: .english)
        let reason = AddLinkConnectivity.offline.createDisabledReason
        #expect(reason != nil)
        #expect(reason != notebook)
    }
}
