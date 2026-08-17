#if os(iOS)
import Foundation
import ReadiumShared
import Testing
@testable import BooksAndVocab

@Suite("ReaderPublicationLoadCoordinator")
@MainActor
struct ReaderPublicationLoadCoordinatorTests {
    @Test
    func readerBeginsGenerationBeforeMutatingLoadingState() throws {
        let sourceURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Views/Reader/ReaderView.swift")
        let source = try String(contentsOf: sourceURL, encoding: .utf8)
        let loadStart = try #require(source.range(of: "private func loadPublication()"))
        let loadEnd = source.range(of: "\n    }\n}\n#endif", range: loadStart.upperBound..<source.endIndex)?.lowerBound
            ?? source.endIndex
        let loadBody = source[loadStart.lowerBound..<loadEnd]
        let requestOffset = try #require(loadBody.range(of: "let request = publicationLoadCoordinator.beginRequest()"))
        let attemptOffset = try #require(loadBody.range(of: "readerState.runtime.beginLoadAttempt()"))

        #expect(requestOffset.lowerBound < attemptOffset.lowerBound)
    }

    @Test
    func retryInvalidatesBeforeSchedulingReplacementTask() throws {
        let sourceURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Views/Reader/ReaderView.swift")
        let source = try String(contentsOf: sourceURL, encoding: .utf8)
        let retryStart = try #require(source.range(of: "func retryLoadPublication()"))
        let retryEnd = try #require(source.range(of: "\n    private func loadPublication()", range: retryStart.upperBound..<source.endIndex))
        let retryBody = source[retryStart.lowerBound..<retryEnd.lowerBound]
        let invalidateOffset = try #require(retryBody.range(of: "publicationLoadCoordinator.cancelAndInvalidate()"))
        let scheduleOffset = try #require(retryBody.range(of: "retryLoadTask = Task"))

        #expect(invalidateOffset.lowerBound < scheduleOffset.lowerBound)
    }

    @Test
    func supersededLoadCannotPublishLateSuccessOrUniqueWords() async {
        let loader = ControlledReaderPublicationLoader()
        let coordinator = ReaderPublicationLoadCoordinator()
        let first = makeBook(title: "first")
        let second = makeBook(title: "second")
        var published: [String] = []
        var uniqueWords: [Set<String>] = []
        var errors: [String] = []

        let firstTask = Task {
            await coordinator.load(
                book: first,
                loader: loader,
                onPhase: { _ in },
                onPublication: { publication in published.append(publication.metadata.title ?? "") },
                onUniqueWords: { uniqueWords.append($0) },
                onError: { errors.append($0.localizedDescription) }
            )
        }
        await settle()

        let secondTask = Task {
            await coordinator.load(
                book: second,
                loader: loader,
                onPhase: { _ in },
                onPublication: { publication in published.append(publication.metadata.title ?? "") },
                onUniqueWords: { uniqueWords.append($0) },
                onError: { errors.append($0.localizedDescription) }
            )
        }
        await settle()

        loader.resolve(
            title: first.title,
            result: .success(makeResult(title: first.title, words: ["old"]))
        )
        loader.resolve(
            title: second.title,
            result: .success(makeResult(title: second.title, words: ["new"]))
        )
        await firstTask.value
        await secondTask.value

        #expect(published == [second.title])
        #expect(uniqueWords == [Set(["new"])])
        #expect(errors.isEmpty)
    }

    @Test
    func cancellationAndDisappearDoNotWriteState() async {
        let loader = ControlledReaderPublicationLoader()
        let coordinator = ReaderPublicationLoadCoordinator()
        let book = makeBook(title: "cancelled")
        var published: [String] = []
        var uniqueWords: [Set<String>] = []
        var errors: [String] = []

        let task = Task {
            await coordinator.load(
                book: book,
                loader: loader,
                onPhase: { _ in },
                onPublication: { published.append($0.metadata.title ?? "") },
                onUniqueWords: { uniqueWords.append($0) },
                onError: { errors.append($0.localizedDescription) }
            )
        }
        await settle()
        coordinator.cancelAndInvalidate()
        loader.resolve(
            title: book.title,
            result: .success(makeResult(title: book.title, words: ["stale"]))
        )
        await task.value

        #expect(published.isEmpty)
        #expect(uniqueWords.isEmpty)
        #expect(errors.isEmpty)
    }

    @Test
    func cancellationErrorIsSilentButRealErrorIsVisible() async {
        let loader = ControlledReaderPublicationLoader()
        let coordinator = ReaderPublicationLoadCoordinator()
        let cancellationBook = makeBook(title: "cancellation-error")
        let realErrorBook = makeBook(title: "real-error")
        var published: [String] = []
        var uniqueWords: [Set<String>] = []
        var errors: [String] = []

        let cancellationTask = Task {
            await coordinator.load(
                book: cancellationBook,
                loader: loader,
                onPhase: { _ in },
                onPublication: { published.append($0.metadata.title ?? "") },
                onUniqueWords: { uniqueWords.append($0) },
                onError: { errors.append($0.localizedDescription) }
            )
        }
        await settle()
        loader.resolve(title: cancellationBook.title, result: .failure(CancellationError()))
        await cancellationTask.value

        let realErrorTask = Task {
            await coordinator.load(
                book: realErrorBook,
                loader: loader,
                onPhase: { _ in },
                onPublication: { published.append($0.metadata.title ?? "") },
                onUniqueWords: { uniqueWords.append($0) },
                onError: { errors.append($0.localizedDescription) }
            )
        }
        await settle()
        loader.resolve(title: realErrorBook.title, result: .failure(TestLoadError.failed))
        await realErrorTask.value

        #expect(published.isEmpty)
        #expect(uniqueWords.isEmpty)
        #expect(errors.count == 1)
        #expect(errors[0] == TestLoadError.failed.localizedDescription)
    }

    @Test
    func completedLoadIgnoresLatePhaseUpdate() async {
        let loader = ControlledReaderPublicationLoader()
        let coordinator = ReaderPublicationLoadCoordinator()
        let book = makeBook(title: "completed")
        var phases: [String] = []

        let task = Task {
            await coordinator.load(
                book: book,
                loader: loader,
                onPhase: { phases.append($0) },
                onPublication: { _ in },
                onUniqueWords: { _ in },
                onError: { _ in }
            )
        }
        await settle()
        loader.resolve(
            title: book.title,
            result: .success(makeResult(title: book.title, words: ["done"]))
        )
        await task.value

        loader.emitPhase(title: book.title, phase: "late")

        #expect(phases.isEmpty)
    }

    private func makeBook(title: String) -> Book {
        Book(title: title, author: "Author", fileName: "(title).epub")
    }

    private func makeResult(title: String, words: Set<String>) -> ReaderPublicationLoadResult {
        let publication = Publication(manifest: Manifest(metadata: Metadata(title: title)))
        return ReaderPublicationLoadResult(
            publication: publication,
            extractUniqueWords: { words }
        )
    }

    private func settle() async {
        for _ in 0..<12 { await Task.yield() }
    }
}

@MainActor
private final class ControlledReaderPublicationLoader: ReaderPublicationLoading {
    private var continuations: [String: CheckedContinuation<ReaderPublicationLoadResult, Error>] = [:]
    private var phaseUpdates: [String: @MainActor (String) -> Void] = [:]

    func loadPublication(
        for book: Book,
        updatePhase: @escaping @MainActor (String) -> Void
    ) async throws -> ReaderPublicationLoadResult {
        phaseUpdates[book.title] = updatePhase
        return try await withCheckedThrowingContinuation { continuation in
            continuations[book.title] = continuation
        }
    }

    func resolve(title: String, result: Result<ReaderPublicationLoadResult, Error>) {
        guard let continuation = continuations.removeValue(forKey: title) else { return }
        continuation.resume(with: result)
    }

    func emitPhase(title: String, phase: String) {
        phaseUpdates[title]?(phase)
    }
}

private enum TestLoadError: LocalizedError {
    case failed

    var errorDescription: String? { "controlled loader failed" }
}
#endif
