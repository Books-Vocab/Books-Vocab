import Foundation

private struct AnyTodayReviewCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int?

    init?(stringValue: String) {
        self.stringValue = stringValue
        self.intValue = nil
    }

    init?(intValue: Int) {
        self.stringValue = "\(intValue)"
        self.intValue = intValue
    }
}

private func rejectUnknownTodayReviewKeys<Key>(
    from decoder: Decoder,
    knownKeys: Key.Type,
    context: String
) throws where Key: CodingKey & CaseIterable, Key.AllCases: Sequence {
    let rawContainer = try decoder.container(keyedBy: AnyTodayReviewCodingKey.self)
    let known = Set(Key.allCases.map(\.stringValue))
    let unknown = Set(rawContainer.allKeys.map(\.stringValue)).subtracting(known)
    guard unknown.isEmpty else {
        throw DecodingError.dataCorrupted(
            .init(
                codingPath: decoder.codingPath,
                debugDescription: "\(context) contains unknown keys \(unknown.sorted())"
            )
        )
    }
}

private func requireAllTodayReviewKeys<Key>(
    in container: KeyedDecodingContainer<Key>,
    context: String
) throws where Key: CodingKey & CaseIterable, Key.AllCases: Sequence {
    for key in Key.allCases where !container.contains(key) {
        throw DecodingError.keyNotFound(
            key,
            .init(
                codingPath: container.codingPath,
                debugDescription: "\(context) must explicitly declare \(key.stringValue), even when null"
            )
        )
    }
}

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

        enum CodingKeys: String, CodingKey, CaseIterable {
            case id
            case cardId
            case word
            case kind
            case label
            case confidence
            case reason
            case hidden
        }

        init(from decoder: Decoder) throws {
            try rejectUnknownTodayReviewKeys(from: decoder, knownKeys: CodingKeys.self, context: "UI World todayReview card link")
            let container = try decoder.container(keyedBy: CodingKeys.self)
            try requireAllTodayReviewKeys(in: container, context: "UI World todayReview card link")
            id = try container.decode(String.self, forKey: .id)
            cardId = try container.decode(String.self, forKey: .cardId)
            word = try container.decode(String.self, forKey: .word)
            kind = try container.decode(String.self, forKey: .kind)
            label = try container.decode(String.self, forKey: .label)
            confidence = try container.decode(Double.self, forKey: .confidence)
            reason = try container.decode(String.self, forKey: .reason)
            hidden = try container.decode(Bool.self, forKey: .hidden)
        }
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

    enum CodingKeys: String, CodingKey, CaseIterable {
        case word
        case translation
        case context
        case explanation
        case partOfSpeech
        case bookTitle
        case chapterTitle
        case dateAdded
        case difficultyTier
        case reviewMode
        case reviewExamples
        case rootForm
        case inflections
        case graphLinksByKind
    }

    init(from decoder: Decoder) throws {
        try rejectUnknownTodayReviewKeys(from: decoder, knownKeys: CodingKeys.self, context: "UI World todayReview card")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireAllTodayReviewKeys(in: container, context: "UI World todayReview card")
        word = try container.decode(String.self, forKey: .word)
        translation = try container.decode(String.self, forKey: .translation)
        context = try container.decode(String.self, forKey: .context)
        explanation = try container.decodeIfPresent(String.self, forKey: .explanation)
        partOfSpeech = try container.decodeIfPresent(String.self, forKey: .partOfSpeech)
        bookTitle = try container.decode(String.self, forKey: .bookTitle)
        chapterTitle = try container.decodeIfPresent(String.self, forKey: .chapterTitle)
        dateAdded = try container.decode(Date.self, forKey: .dateAdded)
        difficultyTier = try container.decodeIfPresent(String.self, forKey: .difficultyTier)
        reviewMode = try container.decode(VocabularyCardMode.self, forKey: .reviewMode)
        reviewExamples = try container.decode([String].self, forKey: .reviewExamples)
        rootForm = try container.decodeIfPresent(String.self, forKey: .rootForm)
        inflections = try container.decode([String].self, forKey: .inflections)
        graphLinksByKind = try container.decode([String: [LinkSeed]].self, forKey: .graphLinksByKind)
    }
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

    enum CodingKeys: String, CodingKey, CaseIterable {
        case progressText
        case currentCard
        case nextCard
        case revealStage
        case canShuffle
        case canGoPrevious
        case canGoNext
        case remainingCount
        case forgotCount
        case rememberedCount
        case rememberedFeedbackTrigger
        case forgotFeedbackTrigger
        case isAutoPlaying
        case isAutoPlayPaused
        case autoplayProgress
        case autoplaySpeed
        case autoplaySoundEnabled
        case showFirstRunHint
    }

    init(from decoder: Decoder) throws {
        try rejectUnknownTodayReviewKeys(from: decoder, knownKeys: CodingKeys.self, context: "UI World todayReview session")
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try requireAllTodayReviewKeys(in: container, context: "UI World todayReview session")
        progressText = try container.decode(String.self, forKey: .progressText)
        currentCard = try container.decodeIfPresent(TodayReviewCardSeed.self, forKey: .currentCard)
        nextCard = try container.decodeIfPresent(TodayReviewCardSeed.self, forKey: .nextCard)
        revealStage = try container.decode(TodayReviewRevealStage.self, forKey: .revealStage)
        canShuffle = try container.decode(Bool.self, forKey: .canShuffle)
        canGoPrevious = try container.decode(Bool.self, forKey: .canGoPrevious)
        canGoNext = try container.decode(Bool.self, forKey: .canGoNext)
        remainingCount = try container.decode(Int.self, forKey: .remainingCount)
        forgotCount = try container.decode(Int.self, forKey: .forgotCount)
        rememberedCount = try container.decode(Int.self, forKey: .rememberedCount)
        rememberedFeedbackTrigger = try container.decode(Int.self, forKey: .rememberedFeedbackTrigger)
        forgotFeedbackTrigger = try container.decode(Int.self, forKey: .forgotFeedbackTrigger)
        isAutoPlaying = try container.decode(Bool.self, forKey: .isAutoPlaying)
        isAutoPlayPaused = try container.decode(Bool.self, forKey: .isAutoPlayPaused)
        autoplayProgress = try container.decode(Double.self, forKey: .autoplayProgress)
        autoplaySpeed = try container.decode(AutoplaySpeed.self, forKey: .autoplaySpeed)
        autoplaySoundEnabled = try container.decode(Bool.self, forKey: .autoplaySoundEnabled)
        showFirstRunHint = try container.decode(Bool.self, forKey: .showFirstRunHint)
    }
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
            // 對齊 `TodayReviewSessionState.canAutoplay`：靜態 fixture 不表示
            // 已結束的 session，故只需「還能推進 or 還能翻面」這兩項。
            canAutoplay: seed.canGoNext || seed.revealStage == .front,
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
