import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct BookshelfImportCancellationTests {
    private enum Completion {
        case success(ImportedBookDraft)
        case cancellation
    }

    @MainActor
    private final class ControlledImportService: BookshelfImporting {
        private(set) var startedKeys: [String] = []
        private var continuations: [String: CheckedContinuation<ImportedBookDraft, Error>] = [:]
        private var progressCallbacks: [String: (@Sendable (Double) -> Void)] = [:]

        func importBook(
            from sourceURL: URL,
            progress: (@Sendable (Double) -> Void)?
        ) async throws -> ImportedBookDraft {
            try await suspendImport(for: sourceURL, progress: progress)
        }

        func importTXT(
            from url: URL,
            progress: (@Sendable (Double) -> Void)?
        ) async throws -> ImportedBookDraft {
            try await suspendImport(for: url, progress: progress)
        }

        func importMD(
            from url: URL,
            progress: (@Sendable (Double) -> Void)?
        ) async throws -> ImportedBookDraft {
            try await suspendImport(for: url, progress: progress)
        }

        func importPDF(
            from url: URL,
            progress: (@Sendable (Double) -> Void)?
        ) async throws -> ImportedBookDraft {
            try await suspendImport(for: url, progress: progress)
        }

        func waitUntilStarted(_ key: String) async -> Bool {
            for _ in 0..<100 {
                if startedKeys.contains(key) { return true }
                await Task.yield()
            }
            return false
        }

        func complete(_ key: String, with completion: Completion) {
            guard let continuation = continuations.removeValue(forKey: key) else { return }
            switch completion {
            case .success(let draft): continuation.resume(returning: draft)
            case .cancellation: continuation.resume(throwing: CancellationError())
            }
        }

        func sendProgress(_ key: String, _ ratio: Double) {
            progressCallbacks[key]?(ratio)
        }

        private func suspendImport(
            for url: URL,
            progress: (@Sendable (Double) -> Void)?
        ) async throws -> ImportedBookDraft {
            let key = url.lastPathComponent
            startedKeys.append(key)
            if let progress { progressCallbacks[key] = progress }
            return try await withCheckedThrowingContinuation { continuation in
                continuations[key] = continuation
            }
        }
    }

    private func makeContainer() throws -> ModelContainer {
        let configuration = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try ModelContainer(for: Book.self, configurations: configuration)
    }

    private func makeDraft(_ key: String) -> ImportedBookDraft {
        ImportedBookDraft(
            title: key,
            author: "Author",
            coverImageData: nil,
            fileName: "\(key).epub",
            format: .epub
        )
    }

    private func waitForQuiescence(
        _ coordinator: BookshelfCoordinator,
        service: ControlledImportService
    ) async {
        for _ in 0..<100 {
            if !coordinator.isLoading && service.startedKeys.count >= 1 {
                await Task.yield()
                return
            }
            await Task.yield()
        }
    }

    @Test
    func supersededImportThatIgnoresCancellation_doesNotPersistOrReportFailure() async throws {
        let container = try makeContainer()
        let context = container.mainContext
        let coordinator = BookshelfCoordinator()
        let service = ControlledImportService()
        let toast = AppToastCoordinator()
        let first = URL(fileURLWithPath: "/tmp/old.txt")
        let second = URL(fileURLWithPath: "/tmp/new.txt")

        coordinator.handleFileImport(
            .success([first]),
            modelContext: context,
            importService: service,
            toastCoordinator: toast
        )
        #expect(await service.waitUntilStarted(first.lastPathComponent))

        coordinator.handleFileImport(
            .success([second]),
            modelContext: context,
            importService: service,
            toastCoordinator: toast
        )
        #expect(await service.waitUntilStarted(second.lastPathComponent))

        service.sendProgress(first.lastPathComponent, 0.95)
        service.sendProgress(second.lastPathComponent, 0.25)
        service.complete(first.lastPathComponent, with: .success(makeDraft("old")))
        service.complete(second.lastPathComponent, with: .success(makeDraft("new")))
        await waitForQuiescence(coordinator, service: service)

        let books = try context.fetch(FetchDescriptor<Book>())
        #expect(books.map(\.title) == ["new"])
        #expect(coordinator.errorMessage == nil)
        #expect(coordinator.errorDiagnosis == nil)
        #expect(coordinator.showError == false)
        #expect(coordinator.loadingProgress == nil)
        #expect(toast.current?.style == .success)
    }

    @Test
    func cancellationError_isSilentAndDoesNotBecomeImportFailure() async throws {
        let container = try makeContainer()
        let context = container.mainContext
        let coordinator = BookshelfCoordinator()
        let service = ControlledImportService()
        let toast = AppToastCoordinator()
        let url = URL(fileURLWithPath: "/tmp/cancelled.txt")

        coordinator.handleFileImport(
            .success([url]),
            modelContext: context,
            importService: service,
            toastCoordinator: toast
        )
        #expect(await service.waitUntilStarted(url.lastPathComponent))
        service.complete(url.lastPathComponent, with: .cancellation)
        await waitForQuiescence(coordinator, service: service)

        #expect(try context.fetch(FetchDescriptor<Book>()).isEmpty)
        #expect(coordinator.isLoading == false)
        #expect(coordinator.errorMessage == nil)
        #expect(coordinator.errorDiagnosis == nil)
        #expect(coordinator.showError == false)
        #expect(toast.current == nil)
    }
}
