import Foundation
import Observation
import SwiftUI

enum ReviewSettingsMode: String, CaseIterable {
    case relaxed
    case intensive
    case custom

    var displayName: String {
        switch self {
        case .relaxed: return L10n.string("寬鬆")
        case .intensive: return L10n.string("密集")
        case .custom: return L10n.string("自訂")
        }
    }

    var icon: String {
        switch self {
        case .relaxed: return "heart"
        case .intensive: return "bolt"
        case .custom: return "gearshape"
        }
    }
}

enum AutoplaySpeed: String, CaseIterable {
    case slow
    case normal
    case fast

    var displayName: String {
        switch self {
        case .slow: return L10n.string("慢")
        case .normal: return L10n.string("正常")
        case .fast: return L10n.string("快")
        }
    }

    /// 卡片正面停留時間（翻面前的等待）
    var revealDelay: Duration {
        switch self {
        case .slow: return .seconds(4)
        case .normal: return .seconds(2)
        case .fast: return .seconds(1)
        }
    }

    /// 卡片背面停留時間（翻到下一張前的等待）
    var stayDelay: Duration {
        switch self {
        case .slow: return .seconds(8)
        case .normal: return .seconds(4)
        case .fast: return .seconds(2)
        }
    }

    var next: AutoplaySpeed {
        switch self {
        case .slow: return .normal
        case .normal: return .fast
        case .fast: return .slow
        }
    }
}

struct ReviewSettings {
    var mode: ReviewSettingsMode
    var customInitialIntervalHours: Double
    var customRememberedMultiplier: Double
    var customForgotMultiplier: Double
    var customMinimumIntervalHours: Double
    var customMaximumIntervalHours: Double
    var isProgressPaused: Bool = false
    var progressPausedAt: Date? = nil
    var autoplaySpeed: AutoplaySpeed = .normal
    var autoplaySoundEnabled: Bool = true

    static let `default` = ReviewSettings(
        mode: .relaxed,
        customInitialIntervalHours: 12,
        customRememberedMultiplier: 1.9,
        customForgotMultiplier: 0.45,
        customMinimumIntervalHours: 6,
        customMaximumIntervalHours: 1440,
        autoplaySpeed: .normal,
        autoplaySoundEnabled: true
    )

    var effectiveInitialIntervalHours: Double {
        switch mode {
        case .relaxed: return 24
        case .intensive: return 8
        case .custom: return customInitialIntervalHours
        }
    }

    var effectiveRememberedMultiplier: Double {
        switch mode {
        case .relaxed: return 2.5
        case .intensive: return 1.4
        case .custom: return customRememberedMultiplier
        }
    }

    var effectiveForgotMultiplier: Double {
        switch mode {
        case .relaxed: return 0.5
        case .intensive: return 0.35
        case .custom: return customForgotMultiplier
        }
    }

    var effectiveMinimumIntervalHours: Double {
        switch mode {
        case .relaxed: return 6
        case .intensive: return 4
        case .custom: return customMinimumIntervalHours
        }
    }

    var effectiveMaximumIntervalHours: Double {
        switch mode {
        case .relaxed: return 1440
        case .intensive: return 1440
        case .custom: return customMaximumIntervalHours
        }
    }

    func reviewReferenceDate(now: Date = Date()) -> Date {
        guard isProgressPaused else { return now }
        return progressPausedAt ?? now
    }

    mutating func pauseProgress(at date: Date = Date()) {
        isProgressPaused = true
        progressPausedAt = progressPausedAt ?? date
    }

    mutating func resumeProgress() {
        isProgressPaused = false
        progressPausedAt = nil
    }
}

// MARK: - Pause clock cross-device sync (Phase 2)

/// iCloud KVS 抽象 seam(僅 pause clock 需要的 Double get/set),讓
/// `ReviewSettingsStore` 可注入 fake 測 LWW。`CloudPreferencesSync` 已提供,空 extension conform。
protocol CloudKeyValueStore {
    func double(forKey key: String) -> Double?
    func set(_ value: Double, forKey key: String)
}

extension CloudPreferencesSync: CloudKeyValueStore {}

/// pause 時鐘的跨裝置狀態快照:`isPaused` + `pausedAt` 複合,共用單一 `updatedAt` 時戳。
struct PauseClockState: Equatable {
    var isPaused: Bool
    var pausedAt: Date?
    var updatedAt: Double?   // LWW timestamp(秒, since 1970);nil = 從未寫過
}

/// Last-write-wins 決議:取 `updatedAt` 較新的**整組**。兩欄位共用一個時戳確保整組
/// 原子收斂(絕不讓 isPaused 取一邊、pausedAt 取另一邊)。雙方皆無時戳則保留 local
/// (可能是 default)。pause 時鐘錯誤會讓跨裝置算出不同的 reviewReferenceDate → due 量不一致。
enum ReviewClockLWW {
    static func resolve(local: PauseClockState, cloud: PauseClockState) -> PauseClockState {
        switch (local.updatedAt, cloud.updatedAt) {
        case let (l?, c?): return c > l ? cloud : local
        case (nil, _?): return cloud
        case (_?, nil): return local
        case (nil, nil): return local
        }
    }
}

@Observable
final class ReviewSettingsStore {
    static let shared = ReviewSettingsStore()

    private enum Keys {
        static let mode = "review_settings_mode"
        static let customParams = "review_settings_custom_params"
        static let isProgressPaused = "review_settings_progress_paused"
        static let progressPausedAt = "review_settings_progress_paused_at"
        static let progressUpdatedAt = "review_settings_progress_updated_at"
        static let autoplaySpeed = "review_settings_autoplay_speed"
        static let autoplaySoundEnabled = "review_settings_autoplay_sound_enabled"
    }

    private let defaults: UserDefaults
    private let cloud: CloudKeyValueStore
    private(set) var settings: ReviewSettings

    convenience init() {
        self.init(defaults: .standard)
    }

    init(defaults: UserDefaults, cloud: CloudKeyValueStore = CloudPreferencesSync.shared) {
        self.defaults = defaults
        self.cloud = cloud
        let modeRaw = defaults.string(forKey: Keys.mode)
        let mode = modeRaw.flatMap(ReviewSettingsMode.init(rawValue:)) ?? .relaxed

        var customInitial: Double = 12
        var customRemembered: Double = 1.9
        var customForgot: Double = 0.45
        var customMin: Double = 6
        var customMax: Double = 1440
        // pause clock 三層 LWW:本地(UserDefaults)與雲端(iCloud KVS)各取一組,比
        // updatedAt 取較新整組 → 跨裝置複習基準一致(否則各裝置算出不同 due 量)。
        let resolvedPause = ReviewClockLWW.resolve(
            local: Self.readLocalPauseState(defaults),
            cloud: Self.readCloudPauseState(cloud)
        )
        let autoplaySpeedRaw = defaults.string(forKey: Keys.autoplaySpeed)
        let autoplaySpeed = autoplaySpeedRaw.flatMap(AutoplaySpeed.init(rawValue:)) ?? .normal
        let autoplaySoundEnabled = defaults.object(forKey: Keys.autoplaySoundEnabled) as? Bool ?? true

        if let data = defaults.data(forKey: Keys.customParams),
           let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Double] {
            customInitial = dict["initialIntervalHours"] ?? customInitial
            customRemembered = dict["rememberedMultiplier"] ?? customRemembered
            customForgot = dict["forgotMultiplier"] ?? customForgot
            customMin = dict["minimumIntervalHours"] ?? customMin
            customMax = dict["maximumIntervalHours"] ?? customMax
        }

        self.settings = ReviewSettings(
            mode: mode,
            customInitialIntervalHours: customInitial,
            customRememberedMultiplier: customRemembered,
            customForgotMultiplier: customForgot,
            customMinimumIntervalHours: customMin,
            customMaximumIntervalHours: customMax,
            isProgressPaused: resolvedPause.isPaused,
            progressPausedAt: resolvedPause.pausedAt,
            autoplaySpeed: autoplaySpeed,
            autoplaySoundEnabled: autoplaySoundEnabled
        )
    }

    func update(_ settings: ReviewSettings) {
        let pauseChanged = settings.isProgressPaused != self.settings.isProgressPaused
            || settings.progressPausedAt != self.settings.progressPausedAt
        self.settings = settings
        defaults.set(settings.mode.rawValue, forKey: Keys.mode)
        let dict: [String: Double] = [
            "initialIntervalHours": settings.customInitialIntervalHours,
            "rememberedMultiplier": settings.customRememberedMultiplier,
            "forgotMultiplier": settings.customForgotMultiplier,
            "minimumIntervalHours": settings.customMinimumIntervalHours,
            "maximumIntervalHours": settings.customMaximumIntervalHours
        ]
        if let data = try? JSONSerialization.data(withJSONObject: dict) {
            defaults.set(data, forKey: Keys.customParams)
        }
        // pause clock 本地層:總是寫(冪等,與既有行為一致)。
        writeLocalPause(settings.isProgressPaused, settings.progressPausedAt)
        // pause clock 雲端層 + LWW 時戳:只在 pause 真的變動時推進 updatedAt 並寫
        // iCloud(改 mode/autoplay 不該動 pause 時鐘的 LWW clock,否則跨裝置誤判較新)。
        if pauseChanged {
            let ts = Date().timeIntervalSince1970
            defaults.set(ts, forKey: Keys.progressUpdatedAt)
            cloud.set(settings.isProgressPaused ? 1.0 : 0.0, forKey: Keys.isProgressPaused)
            // resume(無錨點)時寫 0 sentinel:KVS 無 removeObject,讀取端把 0 視為 nil。
            cloud.set(settings.progressPausedAt?.timeIntervalSince1970 ?? 0, forKey: Keys.progressPausedAt)
            cloud.set(ts, forKey: Keys.progressUpdatedAt)
        }
        defaults.set(settings.autoplaySpeed.rawValue, forKey: Keys.autoplaySpeed)
        defaults.set(settings.autoplaySoundEnabled, forKey: Keys.autoplaySoundEnabled)
    }

    // MARK: - Pause clock layer reads (LWW inputs)

    static func readLocalPauseState(_ defaults: UserDefaults) -> PauseClockState {
        PauseClockState(
            isPaused: defaults.bool(forKey: Keys.isProgressPaused),
            pausedAt: (defaults.object(forKey: Keys.progressPausedAt) as? Double)
                .map(Date.init(timeIntervalSince1970:)),
            updatedAt: defaults.object(forKey: Keys.progressUpdatedAt) as? Double
        )
    }

    static func readCloudPauseState(_ cloud: CloudKeyValueStore) -> PauseClockState {
        let pausedAtRaw = cloud.double(forKey: Keys.progressPausedAt)
        return PauseClockState(
            isPaused: (cloud.double(forKey: Keys.isProgressPaused) ?? 0) != 0,
            // 0 是 resume 時寫的 sentinel(KVS 無 removeObject),視為無錨點。
            pausedAt: pausedAtRaw.flatMap { $0 == 0 ? nil : Date(timeIntervalSince1970: $0) },
            updatedAt: cloud.double(forKey: Keys.progressUpdatedAt)
        )
    }

    // MARK: - Pause clock push/rollback support (Phase 3)

    /// 當前 pause 三層的 LWW 快照(rollback 前取;updatedAt 取本地層)。
    var pauseClockSnapshot: PauseClockState {
        PauseClockState(
            isPaused: settings.isProgressPaused,
            pausedAt: settings.progressPausedAt,
            updatedAt: Self.readLocalPauseState(defaults).updatedAt
        )
    }

    /// 遠端 push 失敗時還原 pause 三層到快照(含原 updatedAt),使回滾值不會被 iCloud
    /// LWW 當成比其他裝置並發寫更新。對標 TranslationLanguage.restore。
    func restorePauseState(_ snapshot: PauseClockState) {
        var s = settings
        s.isProgressPaused = snapshot.isPaused
        s.progressPausedAt = snapshot.pausedAt
        settings = s
        writeLocalPause(snapshot.isPaused, snapshot.pausedAt)
        if let ts = snapshot.updatedAt {
            defaults.set(ts, forKey: Keys.progressUpdatedAt)
            cloud.set(snapshot.isPaused ? 1.0 : 0.0, forKey: Keys.isProgressPaused)
            cloud.set(snapshot.pausedAt?.timeIntervalSince1970 ?? 0, forKey: Keys.progressPausedAt)
            cloud.set(ts, forKey: Keys.progressUpdatedAt)
        } else {
            // 先前從未寫過:清本地時戳;KVS 無 removeObject,寫 0 讓他裝置真寫(ts>0)勝出。
            defaults.removeObject(forKey: Keys.progressUpdatedAt)
            cloud.set(0.0, forKey: Keys.progressUpdatedAt)
        }
    }

    /// Server cold-start 套用:本機從未寫過 pause 時,以 server 值初始化本地三層
    /// (記 server updatedAt 作後續 LWW 基準;不回寫 iCloud,避免與他裝置 KV 競爭)。
    func applyServerPauseState(isPaused: Bool, pausedAt: Date?, updatedAt: Double?) {
        var s = settings
        s.isProgressPaused = isPaused
        s.progressPausedAt = pausedAt
        settings = s
        writeLocalPause(isPaused, pausedAt)
        if let ts = updatedAt {
            defaults.set(ts, forKey: Keys.progressUpdatedAt)
        }
    }

    private func writeLocalPause(_ isPaused: Bool, _ pausedAt: Date?) {
        defaults.set(isPaused, forKey: Keys.isProgressPaused)
        if let at = pausedAt {
            defaults.set(at.timeIntervalSince1970, forKey: Keys.progressPausedAt)
        } else {
            defaults.removeObject(forKey: Keys.progressPausedAt)
        }
    }

    init(previewSettings: ReviewSettings) {
        self.defaults = .standard
        self.cloud = CloudPreferencesSync.shared
        self.settings = previewSettings
    }
}

private struct ReviewSettingsStoreKey: EnvironmentKey {
    static let defaultValue: ReviewSettingsStore = .shared
}

extension EnvironmentValues {
    var reviewSettingsStore: ReviewSettingsStore {
        get { self[ReviewSettingsStoreKey.self] }
        set { self[ReviewSettingsStoreKey.self] = newValue }
    }
}
