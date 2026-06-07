#if DEBUG && canImport(Playbook)
import Playbook
import PlaybookUI
import SwiftUI

/// DEBUG-only Playbook catalog of KG SwiftUI surfaces.
///
/// 啟用方式:
/// 1. Xcode → Product → Scheme → Edit Scheme → Run → Arguments → Launch Arguments
///    加 `-catalog`
/// 2. ⌘R 跑 Debug build,app 啟動進 catalog 而非正常 UI
///
/// 截圖協作流程: simulator 跑著時用 `xcrun simctl io booted screenshot foo.png`,
/// 把 PNG 路徑貼給 Claude 即可協作視覺迭代。詳見 docs/sop/ios.md §Playbook Catalog。
struct CatalogScene: View {
    // Why: static let 確保 scenarios 只註冊一次 (Swift static init 是 thread-safe + lazy)。
    // 若改成 instance-level 每次 View init 都會重複註冊,Playbook 內部 storage
    // 會出現重複 entries。
    private static let playbook: Playbook = buildPlaybook()

    struct ScenarioDescriptor: Hashable {
        let category: String
        let title: String
    }

    struct Filter {
        let groups: Set<String>
        let scenarios: Set<ScenarioDescriptor>

        var isEmpty: Bool { groups.isEmpty && scenarios.isEmpty }

        func includes(category: String, title: String) -> Bool {
            if groups.contains(category) { return true }
            return scenarios.contains(.init(category: category, title: title))
        }
    }

    struct ManifestEntry {
        let id: String
        let categories: [String]
        let register: (Playbook) -> Void
    }

    enum Manifest {
        static let entries: [ManifestEntry] = [
            .init(id: "design_tokens", categories: ["Design Tokens"], register: TokenSheetScenarios.register),
            .init(
                id: "reader",
                categories: [
                    "Reader · Translation",
                    "Reader · TOC",
                    "Reader · Settings",
                    "Reader · Quota",
                    "Reader · Selection Tile",
                    "Reader · Step Control",
                ],
                register: ReaderScenarios.register
            ),
            .init(
                id: "notebook_detail",
                categories: ["Notebook Detail · Row", "Notebook Detail · CTA Pill"],
                register: NotebookDetailScenarios.register
            ),
            .init(
                id: "notebooks",
                categories: ["Notebooks · Stack", "Notebooks · Card"],
                register: NotebooksScenarios.register
            ),
            .init(
                id: "notebook_list",
                categories: ["Notebooks · Stack"],
                register: NotebookListScenarios.register
            ),
            .init(
                id: "vocabulary",
                categories: [
                    "Vocabulary · Overview",
                    "Vocabulary · Knowledge Graph",
                    "Vocabulary · Linked Card",
                    "Vocabulary · Add Link",
                ],
                register: VocabScenarios.register
            ),
            .init(
                id: "word_detail",
                categories: ["Word Detail · Sheet", "Word Detail · Card Document"],
                register: WordDetailScenarios.register
            ),
            .init(
                id: "podcast_player",
                categories: ["Podcast · Subtitle", "Podcast · Episode Row"],
                register: PodcastPlayerScenarios.register
            ),
            .init(id: "settings", categories: ["Settings"], register: SettingsScenarios.register),
            .init(id: "today_review", categories: ["Today Review"], register: TodayReviewScenarios.register),
            .init(id: "bookshelf", categories: ["Bookshelf"], register: BookshelfScenarios.register),
            .init(id: "welcome", categories: ["Welcome"], register: WelcomeScenarios.register),
        ]

        static var categoryNames: Set<String> {
            Set(entries.flatMap(\.categories))
        }
    }

    /// Build a fresh `Playbook` with all KG surface scenarios registered.
    /// Exposed (internal-access) so `BooksBrowserTests` can drive PlaybookSnapshot
    /// against the same surface set as the in-app catalog.
    static func buildPlaybook(filter: Filter? = nil) -> Playbook {
        let pb = Playbook()
        for entry in Manifest.entries {
            entry.register(pb)
        }
        return filteredPlaybook(from: pb, using: filter)
    }

    static func filter(groups: [String], scenarios: [String]) -> Filter {
        let normalizedGroups = Set(groups.map(normalizeCategoryOrScenarioName))
        let normalizedScenarios = Set(scenarios.compactMap { descriptor(from: $0) })
        return .init(groups: normalizedGroups, scenarios: normalizedScenarios)
    }

    private static func filteredPlaybook(from playbook: Playbook, using filter: Filter?) -> Playbook {
        guard let filter, !filter.isEmpty else { return playbook }

        let scoped = Playbook()
        for store in playbook.stores {
            let category = store.category.rawValue
            let matchedScenarios = store.scenarios.filter { filter.includes(category: category, title: $0.title.rawValue) }
            guard !matchedScenarios.isEmpty else { continue }
            let targetStore = scoped.scenarios(of: store.category)
            for scenario in matchedScenarios {
                targetStore.add(scenario)
            }
        }
        return scoped
    }

    private static func descriptor(from rawValue: String) -> ScenarioDescriptor? {
        let normalized = normalizeCategoryOrScenarioName(rawValue)
        let segments = normalized.split(separator: "/", maxSplits: 1).map(String.init)
        guard segments.count == 2 else { return nil }
        return .init(category: segments[0], title: segments[1])
    }

    private static func normalizeCategoryOrScenarioName(_ rawValue: String) -> String {
        rawValue
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
    }

    var body: some View {
        PlaybookCatalog(title: "KG Catalog", playbook: Self.playbook)
    }
}

#Preview {
    CatalogScene()
}
#endif
