//
//  KGFeatureFlags.swift
//  Books & Vocab
//
//  Compile-time / runtime feature gates for shipping work-in-progress features
//  alongside backend dependencies. Default values reflect the current shipping
//  state; flip them when the matching backend change lands.
//

import Foundation

enum KGFeatureFlags {
    /// Whether to send `updated_at` and trust server-returned `updated_at` for
    /// LWW resolution on TranslationLanguage sync. Backend now persists
    /// `TranslationLanguageConfig.updated_at` (Feature C) and iOS already sends it
    /// on push + applies the server timestamp on cold-start (local-only, no KVS
    /// write-back). Until this flag is on, server is single-direction (server-wins
    /// on cold-start) and iCloud KV is the authoritative cross-device path —
    /// mirrors `serverVocabUiLwwEnabled` / `serverReviewModeLwwEnabled`.
    static var serverTranslationLwwEnabled: Bool { false }

    /// Whether to send `updated_at` and trust server-returned `updated_at` for
    /// LWW on the pause review clock. Backend dependency: `review_clock.updated_at`
    /// persisted + returned by `GET /api/user/config`. Until on, server is
    /// single-direction (server-wins on cold-start) and iCloud KV is the
    /// authoritative cross-device path — mirrors `serverTranslationLwwEnabled`.
    static var serverReviewClockLwwEnabled: Bool { false }

    /// Whether to send `updated_at` and trust server-returned `updated_at` for
    /// LWW on the review mode + custom SRS params. Backend dependency:
    /// `review_mode.updated_at` persisted + returned by `GET /api/user/config`.
    /// Until on, server is single-direction (server-wins on cold-start) and
    /// iCloud KV is the authoritative cross-device path — mirrors
    /// `serverReviewClockLwwEnabled`.
    static var serverReviewModeLwwEnabled: Bool { false }

    /// Whether to send `updated_at` and trust server-returned `updated_at` for
    /// LWW on the active notebook (`vocab_ui`) cursor. Backend dependency:
    /// `vocab_ui.updated_at` persisted + returned by `GET /api/user/config`.
    /// Until on, server is single-direction (server-wins on cold-start) and
    /// iCloud KV is the authoritative cross-device path for Apple devices —
    /// mirrors `serverReviewModeLwwEnabled`. (chrome / web read active notebook
    /// via the backend group.)
    static var serverVocabUiLwwEnabled: Bool { false }

    /// Whether the podcast feature is exposed anywhere in the UI (top-level
    /// section tab / Catalyst sidebar row / paywall marketing copy) **and**
    /// whether its data layer may run at all（`backgroundSync` catalog leg 含
    /// 封面下載、`PodcastDownloadManager.configure`）。DEBUG-only
    /// while the feature incubates: Release builds ship reader + vocabulary +
    /// notebook only — 零 podcast 網路/磁碟足跡（logout cleanup 除外，刻意保留
    /// 以清舊 build 殘檔）。Compile-time constant so Release codepaths are
    /// strippable.
    #if DEBUG
    static let podcastEnabled = true
    #else
    static let podcastEnabled = false
    #endif

    /// Whether to include `source_lang` / `target_lang` in VocabularyEntry
    /// upload payloads. Backend currently has `extra='ignore'` so adding the
    /// fields would be silently dropped; flip this when backend accepts them.
    static var vocabularyLangPayloadEnabled: Bool { false }
}
