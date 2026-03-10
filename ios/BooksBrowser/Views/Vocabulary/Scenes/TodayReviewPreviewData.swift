import SwiftUI

enum TodayReviewPresenterPreviewData {
    static let baseCard: CardPresentation = {
        let entry = VocabularyEntry(
            word: "meticulous",
            translation: "一絲不苟的；非常仔細的",
            context: "The editor was meticulous about every line break and caption.",
            explanation: "描述做事非常細心、注意細節，通常帶有正面稱讚意味。",
            partOfSpeech: "adj.",
            pronunciation: "məˈtɪkjələs",
            bookTitle: "Designing Interfaces",
            chapterTitle: "Writing Tone"
        )
        entry.dateAdded = Date(timeIntervalSince1970: 1_736_000_000)
        entry.difficultyTier = "advanced"
        entry.reviewMode = .recognition
        entry.reviewExamples = ["The editor was meticulous about every line break and caption."]
        entry.syncState = .synced
        entry.rootForm = "meticulous"
        entry.inflections = ["meticulously", "meticulousness"]
        entry.graphLinksByKind = [
            "confusable": [
                KGCardLinkSummary(id: "link-1", cardId: "card-1", word: "precise", kind: "confusable", label: "易混", confidence: 0.82, reason: "都與精確相關"),
                KGCardLinkSummary(id: "link-2", cardId: "card-2", word: "thorough", kind: "confusable", label: "易混", confidence: 0.79, reason: "都與仔細相關"),
                KGCardLinkSummary(id: "link-3", cardId: "card-3", word: "scrupulous", kind: "confusable", label: "易混", confidence: 0.75, reason: "都與嚴謹相關")
            ]
        ]
        return entry.cardPresentation
    }()

    static let currentCard = TodayReviewPresenterState.CurrentCard(
        card: baseCard,
        linkGroups: [
            .init(
                id: "confusable",
                label: "易混",
                items: [
                    .init(id: "link-1", cardId: "card-1", word: "precise", kind: "confusable", label: "易混", confidence: 0.82, reason: "都與精確相關"),
                    .init(id: "link-2", cardId: "card-2", word: "thorough", kind: "confusable", label: "易混", confidence: 0.79, reason: "都與仔細相關")
                ],
                overflowCount: 1
            )
        ]
    )

    static let nextCard = TodayReviewPresenterState.CurrentCard(
        card: {
            let entry = VocabularyEntry(
                word: "ephemeral",
                translation: "短暫的；轉瞬即逝的",
                context: "Social media posts are ephemeral by nature.",
                explanation: "形容事物存在時間極短。",
                partOfSpeech: "adj.",
                pronunciation: "ɪˈfemərəl",
                bookTitle: "Designing Interfaces",
                chapterTitle: "Writing Tone"
            )
            entry.dateAdded = Date(timeIntervalSince1970: 1_736_001_000)
            entry.reviewMode = .recognition
            return entry.cardPresentation
        }(),
        linkGroups: []
    )

    static func state(stage: TodayReviewRevealStage) -> TodayReviewPresenterState {
        .init(
            progressText: "3 / 12",
            currentCard: currentCard,
            nextCard: nextCard,
            revealStage: stage,
            canShuffle: true,
            canGoPrevious: true,
            canGoNext: true,
            remainingCount: 9,
            forgotCount: 1,
            rememberedCount: 2,
            rememberedFeedbackTrigger: 0,
            forgotFeedbackTrigger: 0,
            persistenceFailureTrigger: 0,
            persistenceErrorMessage: nil
        )
    }

    static let completedState = TodayReviewPresenterState(
        progressText: "12 / 12",
        currentCard: nil,
        nextCard: nil,
        revealStage: .front,
        canShuffle: false,
        canGoPrevious: false,
        canGoNext: false,
        remainingCount: 0,
        forgotCount: 4,
        rememberedCount: 8,
        rememberedFeedbackTrigger: 0,
        forgotFeedbackTrigger: 0,
        persistenceFailureTrigger: 0,
        persistenceErrorMessage: nil
    )

    static let noopCallbacks: (
        onClose: () -> Void,
        onAdvanceReveal: () -> Void,
        onCollapseReveal: () -> Void,
        onShuffle: () -> Void,
        onPrevious: () -> Void,
        onNext: () -> Void,
        onForgot: () -> Void,
        onRemembered: () -> Void,
        onLinkTap: (KGCardLinkSummary) -> Void
    ) = ({}, {}, {}, {}, {}, {}, {}, {}, { _ in })
}

#Preview("Today Review / Front") {
    let cb = TodayReviewPresenterPreviewData.noopCallbacks
    AppThemeContainer {
        TodayReviewPresenter(
            state: TodayReviewPresenterPreviewData.state(stage: .front),
            onClose: cb.onClose, onAdvanceReveal: cb.onAdvanceReveal, onCollapseReveal: cb.onCollapseReveal,
            onShuffle: cb.onShuffle, onPrevious: cb.onPrevious, onNext: cb.onNext,
            onForgot: cb.onForgot, onRemembered: cb.onRemembered, onLinkTap: cb.onLinkTap
        )
    }
}

#Preview("Today Review / Back") {
    let cb = TodayReviewPresenterPreviewData.noopCallbacks
    AppThemeContainer {
        TodayReviewPresenter(
            state: TodayReviewPresenterPreviewData.state(stage: .back),
            onClose: cb.onClose, onAdvanceReveal: cb.onAdvanceReveal, onCollapseReveal: cb.onCollapseReveal,
            onShuffle: cb.onShuffle, onPrevious: cb.onPrevious, onNext: cb.onNext,
            onForgot: cb.onForgot, onRemembered: cb.onRemembered, onLinkTap: cb.onLinkTap
        )
    }
}

#Preview("Today Review / Completed") {
    let cb = TodayReviewPresenterPreviewData.noopCallbacks
    AppThemeContainer {
        TodayReviewPresenter(
            state: TodayReviewPresenterPreviewData.completedState,
            onClose: cb.onClose, onAdvanceReveal: cb.onAdvanceReveal, onCollapseReveal: cb.onCollapseReveal,
            onShuffle: cb.onShuffle, onPrevious: cb.onPrevious, onNext: cb.onNext,
            onForgot: cb.onForgot, onRemembered: cb.onRemembered, onLinkTap: cb.onLinkTap
        )
    }
}
