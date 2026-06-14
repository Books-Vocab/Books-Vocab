import Foundation

enum TodayReviewFixtureID: String, CaseIterable {
    case front = "front"
    case back = "back"
    case completed = "completed"
    case autoplay = "autoplay"
    case autoplayPaused = "autoplayPaused"
    case productionFront = "productionFront"
    case productionBack = "productionBack"
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

    private static let registry = FixtureRegistry<TodayReviewSessionSeed>(
        TodayReviewFixtureID.allCases.map { fixtureID in
            FixtureRecipe(key: fixtureID.key, surfaces: surfaces(for: fixtureID), tags: tags(for: fixtureID)) {
                FixtureDatasetStore.requireTodayReviewSeed(for: fixtureID)
            }
        }
    )

    private static func surfaces(for fixtureID: TodayReviewFixtureID) -> Set<FixtureSurface> {
        switch fixtureID {
        case .longContent:
            return [.preview, .catalog]
        case .front, .back, .completed, .autoplay, .autoplayPaused, .productionFront, .productionBack:
            return sharedSurfaces
        }
    }

    private static func tags(for fixtureID: TodayReviewFixtureID) -> Set<String> {
        switch fixtureID {
        case .front, .back, .completed:
            return ["baseline"]
        case .autoplay, .autoplayPaused:
            return ["autoplay"]
        case .productionFront, .productionBack:
            return ["production"]
        case .longContent:
            return ["stress"]
        }
    }

    static func recipes(for surface: FixtureSurface) -> [FixtureRecipe<TodayReviewSessionSeed>] {
        registry.recipes(for: surface)
    }

    static func state(for fixtureID: TodayReviewFixtureID) -> TodayReviewPresenterState {
        renderModel(for: fixtureID).state
    }

    static func renderModel(for fixtureID: TodayReviewFixtureID) -> TodayReviewFixtureRenderModel {
        let seed = FixtureDatasetStore.requireTodayReviewSeed(for: fixtureID)
        return .init(
            state: TodayReviewFixtureAdapter.makeState(from: seed),
            showFirstRunHint: seed.showFirstRunHint
        )
    }

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
