//
//  KGService+ServerURL.swift
//  Books & Vocab
//
//  Server URL configuration — production constant + DEBUG-only local override.
//

import Foundation

extension KGService {
    #if DEBUG
    enum DebugServerMode: String {
        case remote
        case local
    }

    private enum DebugServerKeys {
        static let mode = "kg_debug_server_mode"
        static let localURL = "kg_debug_local_server_url"
    }
    #endif

    // MARK: - URL Constants

    static let deployedServerURL = "https://wordnexus.lol"

    /// Hardcoded last-resort fallback URL — guaranteed to parse, used only if both
    /// the user-configured `serverURL` and `deployedServerURL` fail to parse.
    static let fallbackURL = URL(string: "https://wordnexus.lol")!

    #if DEBUG
    private static let defaultLocalServerURL = "http://127.0.0.1:8000"
    #endif

    // MARK: - Server URL Management

    static func setServerURL(_ url: String) {
        #if DEBUG
        let normalized = normalizeServerURL(url)
        if normalized == deployedServerURL {
            useProductionServer()
            return
        }
        UserDefaults.standard.set(normalized, forKey: DebugServerKeys.localURL)
        UserDefaults.standard.set(DebugServerMode.local.rawValue, forKey: DebugServerKeys.mode)
        #else
        _ = url
        #endif
    }

    static func getServerURL() -> String {
        #if DEBUG
        switch getDebugServerMode() {
        case .remote:
            return deployedServerURL
        case .local:
            return getDebugLocalServerURL()
        }
        #else
        return deployedServerURL
        #endif
    }

    #if DEBUG
    static func getDebugServerMode() -> DebugServerMode {
        let raw = UserDefaults.standard.string(forKey: DebugServerKeys.mode) ?? DebugServerMode.remote.rawValue
        return DebugServerMode(rawValue: raw) ?? .remote
    }

    static func getDebugLocalServerURL() -> String {
        let stored = UserDefaults.standard.string(forKey: DebugServerKeys.localURL)
        return normalizeServerURL(stored ?? defaultLocalServerURL)
    }

    static func setDebugLocalServerURL(_ url: String) {
        UserDefaults.standard.set(normalizeServerURL(url), forKey: DebugServerKeys.localURL)
    }

    static func useProductionServer() {
        UserDefaults.standard.set(DebugServerMode.remote.rawValue, forKey: DebugServerKeys.mode)
    }

    static func useLocalServer() {
        UserDefaults.standard.set(DebugServerMode.local.rawValue, forKey: DebugServerKeys.mode)
    }

    private static func normalizeServerURL(_ url: String) -> String {
        let trimmed = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return defaultLocalServerURL }
        return trimmed.hasSuffix("/") ? String(trimmed.dropLast()) : trimmed
    }
    #endif
}
