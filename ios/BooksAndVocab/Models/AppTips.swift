//
//  AppTips.swift
//  Books & Vocab
//

import SwiftUI
import TipKit

// Why Text(verbatim:): bypass SwiftUI's automatic LocalizedStringKey lookup —
// the string from L10n.string(_:) is already resolved through our 3-tier
// fallback. Without `verbatim`, SwiftUI would attempt a second Bundle.main
// lookup on the resolved value, which can corrupt UI when the value happens
// to contain format specifiers or match an unrelated catalog key.
// DO NOT remove `verbatim`.

// MARK: - Long Press Word Lookup

struct LongPressTip: Tip {
    static let wordLookedUp = Event(id: "wordLookedUp")

    var title: Text { Text(verbatim: L10n.string("tip_long_press_title")) }
    var message: Text? { Text(verbatim: L10n.string("tip_long_press_message")) }
    var options: [TipOption] { [Tips.MaxDisplayCount(1)] }

    var rules: [Rule] {
        #Rule(Self.wordLookedUp) { $0.donations.count == 0 }
    }
}

// MARK: - Sync Pending Vocabulary

struct SyncPendingTip: Tip {
    static let syncCompleted = Event(id: "syncCompleted")

    var title: Text { Text(verbatim: L10n.string("tip_sync_vocab_title")) }
    var message: Text? { Text(verbatim: L10n.string("tip_sync_vocab_message")) }
    var options: [TipOption] { [Tips.MaxDisplayCount(1)] }

    var rules: [Rule] {
        #Rule(Self.syncCompleted) { $0.donations.count == 0 }
    }
}

// MARK: - EPUB Guide

struct EPUBGuideTip: Tip {
    /// Shared id so the action declaration and the TipView handler can't drift.
    static let guideActionID = "epub_guide_action"

    var title: Text { Text(verbatim: L10n.string("tip_epub_guide_title")) }
    var message: Text? { Text(verbatim: L10n.string("tip_epub_guide_message")) }
    var options: [TipOption] { [Tips.MaxDisplayCount(1)] }

    var actions: [Action] {
        [Action(id: Self.guideActionID, title: L10n.string("tip_epub_guide_action"))]
    }
}
