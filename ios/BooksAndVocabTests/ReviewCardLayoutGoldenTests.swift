import Foundation
import Testing
@testable import BooksAndVocab

struct ReviewCardLayoutGoldenTests {
    private struct Golden: Codable, Equatable {
        struct Face: Codable, Equatable {
            let rows: [String]
        }

        struct Mode: Codable, Equatable {
            let front: Face
            let back: Face
        }

        struct NaturalFace: Codable, Equatable {
            let explanationLineLimit: Int
            let collocationRowLimit: Int
            let naturalExampleRadius: Int?
        }

        struct Divider: Codable, Equatable {
            let empty: Bool
            let withFields: Bool
        }

        struct NaturalTier: Codable, Equatable {
            let front: NaturalFace
            let back: NaturalFace
            let drawsAnswerDivider: Divider
        }

        struct Viewport: Codable, Equatable {
            let containerHeight: Double
            let contentHeight: Double
            let revealZoneReserve: Double
            let frontHeight: Double
        }

        let modes: [String: Mode]
        let naturalTier: NaturalTier
        let viewport: Viewport
    }

    private let allContent = ReviewCardContentAvailability(
        partOfSpeech: true,
        difficultyTier: true,
        example: true,
        explanation: true,
        collocations: true,
        graphLinks: true
    )

    private var goldenURL: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .appendingPathComponent("Golden/review_card_layout.json")
    }

    @Test func default_layout_matches_review_card_layout_golden() throws {
        let data = try Data(contentsOf: goldenURL)
        let expected = try JSONDecoder().decode(Golden.self, from: data)
        let actual = makeSnapshot()
        let expectedText = String(data: data, encoding: .utf8) ?? "<unreadable>"
        let actualText = String(
            data: try JSONEncoder().encode(actual),
            encoding: .utf8
        ) ?? "<unreadable>"

        #expect(
            actual == expected,
            "review_card_layout golden mismatch. If this is an intentional visual change, update the golden and explain it in the commit message.\nexpected=\(expectedText)\nactual=\(actualText)"
        )
    }

    private func makeSnapshot() -> Golden {
        let modes: [String: Golden.Mode] = [
            "recognition": modeSnapshot(.recognition),
            "production": modeSnapshot(.production)
        ]
        let naturalTier = Golden.NaturalTier(
            front: .init(
                explanationLineLimit: ReviewCardLayoutSolver.explanationLineLimit(policyLineLimit: nil),
                collocationRowLimit: ReviewCardLayoutSolver.collocationRowLimit(lineLimit: nil),
                naturalExampleRadius: ReviewCardLayoutSolver.naturalExampleRadius(for: .front, staticRadius: 5)
            ),
            back: .init(
                explanationLineLimit: ReviewCardLayoutSolver.explanationLineLimit(policyLineLimit: nil),
                collocationRowLimit: ReviewCardLayoutSolver.collocationRowLimit(lineLimit: nil),
                naturalExampleRadius: ReviewCardLayoutSolver.naturalExampleRadius(for: .back, staticRadius: 5)
            ),
            drawsAnswerDivider: .init(
                empty: ReviewCardLayoutSolver.drawsAnswerDivider(fields: []),
                withFields: ReviewCardLayoutSolver.drawsAnswerDivider(fields: [.difficultyTier])
            )
        )
        let viewport = ReviewCardViewport(containerHeight: 600)
        return Golden(
            modes: modes,
            naturalTier: naturalTier,
            viewport: .init(
                containerHeight: Double(viewport.containerHeight),
                contentHeight: Double(viewport.contentHeight),
                revealZoneReserve: Double(viewport.revealZoneReserve),
                frontHeight: Double(viewport.frontHeight)
            )
        )
    }

    private func modeSnapshot(_ mode: VocabularyCardMode) -> Golden.Mode {
        let plan = ReviewCardRenderPlan.make(
            profile: .default,
            mode: mode,
            availability: allContent
        )
        return .init(
            front: .init(rows: plan.front.rows.map(rowName)),
            back: .init(rows: plan.back.rows.map(rowName))
        )
    }

    private func rowName(_ row: ReviewCardRenderPlan.Row) -> String {
        switch row {
        case .prompt: "prompt"
        case .answer: "answer"
        case .answerDivider: "answerDivider"
        case .field(let field): "field.\(field.rawValue)"
        }
    }
}
