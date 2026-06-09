import Foundation

enum TranslationLanguage: String, CaseIterable, Identifiable, Codable {
    case en
    case zhHant = "zh-Hant"
    case zhHans = "zh-Hans"
    case ja
    case ko
    case fr
    case de
    case es

    var id: String { rawValue }

    var nativeName: String {
        switch self {
        case .en: return "English"
        case .zhHant: return "繁體中文"  // i18n-allow: language-self-name
        case .zhHans: return "简体中文"  // i18n-allow: language-self-name
        case .ja: return "日本語"        // i18n-allow: language-self-name
        case .ko: return "한국어"
        case .fr: return "Français"
        case .de: return "Deutsch"
        case .es: return "Español"
        }
    }

    var flagEmoji: String {
        switch self {
        case .en: return "🇺🇸"
        case .zhHant: return "🇹🇼"
        case .zhHans: return "🇨🇳"
        case .ja: return "🇯🇵"
        case .ko: return "🇰🇷"
        case .fr: return "🇫🇷"
        case .de: return "🇩🇪"
        case .es: return "🇪🇸"
        }
    }

    static var sourceLanguages: [TranslationLanguage] { [.en, .ja, .ko, .fr, .de, .es] }
    static var targetLanguages: [TranslationLanguage] { [.zhHant, .zhHans, .en, .ja, .ko] }

    // MARK: - System Locale Inference

    /// Walks `Locale.preferredLanguages` and returns the first entry that matches
    /// one of `allowed`. Script-aware: distinguishes `zh-Hans` from `zh-Hant` by
    /// the canonical script subtag instead of bare prefix match (which would
    /// always hit zh-Hant first because of alphabetic ordering).
    ///
    /// Internal scope: testable from BooksAndVocabTests.
    static func inferFromPreferredLanguages(
        allowed: [TranslationLanguage],
        preferred: [String] = Locale.preferredLanguages
    ) -> TranslationLanguage? {
        for code in preferred {
            let canonical = Locale(identifier: code)
            guard let lang = canonical.language.languageCode?.identifier else { continue }
            let script = canonical.language.script?.identifier

            if lang == "zh" {
                if code == "zh" {
                    return allowed.first(where: { $0 == .zhHant })
                }
                if script == "Hans", let hit = allowed.first(where: { $0 == .zhHans }) {
                    return hit
                }
                if let hit = allowed.first(where: { $0 == .zhHant }) {
                    return hit
                }
                continue
            }
            if let hit = allowed.first(where: { $0.rawValue.hasPrefix(lang) }) {
                return hit
            }
        }
        return nil
    }

    // MARK: - UserDefaults + iCloud KV persistence (with LWW timestamp)
    //
    // Storage layers:
    //   - UserDefaults (local truth, fastest read)
    //   - NSUbiquitousKeyValueStore via CloudPreferencesSync (cross-device LWW)
    //   - `*_updated_at` timestamps (Double, seconds since 1970) drive LWW
    //
    // Server LWW is feature-flagged off (see KGFeatureFlags) until the backend
    // persists `updated_at` on TranslationLanguageConfig. Until then iCloud KV
    // is the authoritative cross-device sync path; server only wins on initial
    // fetch (server-wins-cold-start).

    private static let sourceKey = "translation_source_lang"
    private static let targetKey = "translation_target_lang"
    private static let sourceUpdatedAtKey = "translation_source_lang_updated_at"
    private static let targetUpdatedAtKey = "translation_target_lang_updated_at"

    static var currentSource: TranslationLanguage {
        get { readPersisted(key: sourceKey, fallback: { resolveSourceDefault() }) }
        set { writePersisted(value: newValue, key: sourceKey, updatedAtKey: sourceUpdatedAtKey) }
    }

    static var currentTarget: TranslationLanguage {
        get { readPersisted(key: targetKey, fallback: { resolveTargetDefault() }) }
        set { writePersisted(value: newValue, key: targetKey, updatedAtKey: targetUpdatedAtKey) }
    }

    /// Timestamp (seconds since 1970) of the last local write, used for LWW.
    /// `nil` if the value has never been written on this device or via iCloud.
    static var sourceUpdatedAt: Double? {
        let local = UserDefaults.standard.object(forKey: sourceUpdatedAtKey) as? Double
        let cloud = CloudPreferencesSync.shared.double(forKey: sourceUpdatedAtKey)
        return [local, cloud].compactMap { $0 }.max()
    }

    static var targetUpdatedAt: Double? {
        let local = UserDefaults.standard.object(forKey: targetUpdatedAtKey) as? Double
        let cloud = CloudPreferencesSync.shared.double(forKey: targetUpdatedAtKey)
        return [local, cloud].compactMap { $0 }.max()
    }

    // MARK: - Default resolution

    private static func resolveSourceDefault() -> TranslationLanguage {
        inferFromPreferredLanguages(allowed: sourceLanguages) ?? .en
    }

    private static func resolveTargetDefault() -> TranslationLanguage {
        inferFromPreferredLanguages(allowed: targetLanguages) ?? .zhHant
    }

    private static func readPersisted(
        key: String,
        fallback: () -> TranslationLanguage
    ) -> TranslationLanguage {
        // Prefer cloud read (cross-device), falling back to local UserDefaults.
        if let cloudRaw = CloudPreferencesSync.shared.string(forKey: key),
           let lang = TranslationLanguage(rawValue: cloudRaw) {
            return lang
        }
        if let localRaw = UserDefaults.standard.string(forKey: key),
           let lang = TranslationLanguage(rawValue: localRaw) {
            return lang
        }
        return fallback()
    }

    private static func writePersisted(
        value: TranslationLanguage,
        key: String,
        updatedAtKey: String
    ) {
        writePersisted(
            value: value,
            key: key,
            updatedAtKey: updatedAtKey,
            timestamp: Date().timeIntervalSince1970
        )
    }

    /// Write with an explicit timestamp. Used by `restore(source:target:withTimestamps:)`
    /// so a rollback doesn't advance the LWW clock past a remote write that's
    /// already in iCloud KV from another device.
    private static func writePersisted(
        value: TranslationLanguage,
        key: String,
        updatedAtKey: String,
        timestamp: TimeInterval
    ) {
        UserDefaults.standard.set(value.rawValue, forKey: key)
        UserDefaults.standard.set(timestamp, forKey: updatedAtKey)
        CloudPreferencesSync.shared.set(value.rawValue, forKey: key)
        CloudPreferencesSync.shared.set(timestamp, forKey: updatedAtKey)
    }

    /// Server cold-start：以 server 值初始化本地層 + 記 server 的**單一 group 時戳**
    /// 作後續 LWW 基準（設計 A：source/target 共用一個 `updated_at`）。
    /// **只寫 UserDefaults，不回寫 iCloud KVS** —— 對齊 `ActiveNotebookStore.applyServerState`
    /// / `ReviewSettingsStore.applyServerModeState`：避免新 Apple 裝置 cold-start 覆蓋
    /// 他裝置尚未傳播的 genuine local write。caller 須 guard「本機從未寫過」
    /// （`sourceUpdatedAt == nil && targetUpdatedAt == nil`）才呼叫。
    static func applyServerColdStart(
        source: TranslationLanguage,
        target: TranslationLanguage,
        updatedAt: TimeInterval
    ) {
        UserDefaults.standard.set(source.rawValue, forKey: sourceKey)
        UserDefaults.standard.set(updatedAt, forKey: sourceUpdatedAtKey)
        UserDefaults.standard.set(target.rawValue, forKey: targetKey)
        UserDefaults.standard.set(updatedAt, forKey: targetUpdatedAtKey)
    }

    /// Restore previously-snapshotted source/target with their original
    /// timestamps. Use this on remote-update rollback so the rolled-back
    /// values don't appear to be "newer than" concurrent writes from other
    /// devices in iCloud KV's LWW.
    /// `nil` timestamp means the snapshot was taken when no write had ever
    /// happened — in that case we clear the persistence layers entirely.
    static func restore(
        source: TranslationLanguage,
        sourceUpdatedAt: TimeInterval?,
        target: TranslationLanguage,
        targetUpdatedAt: TimeInterval?
    ) {
        if let ts = sourceUpdatedAt {
            writePersisted(value: source, key: sourceKey, updatedAtKey: sourceUpdatedAtKey, timestamp: ts)
        } else {
            // Best-effort: rollback when prev timestamp was nil means the user
            // was making their first-ever write to this setting and the remote
            // call failed. The setter already mirrored the failed value to
            // iCloud KV; we clear UserDefaults but cannot purge KV
            // (NSUbiquitousKeyValueStore has no removeObject API). We instead
            // write the resolved default back with timestamp=0 so any other
            // device with a real write (timestamp > 0) wins via LWW.
            UserDefaults.standard.removeObject(forKey: sourceKey)
            UserDefaults.standard.removeObject(forKey: sourceUpdatedAtKey)
            CloudPreferencesSync.shared.set(source.rawValue, forKey: sourceKey)
            CloudPreferencesSync.shared.set(0.0, forKey: sourceUpdatedAtKey)
        }
        if let ts = targetUpdatedAt {
            writePersisted(value: target, key: targetKey, updatedAtKey: targetUpdatedAtKey, timestamp: ts)
        } else {
            UserDefaults.standard.removeObject(forKey: targetKey)
            UserDefaults.standard.removeObject(forKey: targetUpdatedAtKey)
            CloudPreferencesSync.shared.set(target.rawValue, forKey: targetKey)
            CloudPreferencesSync.shared.set(0.0, forKey: targetUpdatedAtKey)
        }
    }
}
