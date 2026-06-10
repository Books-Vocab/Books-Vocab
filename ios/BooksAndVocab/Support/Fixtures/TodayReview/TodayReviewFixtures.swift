import Foundation

enum TodayReviewFixtureID: String, CaseIterable {
    case front = "front"
    case back = "back"
    case completed = "completed"
    case autoplay = "autoplay"
    case longContent = "longContent"

    var key: FixtureKey {
        FixtureKey("today_review.\(rawValue)")
    }
}

struct TodayReviewCardSeed: Codable {
    struct LinkSeed: Codable {
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

struct TodayReviewSessionSeed: Codable {
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
        // Stress: answer card whose context / explanation / examples overflow the
        // fixed answer-card height, plus a 5-link group to push the link strip past
        // its inline cap. Catalog/preview only — not part of the blessed snapshot set.
        FixtureRecipe(key: TodayReviewFixtureID.longContent.key, surfaces: [.preview, .catalog], tags: ["stress"]) {
            .init(
                progressText: "5 / 18",
                currentCard: longContentCardSeed,
                nextCard: nextCardSeed,
                revealStage: .back,
                canShuffle: true,
                canGoPrevious: true,
                canGoNext: true,
                remainingCount: 13,
                forgotCount: 1,
                rememberedCount: 4,
                rememberedFeedbackTrigger: 0,
                forgotFeedbackTrigger: 0,
                isAutoPlaying: false,
                isAutoPlayPaused: false,
                autoplayProgress: 0.25,
                autoplaySpeed: .normal,
                autoplaySoundEnabled: true,
                showFirstRunHint: false
            )
        },
    ])

    static func recipes(for surface: FixtureSurface) -> [FixtureRecipe<TodayReviewSessionSeed>] {
        registry.recipes(for: surface)
    }

    static func state(for fixtureID: TodayReviewFixtureID) -> TodayReviewPresenterState {
        renderModel(for: fixtureID).state
    }

    static func renderModel(for fixtureID: TodayReviewFixtureID) -> TodayReviewFixtureRenderModel {
        let seed = FixtureDatasetStore.todayReviewSeed(for: fixtureID)
            ?? registry.recipe(for: fixtureID.key).build()
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

    /// Deliberately oversized card: long literary context, multi-sentence
    /// explanation, several review examples and a 5-link group — exercises the
    /// answer-card overflow + link-strip `+N` cap in one frame.
    private static let longContentCardSeed = TodayReviewCardSeed(
        word: "serendipity",
        translation: "機緣巧合；意外發現美好事物的能力與運氣",
        context: "It was pure serendipity that, while searching the archive for an unrelated maritime "
            + "ledger, she stumbled upon the only surviving letter in which the composer described, in "
            + "his own trembling hand, the night the symphony's final movement first came to him.",
        explanation: "指在尋找某事物的過程中，意外發現了另一件同樣珍貴、甚至更有價值的事物的現象或才能。"
            + "這個詞帶有強烈的正面與浪漫色彩，常用於描述科學發現、人際相遇或藝術靈感的偶然降臨；"
            + "與單純的『運氣』不同，serendipity 隱含當事人具備察覺並把握偶然機會的敏銳度，"
            + "因此它既描述外在的巧合，也讚許內在的洞察力。",
        partOfSpeech: "n.",
        bookTitle: "The Travels and Adventures of Three Princes of Serendip",
        chapterTitle: "On Discoveries Neither Sought Nor Expected",
        dateAdded: Date(timeIntervalSince1970: 1_735_000_000),
        difficultyTier: "advanced",
        reviewMode: .recognition,
        reviewExamples: [
            "A series of serendipitous encounters led the two researchers to co-author the paper that "
                + "would eventually reshape the field.",
            "Finding that out-of-print edition in a roadside stall was a moment of genuine serendipity.",
            "Much of scientific progress depends on serendipity tempered by a prepared, observant mind.",
        ],
        rootForm: "serendipity",
        inflections: ["serendipitous", "serendipitously"],
        graphLinksByKind: [
            "shares_usage": [
                .init(id: "lc-1", cardId: "c-1", word: "fortuitous", kind: "shares_usage", label: "相關", confidence: 0.84, reason: "都描述偶然", hidden: false),
                .init(id: "lc-2", cardId: "c-2", word: "providence", kind: "shares_usage", label: "相關", confidence: 0.80, reason: "都帶命運色彩", hidden: false),
                .init(id: "lc-3", cardId: "c-3", word: "happenstance", kind: "shares_usage", label: "相關", confidence: 0.78, reason: "都指巧合", hidden: false),
                .init(id: "lc-4", cardId: "c-4", word: "windfall", kind: "shares_usage", label: "相關", confidence: 0.72, reason: "意外之得", hidden: false),
                .init(id: "lc-5", cardId: "c-5", word: "kismet", kind: "shares_usage", label: "相關", confidence: 0.69, reason: "命定的緣分", hidden: false),
            ]
        ]
    )
}

private enum TodayReviewFixtureAdapter {
    static func makeState(from seed: TodayReviewSessionSeed) -> TodayReviewPresenterState {
        let current = seed.currentCard.map(makeCurrentCard(from:))
        let next = seed.nextCard.map(makeCurrentCard(from:))
        // 靜態 fixture 不攜帶真實 queue index — slot 指派只消費 parity 與
        // 「下一張是否存在」，固定 currentIndex=0 渲染結果與真 session 等價。
        let queueCount = current == nil ? 0 : (next == nil ? 1 : 2)
        let slots = TodayReviewCardSlotModel.make(currentIndex: 0, queueCount: queueCount) { index in
            index == 0 ? current : next
        }
        return .init(
            progressText: seed.progressText,
            currentCard: current,
            slots: slots,
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
