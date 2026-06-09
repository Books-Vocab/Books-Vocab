import Foundation

/// TranslationService 的行為契約
///
/// `onRetry` 是 `@Sendable async` closure：service 以 structured `await` 呼叫，
/// 因此 closure body 受呼叫端 task 的取消涵蓋（`Task.isCancelled` 反映 parent flag）。
/// 改成 async 是為了讓 Reader handler 能在 closure 內 `await MainActor.run { ... }`
/// 寫回 @MainActor status，且仍處於 parent task 的 cancellation guard 之下 —
/// 取代原本「內層 unstructured `Task` 不繼承取消」造成的 stale 寫回 race。
protocol Translating: AnyObject {
    func translateQuick(
        word: String,
        context: String,
        onRetry: (@Sendable (Int, Int) async -> Void)?
    ) async throws -> TranslationResult

    func translatePhrase(
        phrase: String,
        context: String,
        onRetry: (@Sendable (Int, Int) async -> Void)?
    ) async throws -> String

    func fetchExplanation(
        word: String,
        context: String,
        onRetry: (@Sendable (Int, Int) async -> Void)?
    ) async throws -> (explanation: String, latency: TimeInterval)
}
