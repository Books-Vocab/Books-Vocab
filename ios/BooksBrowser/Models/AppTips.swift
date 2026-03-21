//
//  AppTips.swift
//  BooksBrowser
//

import SwiftUI
import TipKit

// MARK: - Long Press Word Lookup

struct LongPressTip: Tip {
    static let wordLookedUp = Event(id: "wordLookedUp")

    var title: Text { Text("長按查詞") }
    var message: Text? { Text("長按任何單字即可查詢 AI 翻譯與詞性解析") }
    var options: [TipOption] { [Tips.MaxDisplayCount(1)] }

    var rules: [Rule] {
        #Rule(Self.wordLookedUp) { $0.donations.count == 0 }
    }
}

// MARK: - Sync Pending Vocabulary

struct SyncPendingTip: Tip {
    static let syncCompleted = Event(id: "syncCompleted")

    var title: Text { Text("同步你的單字") }
    var message: Text? { Text("你有未同步的生詞，點擊同步按鈕推送到雲端") }
    var options: [TipOption] { [Tips.MaxDisplayCount(1)] }

    var rules: [Rule] {
        #Rule(Self.syncCompleted) { $0.donations.count == 0 }
    }
}

// MARK: - EPUB Guide

struct EPUBGuideTip: Tip {
    var title: Text { Text("哪裡找電子書？") }
    var message: Text? { Text("查看 EPUB 取得指南，了解如何取得免費或付費電子書") }
    var options: [TipOption] { [Tips.MaxDisplayCount(1)] }

    var actions: [Action] {
        [Action(id: "查看指南", title: "查看指南")]
    }
}
