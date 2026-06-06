//
//  KGFeatureFlags.swift
//  BooksBrowser
//
//  Compile-time / runtime feature gates for shipping work-in-progress features
//  alongside backend dependencies. Default values reflect the current shipping
//  state; flip them when the matching backend change lands.
//

import Foundation

enum KGFeatureFlags {
    /// Whether to send `updated_at` and trust server-returned `updated_at` for
    /// LWW resolution on TranslationLanguage sync.
    /// Backend dependency: `TranslationLanguageConfig.updated_at` field must be
    /// persisted and returned by `GET /api/user/config`. Until then, server LWW
    /// is single-direction (server-wins on initial fetch) and iCloud KV is the
    /// authoritative cross-device path.
    static var serverTranslationLwwEnabled: Bool { false }

    /// Whether to send `updated_at` and trust server-returned `updated_at` for
    /// LWW on the pause review clock. Backend dependency: `review_clock.updated_at`
    /// persisted + returned by `GET /api/user/config`. Until on, server is
    /// single-direction (server-wins on cold-start) and iCloud KV is the
    /// authoritative cross-device path — mirrors `serverTranslationLwwEnabled`.
    static var serverReviewClockLwwEnabled: Bool { false }

    /// Whether to include `source_lang` / `target_lang` in VocabularyEntry
    /// upload payloads. Backend currently has `extra='ignore'` so adding the
    /// fields would be silently dropped; flip this when backend accepts them.
    static var vocabularyLangPayloadEnabled: Bool { false }
}
