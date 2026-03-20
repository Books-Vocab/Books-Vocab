import Foundation
import SwiftData

enum DemoDataProvider {
    static let demoBookTitle = "The Weight of Words"

    static func injectDemoEntries(into container: ModelContainer) {
        let context = ModelContext(container)
        for spec in Self.specs {
            let entry = VocabularyEntry(
                word: spec.word,
                translation: spec.translation,
                context: spec.context,
                explanation: spec.explanation,
                partOfSpeech: spec.pos,
                bookTitle: demoBookTitle,
                chapterTitle: spec.chapter
            )
            entry.isDemoEntry = true
            entry.kgCardId = spec.cardId
            entry.difficultyTier = spec.tier
            entry.syncStatus = 1          // synced
            entry.actionType = "add"
            entry.reviewExamples = spec.examples
            entry.reviewIntervalHours = spec.intervalHours
            entry.nextReviewAt = Date().addingTimeInterval(spec.nextReviewOffsetHours * 3600)
            entry.reviewCount = spec.reviewCount
            entry.reviewStreak = spec.streak
            entry.lastReviewFeedbackRaw = spec.lastFeedback
            if spec.reviewCount > 0 {
                entry.lastReviewedAt = Date().addingTimeInterval(-24 * 3600)
            }

            // Graph links
            if let links = spec.links {
                entry.graphLinksByKind = links
            }

            context.insert(entry)
        }
        try? context.save()
    }

    static func removeDemoEntries(from container: ModelContainer) {
        let context = ModelContext(container)
        let predicate = #Predicate<VocabularyEntry> { $0.isDemoEntry == true }
        if let entries = try? context.fetch(FetchDescriptor(predicate: predicate)) {
            for entry in entries { context.delete(entry) }
            try? context.save()
        }
    }

    /// Demo graph links for KnowledgeGraphCoordinator
    static var demoGraphLinks: [KGGraphLink] {
        linkSpecs.map {
            KGGraphLink(
                id: $0.id,
                fromId: $0.from,
                toId: $0.to,
                kind: $0.kind,
                confidence: $0.confidence,
                reason: $0.reason
            )
        }
    }
}

// MARK: - Spec Types

private extension DemoDataProvider {
    struct EntrySpec {
        let word: String
        let cardId: String
        let translation: String
        let context: String
        let explanation: String
        let pos: String
        let chapter: String
        let tier: String
        let examples: [String]
        let intervalHours: Double
        let nextReviewOffsetHours: Double  // negative = due
        let reviewCount: Int
        let streak: Int
        let lastFeedback: Int              // -1=none, 0=forgot, 1=remembered
        let links: [String: [KGCardLinkSummary]]?
    }

    struct LinkSpec {
        let id: String
        let from: String
        let to: String
        let kind: String
        let confidence: Double
        let reason: String
    }

    // MARK: - Card ID Lookup

    static func cardId(for key: String) -> String {
        guard let id = ids[key] else {
            assertionFailure("DemoDataProvider: missing card ID for '\(key)'")
            return "demo-unknown-\(key)"
        }
        return id
    }

    // MARK: - Card IDs

    static let ids: [String: String] = [
        "affect": "demo-affect",
        "effect": "demo-effect",
        "complement": "demo-complement",
        "compliment": "demo-compliment",
        "imply": "demo-imply",
        "infer": "demo-infer",
        "elicit": "demo-elicit",
        "illicit": "demo-illicit",
        "precede": "demo-precede",
        "proceed": "demo-proceed",
        "ambiguous": "demo-ambiguous",
        "ubiquitous": "demo-ubiquitous",
        "ephemeral": "demo-ephemeral",
        "eloquent": "demo-eloquent",
        "resilient": "demo-resilient",
    ]

    // MARK: - Entry Specs

    static let specs: [EntrySpec] = [
        // ── Confusable pair: affect / effect ──
        EntrySpec(
            word: "affect",
            cardId: cardId(for: "affect"),
            translation: "影響（動詞）",
            context: "The new policy will significantly affect employee morale across the company.",
            explanation: "作為動詞，affect 表示「對⋯產生影響」。注意與名詞 effect（效果）的區別。",
            pos: "verb",
            chapter: "Chapter 3: Workplace Dynamics",
            tier: "core",
            examples: [
                "How does sleep deprivation affect cognitive performance?",
                "The drought severely affected crop yields this season."
            ],
            intervalHours: 48, nextReviewOffsetHours: -2, reviewCount: 3, streak: 2, lastFeedback: 1,
            links: [
                "shares_usage": [
                    KGCardLinkSummary(id: "l-ae-1", cardId: cardId(for: "effect"), word: "effect", kind: "shares_usage", label: "相關", confidence: 0.95, reason: "affect (v.) vs effect (n.) — 拼寫相近但詞性不同")
                ]
            ]
        ),
        EntrySpec(
            word: "effect",
            cardId: cardId(for: "effect"),
            translation: "效果；影響（名詞）；實施（動詞）",
            context: "The effect of the medication was almost immediate.",
            explanation: "最常見用法是名詞「效果、影響」。少見動詞用法意為「實施、促成」(effect change)。",
            pos: "noun",
            chapter: "Chapter 5: Health & Medicine",
            tier: "core",
            examples: [
                "The side effects of this drug are minimal.",
                "The new CEO effected sweeping changes in corporate culture."
            ],
            intervalHours: 72, nextReviewOffsetHours: 12, reviewCount: 4, streak: 3, lastFeedback: 1,
            links: [
                "shares_usage": [
                    KGCardLinkSummary(id: "l-ea-1", cardId: cardId(for: "affect"), word: "affect", kind: "shares_usage", label: "相關", confidence: 0.95, reason: "effect (n.) vs affect (v.) — 拼寫相近但詞性不同")
                ]
            ]
        ),

        // ── Confusable pair: complement / compliment ──
        EntrySpec(
            word: "complement",
            cardId: cardId(for: "complement"),
            translation: "補充；補足物",
            context: "The wine was chosen to complement the flavors of the main course.",
            explanation: "complement 強調「互補、使完整」。與 compliment（讚美）拼寫僅差一個字母。",
            pos: "verb",
            chapter: "Chapter 7: Culinary Arts",
            tier: "intermediate",
            examples: [
                "Her skills complement his perfectly — together they make a great team.",
                "The scarf complements the outfit nicely."
            ],
            intervalHours: 24, nextReviewOffsetHours: -6, reviewCount: 2, streak: 1, lastFeedback: 1,
            links: [
                "shares_usage": [
                    KGCardLinkSummary(id: "l-cc-1", cardId: cardId(for: "compliment"), word: "compliment", kind: "shares_usage", label: "相關", confidence: 0.92, reason: "complement（補充）vs compliment（讚美）— 一字之差")
                ]
            ]
        ),
        EntrySpec(
            word: "compliment",
            cardId: cardId(for: "compliment"),
            translation: "讚美；恭維",
            context: "She received a genuine compliment on her presentation skills.",
            explanation: "compliment 是「讚美、恭維」。記法：compliment 裡有 'i'，I like to give compliments。",
            pos: "noun",
            chapter: "Chapter 2: Social Interactions",
            tier: "intermediate",
            examples: [
                "He complimented her on the thorough research.",
                "Take it as a compliment — they clearly respect your work."
            ],
            intervalHours: 12, nextReviewOffsetHours: -1, reviewCount: 1, streak: 0, lastFeedback: 0,
            links: [
                "shares_usage": [
                    KGCardLinkSummary(id: "l-cc-2", cardId: cardId(for: "complement"), word: "complement", kind: "shares_usage", label: "相關", confidence: 0.92, reason: "compliment（讚美）vs complement（補充）— 一字之差")
                ]
            ]
        ),

        // ── Confusable pair: imply / infer ──
        EntrySpec(
            word: "imply",
            cardId: cardId(for: "imply"),
            translation: "暗示；意味著",
            context: "Are you trying to imply that I'm not qualified for this role?",
            explanation: "imply 是說話者「暗示」某事，方向是從說者到聽者。與 infer（推斷）相對。",
            pos: "verb",
            chapter: "Chapter 4: Communication",
            tier: "intermediate",
            examples: [
                "The report implies a strong correlation between diet and longevity.",
                "I didn't mean to imply that you were wrong."
            ],
            intervalHours: 36, nextReviewOffsetHours: -8, reviewCount: 2, streak: 2, lastFeedback: 1,
            links: [
                "shares_usage": [
                    KGCardLinkSummary(id: "l-ii-1", cardId: cardId(for: "infer"), word: "infer", kind: "shares_usage", label: "相關", confidence: 0.90, reason: "imply（說者暗示）vs infer（聽者推斷）— 方向相反")
                ]
            ]
        ),
        EntrySpec(
            word: "infer",
            cardId: cardId(for: "infer"),
            translation: "推斷；推論",
            context: "From the data, we can infer that the trend will continue upward.",
            explanation: "infer 是聽者/讀者「推斷」出的結論。Speaker implies, listener infers。",
            pos: "verb",
            chapter: "Chapter 6: Research Methods",
            tier: "intermediate",
            examples: [
                "What can we infer from the survey results?",
                "She inferred from his silence that he disagreed."
            ],
            intervalHours: 36, nextReviewOffsetHours: 2, reviewCount: 3, streak: 1, lastFeedback: 1,
            links: [
                "shares_usage": [
                    KGCardLinkSummary(id: "l-ii-2", cardId: cardId(for: "imply"), word: "imply", kind: "shares_usage", label: "相關", confidence: 0.90, reason: "infer（聽者推斷）vs imply（說者暗示）— 方向相反")
                ]
            ]
        ),

        // ── Confusable pair: elicit / illicit ──
        EntrySpec(
            word: "elicit",
            cardId: cardId(for: "elicit"),
            translation: "引出；引起",
            context: "The comedian's joke elicited roars of laughter from the audience.",
            explanation: "elicit 是動詞，意為「引出（反應、資訊）」。注意與 illicit（非法的）的區別。",
            pos: "verb",
            chapter: "Chapter 8: Public Speaking",
            tier: "advanced",
            examples: [
                "The interview was designed to elicit honest responses.",
                "Her speech elicited a standing ovation."
            ],
            intervalHours: 12, nextReviewOffsetHours: -3, reviewCount: 1, streak: 0, lastFeedback: 0,
            links: [
                "shares_usage": [
                    KGCardLinkSummary(id: "l-ei-1", cardId: cardId(for: "illicit"), word: "illicit", kind: "shares_usage", label: "相關", confidence: 0.88, reason: "elicit（引出，動詞）vs illicit（非法的，形容詞）")
                ]
            ]
        ),
        EntrySpec(
            word: "illicit",
            cardId: cardId(for: "illicit"),
            translation: "非法的；違禁的",
            context: "The investigation uncovered an illicit trade network spanning three countries.",
            explanation: "illicit 是形容詞，表示「非法的、不正當的」。與 elicit（引出）發音相近但意思完全不同。",
            pos: "adjective",
            chapter: "Chapter 10: Law & Ethics",
            tier: "advanced",
            examples: [
                "Illicit substances were found during the raid.",
                "The company engaged in illicit financial practices."
            ],
            intervalHours: 12, nextReviewOffsetHours: -5, reviewCount: 0, streak: 0, lastFeedback: -1,
            links: [
                "shares_usage": [
                    KGCardLinkSummary(id: "l-ei-2", cardId: cardId(for: "elicit"), word: "elicit", kind: "shares_usage", label: "相關", confidence: 0.88, reason: "illicit（非法的，形容詞）vs elicit（引出，動詞）")
                ]
            ]
        ),

        // ── Confusable pair: precede / proceed ──
        EntrySpec(
            word: "precede",
            cardId: cardId(for: "precede"),
            translation: "在⋯之前；先於",
            context: "A brief introduction will precede the keynote speech.",
            explanation: "precede = pre（前）+ cede（走）→「走在前面」。注意與 proceed（繼續進行）區分。",
            pos: "verb",
            chapter: "Chapter 1: Conference Planning",
            tier: "intermediate",
            examples: [
                "The appetizer course precedes the main dish.",
                "Thunder is usually preceded by lightning."
            ],
            intervalHours: 48, nextReviewOffsetHours: 24, reviewCount: 3, streak: 3, lastFeedback: 1,
            links: [
                "shares_usage": [
                    KGCardLinkSummary(id: "l-pp-1", cardId: cardId(for: "proceed"), word: "proceed", kind: "shares_usage", label: "相關", confidence: 0.85, reason: "precede（先於）vs proceed（繼續）— 字根不同但拼寫相近")
                ]
            ]
        ),
        EntrySpec(
            word: "proceed",
            cardId: cardId(for: "proceed"),
            translation: "繼續進行；著手",
            context: "After the safety briefing, passengers may proceed to the boarding gate.",
            explanation: "proceed = pro（向前）+ ceed（走）→「向前走、繼續」。名詞形式 procedure / proceedings。",
            pos: "verb",
            chapter: "Chapter 1: Conference Planning",
            tier: "core",
            examples: [
                "Let's proceed with the next item on the agenda.",
                "The construction will proceed as planned."
            ],
            intervalHours: 96, nextReviewOffsetHours: 48, reviewCount: 5, streak: 4, lastFeedback: 1,
            links: [
                "shares_usage": [
                    KGCardLinkSummary(id: "l-pp-2", cardId: cardId(for: "precede"), word: "precede", kind: "shares_usage", label: "相關", confidence: 0.85, reason: "proceed（繼續）vs precede（先於）— 字根不同但拼寫相近")
                ]
            ]
        ),

        // ── Standalone words ──
        EntrySpec(
            word: "ambiguous",
            cardId: cardId(for: "ambiguous"),
            translation: "模稜兩可的；含糊的",
            context: "The contract language was deliberately ambiguous, leaving room for interpretation.",
            explanation: "ambi-（兩邊）+ -iguous → 可以往兩邊解讀的，即「模稜兩可」。",
            pos: "adjective",
            chapter: "Chapter 9: Legal Writing",
            tier: "intermediate",
            examples: [
                "His response was ambiguous — I couldn't tell if he agreed.",
                "Avoid ambiguous pronouns in academic writing."
            ],
            intervalHours: 24, nextReviewOffsetHours: -4, reviewCount: 2, streak: 1, lastFeedback: 1,
            links: nil
        ),
        EntrySpec(
            word: "ubiquitous",
            cardId: cardId(for: "ubiquitous"),
            translation: "無處不在的；普遍存在的",
            context: "Smartphones have become ubiquitous in modern society.",
            explanation: "ubique（拉丁文：到處）→ ubiquitous「無所不在的」。形容極度普遍的事物。",
            pos: "adjective",
            chapter: "Chapter 11: Technology & Society",
            tier: "advanced",
            examples: [
                "Coffee shops are ubiquitous in this neighborhood.",
                "The ubiquitous nature of social media has transformed communication."
            ],
            intervalHours: 12, nextReviewOffsetHours: -1, reviewCount: 1, streak: 1, lastFeedback: 1,
            links: nil
        ),
        EntrySpec(
            word: "ephemeral",
            cardId: cardId(for: "ephemeral"),
            translation: "短暫的；轉瞬即逝的",
            context: "Fame on social media is often ephemeral, lasting only a few days.",
            explanation: "epi-（在⋯之上）+ hemera（一天）→ 只存在一天的 → 「短暫的」。常用於文學與哲學語境。",
            pos: "adjective",
            chapter: "Chapter 12: Philosophy of Time",
            tier: "advanced",
            examples: [
                "The beauty of cherry blossoms is ephemeral.",
                "Most internet trends are ephemeral by nature."
            ],
            intervalHours: 12, nextReviewOffsetHours: -10, reviewCount: 0, streak: 0, lastFeedback: -1,
            links: nil
        ),
        EntrySpec(
            word: "eloquent",
            cardId: cardId(for: "eloquent"),
            translation: "雄辯的；有口才的",
            context: "She delivered an eloquent speech that moved the entire audience to tears.",
            explanation: "e-（出）+ loqui（說）→ 說得出色的 → 「雄辯的、有說服力的」。",
            pos: "adjective",
            chapter: "Chapter 8: Public Speaking",
            tier: "intermediate",
            examples: [
                "His eloquent writing style earned him the literary prize.",
                "Even her silence was eloquent — it said everything."
            ],
            intervalHours: 36, nextReviewOffsetHours: -2, reviewCount: 2, streak: 2, lastFeedback: 1,
            links: nil
        ),
        EntrySpec(
            word: "resilient",
            cardId: cardId(for: "resilient"),
            translation: "有韌性的；能迅速恢復的",
            context: "Children are remarkably resilient and can adapt to new environments quickly.",
            explanation: "re-（回）+ silire（跳）→ 能彈回來的 → 「有韌性的、適應力強的」。",
            pos: "adjective",
            chapter: "Chapter 13: Psychology",
            tier: "core",
            examples: [
                "The economy proved resilient despite global uncertainties.",
                "Building a resilient team requires trust and communication."
            ],
            intervalHours: 48, nextReviewOffsetHours: 6, reviewCount: 3, streak: 2, lastFeedback: 1,
            links: nil
        ),
    ]

    // MARK: - Graph Link Specs

    static let linkSpecs: [LinkSpec] = [
        // affect ↔ effect
        LinkSpec(id: "gl-1", from: cardId(for: "affect"), to: cardId(for: "effect"), kind: "shares_usage", confidence: 0.95, reason: "affect (v.) vs effect (n.)"),
        // complement ↔ compliment
        LinkSpec(id: "gl-2", from: cardId(for: "complement"), to: cardId(for: "compliment"), kind: "shares_usage", confidence: 0.92, reason: "complement vs compliment"),
        // imply ↔ infer
        LinkSpec(id: "gl-3", from: cardId(for: "imply"), to: cardId(for: "infer"), kind: "shares_usage", confidence: 0.90, reason: "imply vs infer"),
        // elicit ↔ illicit
        LinkSpec(id: "gl-4", from: cardId(for: "elicit"), to: cardId(for: "illicit"), kind: "shares_usage", confidence: 0.88, reason: "elicit vs illicit"),
        // precede ↔ proceed
        LinkSpec(id: "gl-5", from: cardId(for: "precede"), to: cardId(for: "proceed"), kind: "shares_usage", confidence: 0.85, reason: "precede vs proceed"),
        // eloquent → elicit (derivational proximity)
        LinkSpec(id: "gl-6", from: cardId(for: "eloquent"), to: cardId(for: "elicit"), kind: "related", confidence: 0.60, reason: "Both from Latin loqui/lacere roots"),
        // ephemeral → resilient (antonym-ish)
        LinkSpec(id: "gl-7", from: cardId(for: "ephemeral"), to: cardId(for: "resilient"), kind: "related", confidence: 0.50, reason: "Conceptual contrast: fleeting vs enduring"),
    ]
}
