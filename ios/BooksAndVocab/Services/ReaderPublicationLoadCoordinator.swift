#if os(iOS)
import Foundation
import ReadiumShared

/// Reader publication loader seam. The production implementation remains
/// `ReaderPublicationLoader`; tests can hold the await at a controlled
/// continuation without opening a real EPUB.
@MainActor
protocol ReaderPublicationLoading {
    func loadPublication(
        for book: Book,
        updatePhase: @escaping @MainActor (String) -> Void
    ) async throws -> ReaderPublicationLoadResult
}

extension ReaderPublicationLoader: ReaderPublicationLoading {}

/// Owns the Reader publication request generation. A retry or disappearance
/// invalidates the previous generation; a loader is allowed to finish late,
/// but it can no longer publish state into the current Reader view.
@MainActor
final class ReaderPublicationLoadCoordinator {
    struct Request: Sendable {
        fileprivate let generation: UInt

        fileprivate init(generation: UInt) {
            self.generation = generation
        }
    }

    private var generation: UInt = 0
    private var activeGeneration: UInt?

    func beginRequest() -> Request {
        generation &+= 1
        let request = Request(generation: generation)
        activeGeneration = request.generation
        return request
    }

    func load(
        book: Book,
        loader: any ReaderPublicationLoading,
        onPhase: @escaping @MainActor (String) -> Void,
        onPublication: @escaping @MainActor (Publication) -> Void,
        onUniqueWords: @escaping @MainActor (Set<String>) -> Void,
        onError: @escaping @MainActor (Error) -> Void
    ) async {
        let request = beginRequest()
        await load(
            request: request,
            book: book,
            loader: loader,
            onPhase: onPhase,
            onPublication: onPublication,
            onUniqueWords: onUniqueWords,
            onError: onError
        )
    }

    func load(
        request: Request,
        book: Book,
        loader: any ReaderPublicationLoading,
        onPhase: @escaping @MainActor (String) -> Void,
        onPublication: @escaping @MainActor (Publication) -> Void,
        onUniqueWords: @escaping @MainActor (Set<String>) -> Void,
        onError: @escaping @MainActor (Error) -> Void
    ) async {
        guard isCurrent(request.generation), !Task.isCancelled else { return }
        defer { finish(request.generation) }

        do {
            let result = try await loader.loadPublication(for: book) { [weak self] phase in
                guard let self, self.isCurrent(request.generation), !Task.isCancelled else { return }
                onPhase(phase)
            }

            guard isCurrent(request.generation), !Task.isCancelled else { return }
            onPublication(result.publication)

            let uniqueWords = await result.extractUniqueWords()
            guard isCurrent(request.generation), !Task.isCancelled else { return }
            onUniqueWords(uniqueWords)
        } catch is CancellationError {
            // Cancellation is an expected lifecycle event (retry/pop). It is
            // never a user-visible publication error.
        } catch {
            guard isCurrent(request.generation), !Task.isCancelled else { return }
            onError(error)
        }
    }

    /// Invalidates all completions. The caller owns cancellation of its
    /// structured `.task` / retry `Task`; this guard also handles loaders that
    /// ignore cancellation and return a stale result later.
    func cancelAndInvalidate() {
        generation &+= 1
        activeGeneration = nil
    }

    private func isCurrent(_ requestGeneration: UInt) -> Bool {
        activeGeneration == requestGeneration
    }

    private func finish(_ requestGeneration: UInt) {
        guard activeGeneration == requestGeneration else { return }
        activeGeneration = nil
    }
}
#endif
