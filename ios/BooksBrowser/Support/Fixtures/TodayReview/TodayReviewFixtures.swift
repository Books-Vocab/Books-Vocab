import Foundation

enum TodayReviewFixtureID: String, CaseIterable {
    case front = "front"
    case back = "back"
    case completed = "completed"
    case autoplay = "autoplay"

    var key: FixtureKey {
        FixtureKey("today_review.\(rawValue)")
    }
}

struct TodayReviewCardSeed {
    struct LinkSeed {
        let id: String
        let cardId: String
        let word: String
        let kind: String
        let label: String
        let confidence: Double
        let reason: String
        let hidden: Bool
    }

    let word: String
    let translation: String
    let context: String
    let explanation: String?
    let partOfSpeech: String?
    let bookTitle: String
    let chapterTitle: String?
    let dateAdded: Date
    let difficultyTier: String?
    let reviewMode: VocabularyCardMode
    let reviewExamples: [String]
    let rootForm: String?
    let inflections: [String]
    let graphLinksByKind: [String: [LinkSeed]]
}

struct TodayReviewSessionSeed {
    let progressText: String
    let currentCard: TodayReviewCardSeed?
    let nextCard: TodayReviewCardSeed?
    let revealStage: TodayReviewRevealStage
    let canShuffle: Bool
    let canGoPrevious: Bool
    let canGoNext: Bool
    let remainingCount: Int
    let forgotCount: Int
    let rememberedCount: Int
    let rememberedFeedbackTrigger: Int
    let forgotFeedbackTrigger: Int
    let isAutoPlaying: Bool
    let isAutoPlayPaused: Bool
    let autoplayProgress: Double
    let autoplaySpeed: AutoplaySpeed
    let autoplaySoundEnabled: Bool
    let showFirstRunHint: Bool
}

struct TodayReviewFixtureRenderModel {
    let state: TodayReviewPresenterState
    let showFirstRunHint: Bool
}

enum TodayReviewFixtures {
    private static let sharedSurfaces: Set<FixtureSurface> = [.preview, .catalog, .snapshot]

    private static let registry = FixtureRegistry<TodayReviewSessionSeed>([
        FixtureRecipe(key: TodayReviewFixtureID.front.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            seed(revealStage: .front, showFirstRunHint: true, isAutoPlaying: false, isAutoPlayPaused: false)
        },
        FixtureRecipe(key: TodayReviewFixtureID.back.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            seed(revealStage: .back, showFirstRunHint: false, isAutoPlaying: false, isAutoPlayPaused: false)
        },
        FixtureRecipe(key: TodayReviewFixtureID.completed.key, surfaces: sharedSurfaces, tags: ["baseline"]) {
            .init(
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
                isAutoPlaying: false,
                isAutoPlayPaused: false,
                autoplayProgress: 1.0,
                autoplaySpeed: .normal,
                autoplaySoundEnabled: true,
                showFirstRunHint: false
            )
        },
        FixtureRecipe(key: TodayReviewFixtureID.autoplay.key, surfaces: sharedSurfaces, tags: ["autoplay"]) {
            seed(revealStage: .back, showFirstRunHint: false, isAutoPlaying: true, isAutoPlayPaused: false)
        },
    ])

    static func recipes(for surface: FixtureSurface) -> [FixtureRecipe<TodayReviewSessionSeed>] {
        registry.recipes(for: surface)
    }

    static func state(for fixtureID: TodayReviewFixtureID) -> TodayReviewPresenterState {
        renderModel(for: fixtureID).state
    }

    static func renderModel(for fixtureID: TodayReviewFixtureID) -> TodayReviewFixtureRenderModel {
        let seed = registry.recipe(for: fixtureID.key).build()
        return .init(
            state: TodayReviewFixtureAdapter.makeState(from: seed),
            showFirstRunHint: seed.showFirstRunHint
        )
    }

    private static func seed(
        revealStage: TodayReviewRevealStage,
        showFirstRunHint: Bool,
        isAutoPlaying: Bool,
        isAutoPlayPaused: Bool
    ) -> TodayReviewSessionSeed {
        .init(
            progressText: "3 / 12",
            currentCard: currentCardSeed,
            nextCard: nextCardSeed,
            revealStage: revealStage,
            canShuffle: true,
            canGoPrevious: true,
            canGoNext: true,
            remainingCount: 9,
            forgotCount: isAutoPlaying ? 0 : 1,
            rememberedCount: isAutoPlaying ? 0 : 2,
            rememberedFeedbackTrigger: 0,
            forgotFeedbackTrigger: 0,
            isAutoPlaying: isAutoPlaying,
            isAutoPlayPaused: isAutoPlayPaused,
            autoplayProgress: 0.25,
            autoplaySpeed: .normal,
            autoplaySoundEnabled: true,
            showFirstRunHint: showFirstRunHint
        )
    }

    private static let currentCardSeed = TodayReviewCardSeed(
        word: "meticulous",
        translation: "一絲不苟的；非常仔細的",
        context: "The editor was meticulous about every line break and caption.",
        explanation: "描述做事非常細心、注意細節，通常帶有正面稱讚意味。",
        partOfSpeech: "adj.",
        bookTitle: "Designing Interfaces",
        chapterTitle: "Writing Tone",
        dateAdded: Date(timeIntervalSince1970: 1_736_000_000),
        difficultyTier: "advanced",
        reviewMode: .recognition,
        reviewExamples: ["The editor was meticulous about every line break and caption."],
        rootForm: "meticulous",
        inflections: ["meticulously", "meticulousness"],
        graphLinksByKind: [
            "shares_usage": [
                .init(id: "link-1", cardId: "card-1", word: "precise", kind: "shares_usage", label: "相關", confidence: 0.82, reason: "都與精確相關", hidden: false),
                .init(id: "link-2", cardId: "card-2", word: "thorough", kind: "shares_usage", label: "相關", confidence: 0.79, reason: "都與仔細相關", hidden: false),
                .init(id: "link-3", cardId: "card-3", word: "scrupulous", kind: "shares_usage", label: "相關", confidence: 0.75, reason: "都與嚴謹相關", hidden: false),
            ]
        ]
    )

    private static let nextCardSeed = TodayReviewCardSeed(
        word: "ephemeral",
        translation: "短暫的；轉瞬即逝的",
        context: "Social media posts are ephemeral by nature.",
        explanation: "形容事物存在時間極短。",
        partOfSpeech: "adj.",
        bookTitle: "Designing Interfaces",
        chapterTitle: "Writing Tone",
        dateAdded: Date(timeIntervalSince1970: 1_736_001_000),
        difficultyTier: nil,
        reviewMode: .recognition,
        reviewExamples: [],
        rootForm: nil,
        inflections: [],
        graphLinksByKind: [:]
    )
}

private enum TodayReviewFixtureAdapter {
    static func makeState(from seed: TodayReviewSessionSeed) -> TodayReviewPresenterState {
        .init(
            progressText: seed.progressText,
            currentCard: seed.currentCard.map(makeCurrentCard(from:)),
            nextCard: seed.nextCard.map(makeCurrentCard(from:)),
            revealStage: seed.revealStage,
            canShuffle: seed.canShuffle,
            canGoPrevious: seed.canGoPrevious,
            canGoNext: seed.canGoNext,
            remainingCount: seed.remainingCount,
            forgotCount: seed.forgotCount,
            rememberedCount: seed.rememberedCount,
            rememberedFeedbackTrigger: seed.rememberedFeedbackTrigger,
            forgotFeedbackTrigger: seed.forgotFeedbackTrigger,
            isAutoPlaying: seed.isAutoPlaying,
            isAutoPlayPaused: seed.isAutoPlayPaused,
            autoplayProgress: seed.autoplayProgress,
            autoplaySpeed: seed.autoplaySpeed,
            autoplaySoundEnabled: seed.autoplaySoundEnabled
        )
    }

    private static func makeCurrentCard(from seed: TodayReviewCardSeed) -> TodayReviewPresenterState.CurrentCard {
        let entry = VocabularyEntry(
            word: seed.word,
            translation: seed.translation,
            context: seed.context,
            explanation: seed.explanation,
            partOfSpeech: seed.partOfSpeech,
            bookTitle: seed.bookTitle,
            chapterTitle: seed.chapterTitle
        )
        entry.dateAdded = seed.dateAdded
        entry.difficultyTier = seed.difficultyTier
        entry.reviewMode = seed.reviewMode
        entry.reviewExamples = seed.reviewExamples
        entry.syncState = .synced
        entry.rootForm = seed.rootForm
        entry.inflections = seed.inflections
        entry.graphLinksByKind = seed.graphLinksByKind.mapValues { links in
            links.map {
                KGCardLinkSummary(
                    id: $0.id,
                    cardId: $0.cardId,
                    word: $0.word,
                    kind: $0.kind,
                    label: $0.label,
                    confidence: $0.confidence,
                    reason: $0.reason,
                    hidden: $0.hidden
                )
            }
        }

        let card = entry.cardPresentation
        let linkGroups = card.linkGroups.map { fullGroup in
            let limitedItems = fullGroup.id == "shares_usage" ? Array(fullGroup.items.prefix(2)) : fullGroup.items
            return TodayReviewPresenterState.LinkGroup(
                id: fullGroup.id,
                label: fullGroup.label,
                items: limitedItems,
                overflowCount: max(0, fullGroup.items.count - limitedItems.count)
            )
        }
        let backDoc = card.document.reviewBackSubset()
        return .init(
            card: card,
            linkGroups: linkGroups,
            backDocument: backDoc,
            postExampleMetrics: .from(backDoc)
        )
    }
}
