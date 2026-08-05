#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `NotebookCoverView` / `NotebookCoverPattern`.
///
/// Cover color, title, pattern, and image-backed cover path all come from UI
/// World `notebook.coverGallery`. Image covers are installed through the asset
/// manifest, so missing files, hash drift, unsafe install paths, or bad refs
/// fail during scenario construction instead of falling back to a pattern.
enum NotebookCoverScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebook Cover") {
            Scenario("Manifest covers", layout: .fillH) {
                NotebookCoverGalleryScene(showsName: true)
            }
            Scenario("Manifest covers · overlay mode", layout: .fillH) {
                NotebookCoverGalleryScene(showsName: false)
            }
        }
    }
}

// MARK: - Scene harness

private struct NotebookCoverGalleryScene: View {
    let notebooks: [Notebook]
    let showsName: Bool

    init(showsName: Bool) {
        let notebooks = NotebookFixtures.notebooks(for: .coverGallery)
        Self.validate(notebooks)
        self.notebooks = notebooks
        self.showsName = showsName
    }

    var body: some View {
        AppThemeContainer {
            ScrollView {
                LazyVGrid(columns: Self.columns, spacing: 16) {
                    ForEach(notebooks) { notebook in
                        cover(notebook)
                    }
                }
                .padding(16)
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private static let columns = [GridItem(.adaptive(minimum: 110), spacing: 16)]

    private func cover(_ notebook: Notebook) -> some View {
        NotebookCoverView(
            color: NotebookPalette.color(for: notebook.color),
            pattern: notebook.coverPattern.flatMap(NotebookCoverPattern.init(rawValue:)),
            coverImagePath: notebook.coverImagePath,
            name: notebook.name,
            showsName: showsName
        )
        .frame(height: 96)
        .clipShape(AppRoundedRect(roundness: AppRoundness.card))
    }

    private static func validate(_ notebooks: [Notebook]) {
        precondition(!notebooks.isEmpty, "UI World notebook.coverGallery must declare cover notebooks")

        let declaredPatterns = Set(notebooks.compactMap(\.coverPattern))
        let expectedPatterns = Set(NotebookCoverPattern.allCases.map(\.rawValue))
        precondition(
            expectedPatterns.isSubset(of: declaredPatterns),
            "UI World notebook.coverGallery must include every NotebookCoverPattern; missing \(expectedPatterns.subtracting(declaredPatterns).sorted())"
        )

        let imageBacked = notebooks.filter { $0.coverImagePath != nil }
        precondition(
            !imageBacked.isEmpty,
            "UI World notebook.coverGallery must include at least one image-backed cover"
        )
        for notebook in imageBacked {
            guard let path = notebook.coverImagePath, FileManager.default.fileExists(atPath: path) else {
                preconditionFailure("UI World notebook.coverGallery image-backed notebook \(notebook.remoteId) has no installed cover image")
            }
        }
    }
}
#endif
