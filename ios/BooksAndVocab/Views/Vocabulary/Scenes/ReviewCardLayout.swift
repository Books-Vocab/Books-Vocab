import Foundation

enum ReviewCardFace: Hashable { case front, back }

struct ReviewCardMeasurementKey: Hashable {
    let cardKey: String
    let face: ReviewCardFace
    let section: ReviewCardLayoutSolver.Section
    let widthBucket: Int
    let dynamicType: String
}

/// Available optional content is intentionally separate from the persisted profile:
/// a missing field is skipped for this render only and is never removed from a user's
/// preferred ordering.
struct ReviewCardContentAvailability: Equatable {
    var partOfSpeech: Bool
    var difficultyTier: Bool
    var example: Bool
    var explanation: Bool
    var collocations: Bool
    var graphLinks: Bool

    func contains(_ field: ReviewCardField) -> Bool {
        switch field {
        case .partOfSpeech: partOfSpeech
        case .difficultyTier: difficultyTier
        case .example: example
        case .explanation: explanation
        case .collocations: collocations
        case .graphLinks: graphLinks
        }
    }

    /// Availability of the review card's optional blocks.
    ///
    /// `graphLinks` is unconditionally available: with no links the section renders
    /// the add-link affordance, which is the ONLY way to create the first link from
    /// the review card. Filtering it out on an empty link set silently removes that
    /// entry point — the shipped card has always drawn one or the other.
    static func forReviewCard(
        partOfSpeech: String?,
        difficultyTier: String?,
        exampleCount: Int,
        explanationParagraphCount: Int,
        collocationCount: Int
    ) -> Self {
        Self(
            partOfSpeech: partOfSpeech?.isEmpty == false,
            difficultyTier: difficultyTier?.isEmpty == false,
            example: exampleCount > 0,
            explanation: explanationParagraphCount > 0,
            collocations: collocationCount > 0,
            graphLinks: true
        )
    }
}

/// The card region's vertical budget, derived once from the `GeometryReader`
/// height that wraps it.
///
/// The raw height is NOT the room a face has: the region pads itself
/// (`cardTopInset` / `cardBottomInset`), and while the front is showing the
/// reveal affordance holds a hard floor as a layout sibling BELOW the card. Every
/// consumer — the solver's `viewportHeight`, the face's scroll clamp, the back
/// face's remainder, and the expand zone's own `minHeight` — reads this one value,
/// so the budget the solver believes is the space the picture actually leaves.
struct ReviewCardViewport: Equatable {
    /// Raw `GeometryReader` height of the card region.
    let containerHeight: CGFloat

    init(containerHeight: CGFloat) {
        self.containerHeight = containerHeight
    }

    /// What is left after the card region's own outer insets.
    var contentHeight: CGFloat {
        max(
            containerHeight - TodayReviewMetrics.cardTopInset - TodayReviewMetrics.cardBottomInset,
            0
        )
    }

    /// What the reveal affordance holds below the card. The presenter feeds this
    /// same value to the zone's `minHeight`, so the reserve and the drawn floor are
    /// one number by construction.
    ///
    /// Capped at half the region: the zone is an affordance and the card is the
    /// content, so on a region too short for the 180pt floor (landscape, split
    /// view) the zone gives way rather than starving the card to nothing. On every
    /// normal portrait size the cap is inactive and the floor/ratio stands.
    var revealZoneReserve: CGFloat {
        let desired = max(
            containerHeight * TodayReviewMetrics.frontHeightRatio,
            TodayReviewMetrics.revealZoneMinHeight
        )
        return min(desired, contentHeight / 2)
    }

    /// What the front face may occupy. Deliberately constant across reveal stages:
    /// the zone collapses on reveal, but letting the budget grow there would
    /// re-solve the front layout in the middle of the flip.
    var frontHeight: CGFloat { max(contentHeight - revealZoneReserve, 0) }

    /// What the back face may occupy once the front fold has taken its measured
    /// share of the same content height.
    func backHeight(frontOccupied: CGFloat) -> CGFloat {
        ReviewCardLayoutSolver.remainingHeight(viewport: contentHeight, occupied: frontOccupied)
    }
}

struct ReviewCardRenderPlan: Equatable {
    enum Row: Equatable {
        case prompt
        case answer
        case answerDivider
        case field(ReviewCardField)
    }

    struct Face: Equatable {
        let fields: [ReviewCardField]
        let rows: [Row]
    }

    /// Prompt and answer are mode semantics, rather than optional profile fields.
    let coreIsLocked: Bool
    let front: Face
    let back: Face

    static func make(
        profile: ReviewCardLayoutProfile,
        mode: VocabularyCardMode,
        availability: ReviewCardContentAvailability
    ) -> Self {
        let layout = profile.layout(for: mode)
        let frontFields = layout.front.filter(availability.contains)
        let backFields = layout.back.filter(availability.contains)
        let backRows: [Row] = [.answer]
            + (ReviewCardLayoutSolver.drawsAnswerDivider(fields: backFields) ? [.answerDivider] : [])
            + backFields.map(Row.field)
        return Self(
            coreIsLocked: true,
            front: .init(fields: frontFields, rows: [.prompt] + frontFields.map(Row.field)),
            back: .init(fields: backFields, rows: backRows)
        )
    }
}

/// The card's own chrome, owned once. `verticalInset` is what the solver subtracts
/// from the viewport and, by construction, the sum of what the face renderer pads —
/// a face can only gain an inset by changing it here, which moves the drawn padding
/// and the solver's budget in the same edit.
enum ReviewCardChrome {
    /// Uniform padding every face draws around its content.
    static var padding: CGFloat { TodayReviewMetrics.foldPadding }

    /// Space a face reserves above its content on top of `padding`. The front holds
    /// room for the fold hint; the back sits directly under the fold seam.
    static func extraTopInset(for face: ReviewCardFace) -> CGFloat {
        switch face {
        case .front: TodayReviewMetrics.foldHintBottomInset
        case .back: 0
        }
    }

    /// Total vertical space the chrome takes on a face.
    static func verticalInset(for face: ReviewCardFace) -> CGFloat {
        padding * 2 + extraTopInset(for: face)
    }
}

/// Cloze 只在「這一面還沒給答案」時成立，也就是 production 的題目面。
/// 其餘三種 (face, cardMode) 組合上目標詞本來就已經露出，挖空藏不住任何東西，
/// 只會把讀者該看到的高亮拿掉（重構前背面走 CardDocumentView，預設就是 .highlight）。
enum ReviewCardExampleRendering {
    static func mode(face: ReviewCardFace, cardMode: VocabularyCardMode) -> CardRichTextMode {
        face == .front && cardMode == .production ? .cloze : .highlight
    }
}

enum ReviewCardExplanationContent {
    static func rawMarkdown(from paragraphs: [CardDocumentParagraph]) -> String {
        paragraphs.map(\.rawMarkdown).joined(separator: "\n")
    }
}

/// A value-only solver for the active card face. View code supplies its natural and
/// compact measurements; no state is retained and each section is visited at most once.
enum ReviewCardLayoutSolver {
    enum Section: Hashable {
        case core
        case field(ReviewCardField)

        static let example = Self.field(.example)
        static let explanation = Self.field(.explanation)
        static let collocations = Self.field(.collocations)
        static let graphLinks = Self.field(.graphLinks)
    }

    struct Measurement: Equatable {
        let naturalHeight: CGFloat
        let intermediateHeight: CGFloat
        let compactHeight: CGFloat

        init(
            naturalHeight: CGFloat,
            intermediateHeight: CGFloat? = nil,
            compactHeight: CGFloat? = nil
        ) {
            self.naturalHeight = naturalHeight
            self.intermediateHeight = intermediateHeight ?? compactHeight ?? naturalHeight
            self.compactHeight = compactHeight ?? naturalHeight
        }
    }

    struct Input {
        let fields: [ReviewCardField]
        let measurements: [Section: Measurement]
        let viewportHeight: CGFloat
        let chromeHeight: CGFloat
        let minimumHeight: CGFloat
        let sectionSpacing: CGFloat
        let compactSectionSpacing: CGFloat
    }

    enum GraphLinkPresentation: Equatable { case twoPerGroup, onePerGroup, summary }
    enum MeasurementLevel: CaseIterable, Hashable { case natural, intermediate, compact }

    struct Policy: Equatable {
        var height: CGFloat
        var exampleRadius: Int?
        var lineLimit: Int?
        var graphLinkPresentation: GraphLinkPresentation?
        var summarizesOverflow = false

        var isVisible: Bool { height > 0 }
        var measurementLevel: MeasurementLevel {
            if lineLimit == 2 || graphLinkPresentation == .onePerGroup { return .intermediate }
            if exampleRadius != nil
                || lineLimit == 1
                || graphLinkPresentation == .summary
                || summarizesOverflow {
                return .compact
            }
            return .natural
        }

        static func measurementProbe(for field: ReviewCardField, level: MeasurementLevel) -> Self {
            var policy = Self(
                height: 0,
                exampleRadius: nil,
                lineLimit: nil,
                graphLinkPresentation: field == .graphLinks ? .twoPerGroup : nil
            )
            switch level {
            case .natural:
                break
            case .intermediate:
                if field == .explanation { policy.lineLimit = 2 }
                if field == .collocations { policy.lineLimit = 2 }
                if field == .graphLinks { policy.graphLinkPresentation = .onePerGroup }
            case .compact:
                if field == .example { policy.exampleRadius = 3 }
                if field == .explanation || field == .collocations { policy.lineLimit = 1 }
                if field == .collocations || field == .graphLinks { policy.summarizesOverflow = true }
                if field == .graphLinks { policy.graphLinkPresentation = .summary }
            }
            return policy
        }
    }

    struct Result: Equatable {
        let policies: [Section: Policy]
        let cardHeight: CGFloat
        /// The gap the solver actually charged between sections. The renderer draws
        /// this value instead of re-deriving one from tokens, so `cardHeight` and the
        /// picture can never be computed from different spacings.
        let sectionSpacing: CGFloat
        let usesCompactSpacing: Bool
        let requiresScrollFallback: Bool

        func policy(for section: Section) -> Policy {
            policies[section] ?? .init(height: 0)
        }
    }

    static func solve(_ input: Input) -> Result {
        let activeSections = [Section.core] + input.fields.map(Section.field)
        var policies = Dictionary(uniqueKeysWithValues: activeSections.map { section in
            let measurement = input.measurements[section] ?? .init(naturalHeight: 0)
            let policy = Policy(
                height: measurement.naturalHeight,
                exampleRadius: section == .example ? nil : nil,
                lineLimit: nil,
                graphLinkPresentation: section == .graphLinks ? .twoPerGroup : nil
            )
            return (section, policy)
        })

        let available = max(0, input.viewportHeight - input.chromeHeight)
        let minimum = input.minimumHeight
        var compactSpacing = false

        /// The gap in force right now. Read by both the running total and the result,
        /// so the spacing the renderer draws is the spacing the budget was charged.
        func currentSpacing() -> CGFloat {
            sectionSpacing(
                usesCompactSpacing: compactSpacing,
                natural: input.sectionSpacing,
                compact: input.compactSectionSpacing
            )
        }
        /// n sections carry n-1 gaps, so dropping to compact spacing frees
        /// `(natural - compact) * gapCount` — never a fixed amount.
        func totalHeight() -> CGFloat {
            let heights = activeSections.reduce(CGFloat(0)) { $0 + (policies[$1]?.height ?? 0) }
            return heights + CGFloat(max(activeSections.count - 1, 0)) * currentSpacing()
        }
        func compact(_ section: Section) {
            guard let measurement = input.measurements[section], var policy = policies[section] else { return }
            policy.height = min(policy.height, measurement.compactHeight)
            policies[section] = policy
        }
        func intermediate(_ section: Section) {
            guard let measurement = input.measurements[section], var policy = policies[section] else { return }
            policy.height = min(policy.height, measurement.intermediateHeight)
            policies[section] = policy
        }

        // Fixed priority: example → explanation → collocations → graph twice → padding.
        if totalHeight() > available, var policy = policies[.example] {
            policy.exampleRadius = 3
            policies[.example] = policy
            compact(.example)
        }
        if totalHeight() > available, var policy = policies[.explanation] {
            policy.lineLimit = 2
            policies[.explanation] = policy
            intermediate(.explanation)
        }
        if totalHeight() > available, var policy = policies[.explanation] {
            policy.lineLimit = 1
            policies[.explanation] = policy
            compact(.explanation)
        }
        if totalHeight() > available, var policy = policies[.collocations] {
            policy.lineLimit = 2
            policies[.collocations] = policy
            intermediate(.collocations)
        }
        if totalHeight() > available, var policy = policies[.collocations] {
            policy.lineLimit = 1
            policy.summarizesOverflow = true
            policies[.collocations] = policy
            compact(.collocations)
        }
        if totalHeight() > available, var policy = policies[.graphLinks] {
            policy.graphLinkPresentation = .onePerGroup
            policies[.graphLinks] = policy
            intermediate(.graphLinks)
        }
        if totalHeight() > available, var policy = policies[.graphLinks] {
            policy.graphLinkPresentation = .summary
            policy.summarizesOverflow = true
            policies[.graphLinks] = policy
            compact(.graphLinks)
        }
        if totalHeight() > available { compactSpacing = true }

        let contentHeight = totalHeight()
        return Result(
            policies: policies,
            cardHeight: max(minimum, min(contentHeight, available)),
            sectionSpacing: currentSpacing(),
            usesCompactSpacing: compactSpacing,
            requiresScrollFallback: contentHeight > available || minimum > available
        )
    }

    /// Three resident slots must not participate in active-shell measurement.
    static func activeShellHeight(heights: [CGFloat], activeIndex: Int?) -> CGFloat {
        guard let activeIndex, heights.indices.contains(activeIndex) else { return 0 }
        return heights[activeIndex]
    }

    static func remainingHeight(viewport: CGFloat, occupied: CGFloat) -> CGFloat {
        max(viewport - occupied, 0)
    }

    static func sectionSpacing(
        usesCompactSpacing: Bool,
        natural: CGFloat,
        compact: CGFloat
    ) -> CGFloat {
        usesCompactSpacing ? compact : natural
    }

    static func visibleCollocationLimit(lineLimit: Int?) -> Int? {
        lineLimit == 1 ? 1 : nil
    }

    // MARK: Natural-tier parity with the shipped card
    //
    // The card that ships today draws the back document with `compact: true`:
    // meaning paragraphs clamped to 3 lines, collocations clamped to 2 rows, and an
    // example that expanded into whatever space was left. Those are this renderer's
    // NATURAL tier — not an already-compacted one — otherwise the untouched default
    // profile would start looser than the picture it is meant to reproduce and only
    // reach it after the ladder ran.

    /// Explanation lines at each tier. Natural is the shipped 3-line clamp.
    static func explanationLineLimit(policyLineLimit: Int?) -> Int {
        policyLineLimit ?? 3
    }

    /// Collocation rows at each tier. Natural is the shipped 2-row flow cap.
    static func collocationRowLimit(lineLimit: Int?) -> Int {
        lineLimit == 1 ? 1 : 2
    }

    /// Natural example truncation. The back face used to expand the sentence into
    /// the free space it measured; the solver owns that space now, so natural back =
    /// no truncation and the ladder clamps it. The front kept the static skin radius.
    static func naturalExampleRadius(for face: ReviewCardFace, staticRadius: Int) -> Int? {
        switch face {
        case .front: staticRadius
        case .back: nil
        }
    }

    /// The answer's section rule under the word — drawn only when a field follows it,
    /// exactly as the shipped card did (it never trailed the card with a bare line).
    static func drawsAnswerDivider(fields: [ReviewCardField]) -> Bool {
        !fields.isEmpty
    }

    static func missingMeasurementLevels(
        hasNatural: Bool,
        hasIntermediate: Bool,
        hasCompact: Bool
    ) -> [MeasurementLevel] {
        [
            hasNatural ? nil : .natural,
            hasIntermediate ? nil : .intermediate,
            hasCompact ? nil : .compact
        ].compactMap { $0 }
    }
}

extension ReviewCardLayoutSolver.Input {
    /// The renderer's entry point. Chrome and both spacing tiers are bound to the
    /// tokens the face actually draws (`ReviewCardChrome` / `TodayReviewMetrics`),
    /// so a call site cannot hand the solver a budget the picture never honours.
    /// The memberwise initialiser stays available to tests that want arbitrary
    /// geometry.
    init(
        face: ReviewCardFace,
        fields: [ReviewCardField],
        measurements: [ReviewCardLayoutSolver.Section: ReviewCardLayoutSolver.Measurement],
        viewportHeight: CGFloat,
        minimumHeight: CGFloat
    ) {
        self.init(
            fields: fields,
            measurements: measurements,
            viewportHeight: viewportHeight,
            chromeHeight: ReviewCardChrome.verticalInset(for: face),
            minimumHeight: minimumHeight,
            sectionSpacing: TodayReviewMetrics.foldSectionSpacing,
            compactSectionSpacing: TodayReviewMetrics.foldSectionSpacingCompact
        )
    }
}
