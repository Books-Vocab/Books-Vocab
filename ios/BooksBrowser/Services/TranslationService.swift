//
//  TranslationService.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import Foundation
import FoundationModels
import os

/// AI 翻譯結果
struct TranslationResult: Codable {
    let translation: String
    let partOfSpeech: String?
    let pronunciation: String?   // 從字典 API 填入，非 LLM
    let explanation: String?     // Phase 2 填入
    var rootForm: String? = nil  // AI 判斷的詞根原形（e.g. "laid" → "lay"）
    var latency: TimeInterval?   // 耗時（秒）
}

/// AI 翻譯服務 — 使用 Gemini API 進行上下文感知翻譯
@Observable
final class TranslationService: Translating {
    @ObservationIgnored
    private let authSession: any AuthSessionProviding
    @ObservationIgnored
    private let quotaStore: any QuotaProviding

    init(
        authSession: any AuthSessionProviding = MainActor.assumeIsolated({ AuthManager.shared }),
        quotaStore: any QuotaProviding = QuotaStore.shared
    ) {
        self.authSession = authSession
        self.quotaStore = quotaStore
    }

    /// Backend Server URL
    private var backendURL: String {
        KGService.getServerURL()
    }

    // MARK: - Phase 1: 精簡翻譯（~10 output tokens）
    
    func translateQuick(
        word: String,
        context: String,
        onRetry: ((Int, Int) -> Void)? = nil
    ) async throws -> TranslationResult {
        let startTime = Date()
        AppAnalytics.track(.translationRequested(word: word, type: .quick))
        let signpostState = AppAnalytics.beginInterval("TranslateQuick")

        var result: TranslationResult
        do {
            result = try await withRetry(onRetry: onRetry) {
                AppLog.translation.debug("Quick翻譯請求: \(word)")
                let data = try await self.callBackend(endpoint: "/api/translate/quick", word: word, context: context)

                struct QuickResult: Codable {
                    let t: String
                    let p: String?
                    let r: String?
                }

                let quick = try JSONDecoder().decode(QuickResult.self, from: data)
                AppLog.translation.info("Quick翻譯: \(word) → \(quick.t) (root: \(quick.r ?? "nil"))")

                return TranslationResult(
                    translation: quick.t,
                    partOfSpeech: quick.p,
                    pronunciation: nil,
                    explanation: nil,
                    rootForm: quick.r,
                    latency: nil
                )
            }
        } catch {
            AppAnalytics.endInterval("TranslateQuick", signpostState)
            let latencyMs = Int(Date().timeIntervalSince(startTime) * 1000)
            AppAnalytics.track(.translationFailed(word: word, type: .quick, error: error.localizedDescription))
            _ = latencyMs
            throw error
        }

        let endTime = Date()
        result.latency = endTime.timeIntervalSince(startTime)
        AppAnalytics.endInterval("TranslateQuick", signpostState)
        let latencyMs = Int(result.latency! * 1000)
        AppAnalytics.track(.translationCompleted(word: word, type: .quick, latencyMs: latencyMs))
        return result
    }

    // MARK: - Phase 1b: 短語翻譯（Flow 2，只回傳翻譯文字）

    func translatePhrase(
        phrase: String,
        context: String,
        onRetry: ((Int, Int) -> Void)? = nil
    ) async throws -> String {
        let startTime = Date()
        AppAnalytics.track(.translationRequested(word: phrase, type: .phrase))

        do {
            let translated = try await withRetry(onRetry: onRetry) {
                AppLog.translation.debug("短語翻譯請求: \(phrase)")
                let data = try await self.callBackend(endpoint: "/api/translate/phrase", word: phrase, context: context)

                struct PhraseResult: Codable {
                    let t: String
                }

                let result = try JSONDecoder().decode(PhraseResult.self, from: data)
                AppLog.translation.info("短語翻譯: \(phrase) → \(result.t)")
                return result.t
            }
            let latencyMs = Int(Date().timeIntervalSince(startTime) * 1000)
            AppAnalytics.track(.translationCompleted(word: phrase, type: .phrase, latencyMs: latencyMs))
            return translated
        } catch {
            let latencyMs = Int(Date().timeIntervalSince(startTime) * 1000)
            AppAnalytics.track(.translationFailed(word: phrase, type: .phrase, error: error.localizedDescription))
            _ = latencyMs
            throw error
        }
    }

    // MARK: - Phase 2: 語境解釋（使用者按需觸發）

    func fetchExplanation(
        word: String,
        context: String,
        onRetry: ((Int, Int) -> Void)? = nil
    ) async throws -> (explanation: String, latency: TimeInterval) {
        let startTime = Date()
        AppAnalytics.track(.translationRequested(word: word, type: .explanation))
        let signpostState = AppAnalytics.beginInterval("FetchExplanation")

        do {
            let explanation = try await withRetry(onRetry: onRetry) {
                AppLog.translation.debug("解釋請求: \(word)")
                let data = try await self.callBackend(endpoint: "/api/translate/explain", word: word, context: context)

                struct ExplanationResult: Codable {
                    let e: String
                }

                let result = try JSONDecoder().decode(ExplanationResult.self, from: data)
                AppLog.translation.info("解釋完成: \(result.e.prefix(50))...")
                return result.e
            }

            let endTime = Date()
            let latency = endTime.timeIntervalSince(startTime)
            AppAnalytics.endInterval("FetchExplanation", signpostState)
            AppAnalytics.track(.translationCompleted(word: word, type: .explanation, latencyMs: Int(latency * 1000)))
            return (explanation, latency)
        } catch {
            AppAnalytics.endInterval("FetchExplanation", signpostState)
            let latencyMs = Int(Date().timeIntervalSince(startTime) * 1000)
            AppAnalytics.track(.translationFailed(word: word, type: .explanation, error: error.localizedDescription))
            _ = latencyMs
            throw error
        }
    }

    // MARK: - API Error Model

    private struct APIErrorDetail: Decodable {
        let code: String?
        let detail: String?
    }

    // MARK: - Backend Translation API 呼叫

    private func callBackend(endpoint: String, word: String, context: String) async throws -> Data {
        let baseURL = backendURL.trimmingCharacters(in: .whitespacesAndNewlines)
        var cleanURL = baseURL
        if !cleanURL.hasPrefix("http://") && !cleanURL.hasPrefix("https://") {
            cleanURL = "http://" + cleanURL
        }
        
        guard let url = URL(string: "\(cleanURL)\(endpoint)") else {
            throw TranslationError.apiError(L10n.string("無效的後端 URL"))
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        // 帶上授權 Header (因為 /api/translate 是受保護的端點)
        guard let token = await authSession.token else {
            throw TranslationError.apiError(L10n.string("未登入，無法調用翻譯 API"))
        }
        request.addValue("Bearer \(token)", forHTTPHeaderField: "Authorization")

        let body: [String: String] = [
            "word": word,
            "context": context,
            "source_lang": TranslationLanguage.currentSource.rawValue,
            "target_lang": TranslationLanguage.currentTarget.rawValue,
        ]

        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await sharedURLSession.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw TranslationError.apiError(L10n.string("無法取得 HTTP 回應"))
        }

        // Update quota from response headers (before status check)
        quotaStore.update(from: httpResponse)

        guard httpResponse.statusCode == 200 else {
            let errorBody = String(data: data, encoding: .utf8) ?? L10n.string("(無法讀取)")
            AppLog.translation.error("Backend API error [\(httpResponse.statusCode)]: \(errorBody)")

            if httpResponse.statusCode == 401 {
                throw TranslationError.apiError(L10n.string("登入憑證已失效，請重新登入"))
            }
            if httpResponse.statusCode == 429 {
                // Prefer structured JSON check, fallback to string match
                var isQuotaExhausted = false
                if let errorData = errorBody.data(using: .utf8),
                   let json = try? JSONDecoder().decode(APIErrorDetail.self, from: errorData),
                   json.code == "quota_exhausted" {
                    isQuotaExhausted = true
                } else if errorBody.contains("quota_exhausted") {
                    isQuotaExhausted = true
                }
                if isQuotaExhausted {
                    throw TranslationError.quotaExhausted(quotaStore.resetText)
                }
                throw TranslationError.apiError(L10n.string("請求過於頻繁，請稍後再試"))
            }
            throw TranslationError.apiError(L10n.format("後端伺服器錯誤 (%@)", "\(httpResponse.statusCode)"))
        }

        return data
    }


}

enum TranslationError: LocalizedError {
    case apiError(String)
    case parseError(String)
    case quotaExhausted(String)

    var errorDescription: String? {
        switch self {
        case .apiError(let msg): return L10n.format("API 錯誤：%@", msg)
        case .parseError(let msg): return L10n.format("解析錯誤：%@", msg)
        case .quotaExhausted(let resetText): return L10n.format("今日額度已用完，%@", resetText)
        }
    }
}
