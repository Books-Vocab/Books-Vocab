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
}

struct ReviewCardRenderPlan: Equatable {
    struct Face: Equatable {
        let fields: [ReviewCardField]
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
        return Self(
            coreIsLocked: true,
            front: .init(fields: layout.front.filter(availability.contains)),
            back: .init(fields: layout.back.filter(availability.contains))
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
