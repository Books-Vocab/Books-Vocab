#if DEBUG
import Playbook
import SwiftUI

/// Catalog scenarios for the Notebook Detail vocab list — focused on
/// `WordRow` under stress so the truncation / monospacedDigit / accessibility
/// hardening introduced in Phase 2 has a permanent visual baseline.
///
/// 故意不接 Presenter / SwiftData：直接餵合成的 `WordRow.ViewData`，
/// 確保 catalog 不依賴 backend / 真實 SwiftData 物件。
enum NotebookDetailScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebook Detail · Row") {
            Scenario("Happy path", layout: .fill) {
                rowStack(rows: Self.happyRows)
            }
            Scenario("Long word truncate", layout: .fill) {
                rowStack(rows: Self.longWordRows)
            }
            Scenario("Long translation", layout: .fill) {
                rowStack(rows: Self.longTranslationRows)
            }
            Scenario("Large numbers (4 digits)", layout: .fill) {
                rowStack(rows: Self.largeNumberRows)
            }
            Scenario("Narrow width 320pt", layout: .fill) {
                rowStack(rows: Self.happyRows, maxWidth: 320)
            }
            Scenario("Dynamic Type · accessibility3", layout: .fill) {
                rowStack(rows: Self.happyRows)
                    .dynamicTypeSize(.accessibility3)
            }
        }

        playbook.addScenarios(of: "Notebook Detail · Review Banner") {
            Scenario("Hero · due only", layout: .fill) {
                bannerSheet(style: .hero, due: 538, unlearned: 0)
            }
            Scenario("Hero · both types", layout: .fill) {
                bannerSheet(style: .hero, due: 42, unlearned: 12)
            }
            Scenario("Compact · due only (detail page)", layout: .fill) {
                bannerSheet(style: .compact, due: 538, unlearned: 0)
            }
            Scenario("Compact · both types", layout: .fill) {
                bannerSheet(style: .compact, due: 42, unlearned: 12)
            }
            Scenario("Compact · large numbers", layout: .fill) {
                bannerSheet(style: .compact, due: 9999, unlearned: 1234)
            }
        }
    }

    // MARK: - Banner sheet helper

    private static func bannerSheet(style: VocabReviewBannerStyle, due: Int, unlearned: Int) -> some View {
        let skin = AppSkin.previewNeutral
        return VStack(alignment: .leading, spacing: 16) {
            Text(style == .hero ? "Hero (NotebookListView)" : "Compact (VocabularyListView)")
                .font(skin.typography.caption)
                .foregroundStyle(skin.palette.tertiaryText)
                .padding(.horizontal, skin.metrics.pageHorizontalInset)
            VocabReviewBanner(
                dueCount: due,
                unlearnedCount: unlearned,
                style: style,
                onStartDue: {},
                onStartUnlearned: {},
                onStartMixed: {}
            )
            .padding(.horizontal, style == .hero ? skin.metrics.pageHorizontalInset : 0)
            Spacer(minLength: 0)
        }
        .padding(.top, 24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }

    // MARK: - Stress fixtures

    private static let happyRows: [WordRow.ViewData] = [
        Self.row(word: "lascivious", pos: "adj.", translation: "色情的", progress: Self.progress(ratio: 1.6, label: "42d / 2d")),
        Self.row(word: "hors d'oeuvres", pos: "n.", translation: "餐前點心", progress: Self.progress(ratio: 1.8, label: "55d / 16d")),
        Self.row(word: "forestall", pos: "v.", translation: "預先阻止", progress: Self.progress(ratio: 1.8, label: "55d / 16d")),
        Self.row(word: "deft", pos: "adj.", translation: "靈巧的", progress: Self.progress(ratio: 1.5, label: "59d / 20d"))
    ]

    private static let longWordRows: [WordRow.ViewData] = [
        // The classic medical pathology word — 45 chars
        Self.row(
            word: "pneumonoultramicroscopicsilicovolcanoconioses",
            pos: "n.",
            translation: "矽肺症",
            progress: Self.progress(ratio: 0.4, label: "12d / 30d")
        ),
        Self.row(
            word: "antidisestablishmentarianism",
            pos: "n.",
            translation: "反政教分離主義",
            progress: Self.progress(ratio: 0.8, label: "24d / 30d")
        ),
        Self.row(word: "supercalifragilisticexpialidocious", pos: "adj.", translation: "好極了", progress: nil)
    ]

    private static let longTranslationRows: [WordRow.ViewData] = [
        Self.row(
            word: "diaspora",
            pos: "n.",
            translation: "被迫離開原住地散居於世界各處的居民群體；引申為任何族群因戰爭、饑荒、迫害而流散他鄉的歷史現象",
            progress: Self.progress(ratio: 1.2, label: "30d / 25d")
        ),
        Self.row(
            word: "schadenfreude",
            pos: "n.",
            translation: "幸災樂禍 — 看到他人不幸時心中浮現的隱密快感，源自德語 Schaden（傷害）+ Freude（喜悅）",
            progress: Self.progress(ratio: 1.0, label: "30d / 30d")
        )
    ]

    private static let largeNumberRows: [WordRow.ViewData] = [
        Self.row(word: "verbose", pos: "adj.", translation: "冗長的", progress: Self.progress(ratio: 9.5, label: "9999d / 1234d")),
        Self.row(word: "terse", pos: "adj.", translation: "簡潔的", progress: Self.progress(ratio: 0.05, label: "1d / 365d")),
        Self.row(word: "laconic", pos: "adj.", translation: "言簡意賅", progress: Self.progress(ratio: 2.7, label: "888d / 333d"))
    ]

    // MARK: - Helpers

    private static func row(
        word: String,
        pos: String?,
        translation: String?,
        progress: VocabReviewProgress?
    ) -> WordRow.ViewData {
        WordRow.ViewData(
            id: UUID(),
            word: word,
            wordTone: .primary,
            isStrikethrough: false,
            partOfSpeech: pos,
            translation: translation,
            bookTitle: nil,
            chapterTitle: nil,
            difficultyTier: nil,
            reviewProgress: progress,
            leadingSystemImage: nil,
            leadingTone: nil,
            trailingLabel: nil,
            trailingTone: nil,
            statusText: nil,
            statusTone: nil
        )
    }

    private static func progress(ratio: Double, label: String) -> VocabReviewProgress {
        VocabReviewProgress(statusLabel: "due", detailLabel: label, ratio: ratio)
    }

    private static func rowStack(rows: [WordRow.ViewData], maxWidth: CGFloat? = nil) -> some View {
        let skin = AppSkin.previewNeutral
        let content = VStack(spacing: 0) {
            ForEach(rows) { row in
                WordRow(viewData: row)
                    .padding(.horizontal, skin.metrics.listRowHorizontalInset)
                Divider().opacity(0.4)
            }
            Spacer(minLength: 0)
        }
        .padding(.top, 16)
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)

        return Group {
            if let maxWidth {
                HStack {
                    content.frame(maxWidth: maxWidth)
                    Spacer(minLength: 0)
                }
                .background(skin.palette.stageBackground.ignoresSafeArea())
            } else {
                content
            }
        }
    }
}
#endif
