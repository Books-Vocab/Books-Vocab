import Foundation

/// TranslationService 的行為契約
protocol Translating: AnyObject {
    func translateQuick(
        word: String,
        context: String,
        onRetry: ((Int, Int) -> Void)?
    ) async throws -> TranslationResult

    func translatePhrase(
        phrase: String,
        context: String,
        onRetry: ((Int, Int) -> Void)?
    ) async throws -> String

    func fetchExplanation(
        word: String,
        context: String,
        onRetry: ((Int, Int) -> Void)?
    ) async throws -> (explanation: String, latency: TimeInterval)
}
