//
//  DetailRouter.swift
//  Books & Vocab
//
//  統一 detail 呈現路由 — compact sheet vs regular inspector
//

import SwiftUI

@MainActor
protocol DetailRouting: AnyObject, Observable {
    var selectedEntry: VocabularyEntry? { get set }
    var activeReviewSession: TodayReviewSession? { get set }
    var contextEntries: [VocabularyEntry] { get set }
    var hasDetail: Bool { get }

    func showWordDetail(_ entry: VocabularyEntry, allEntries: [VocabularyEntry])
    func showReview(_ session: TodayReviewSession, allEntries: [VocabularyEntry])
    func dismiss()
}

// MARK: - Concrete Implementation

@Observable @MainActor
final class DetailRouter: DetailRouting {
    var selectedEntry: VocabularyEntry?
    var activeReviewSession: TodayReviewSession?
    var contextEntries: [VocabularyEntry] = []

    var hasDetail: Bool { selectedEntry != nil || activeReviewSession != nil }

    func showWordDetail(_ entry: VocabularyEntry, allEntries: [VocabularyEntry]) {
        activeReviewSession = nil
        selectedEntry = entry
        contextEntries = allEntries
    }

    func showReview(_ session: TodayReviewSession, allEntries: [VocabularyEntry]) {
        selectedEntry = nil
        activeReviewSession = session
        contextEntries = allEntries
    }

    func dismiss() {
        selectedEntry = nil
        activeReviewSession = nil
        contextEntries = []
    }
}

// MARK: - Environment Key

private struct DetailRouterKey: EnvironmentKey {
    static let defaultValue: (any DetailRouting)? = nil
}

extension EnvironmentValues {
    var detailRouter: (any DetailRouting)? {
        get { self[DetailRouterKey.self] }
        set { self[DetailRouterKey.self] = newValue }
    }
}
