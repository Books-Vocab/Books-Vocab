#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `ArchivedVocabSheet`.
///
/// The sheet is `@Query`-backed (filter `isArchived == true`, further narrowed
/// at runtime by `shouldAppearInArchiveList`, i.e. `isSynced && action != .delete
/// && isArchived`). Each scenario materializes a UI World vocabulary seed into a
/// fresh in-memory store; missing seeds, malformed archived row state, or save
/// failure fail at catalog construction time.
enum ArchivedVocabScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Archived Vocab") {
            Scenario("Populated", layout: .fill) {
                ArchivedVocabScene(fixture: .populated, expected: .atLeast(5))
            }
            Scenario("Single card", layout: .fill) {
                ArchivedVocabScene(fixture: .single, expected: .exactly(1))
            }
            Scenario("Long list (stress)", layout: .fill) {
                ArchivedVocabScene(fixture: .long, expected: .atLeast(40))
            }
            Scenario("Empty", layout: .fill) {
                ArchivedVocabScene(fixture: .empty, expected: .exactly(0))
            }
        }
    }
}

// MARK: - Fixtures

private enum ArchivedVocabFixture {
    case populated
    case single
    case long
    case empty

    var vocabularyID: UIWorldVocabularyFixtureID {
        switch self {
        case .populated:
            return .archivedPopulated
        case .single:
            return .archivedSingle
        case .long:
            return .archivedLong
        case .empty:
            return .archivedEmpty
        }
    }
}

private enum ArchivedVocabExpectedShape {
    case exactly(Int)
    case atLeast(Int)
}

// MARK: - Scene harness

/// `@MainActor` body so the in-memory container is seeded and env-default
/// services resolve on the main actor before `@Query` reads.
private struct ArchivedVocabScene: View {
    let container: ModelContainer

    init(fixture: ArchivedVocabFixture, expected: ArchivedVocabExpectedShape) {
        let seed = FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)
        do {
            let container = try ModelContainer(
                for: VocabularyEntry.self, Notebook.self, ReviewRecord.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            let entries = try MainActor.assumeIsolated {
                try UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)
            }
            Self.validate(entries, fixture: fixture, expected: expected)
            self.container = container
        } catch {
            preconditionFailure("Failed to materialize UI World vocabulary.\(fixture.vocabularyID.rawValue) for ArchivedVocabScenarios: \(error)")
        }
    }

    var body: some View {
        AppThemeContainer {
            ArchivedVocabSheet()
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private static func validate(
        _ entries: [VocabularyEntry],
        fixture: ArchivedVocabFixture,
        expected: ArchivedVocabExpectedShape
    ) {
        let visible = entries.filter(\.shouldAppearInArchiveList)
        switch expected {
        case .exactly(let count):
            guard visible.count == count else {
                preconditionFailure("UI World vocabulary.\(fixture.vocabularyID.rawValue) must declare \(count) visible archived entries, got \(visible.count)")
            }
        case .atLeast(let count):
            guard visible.count >= count else {
                preconditionFailure("UI World vocabulary.\(fixture.vocabularyID.rawValue) must declare at least \(count) visible archived entries, got \(visible.count)")
            }
        }
    }
}
#endif
