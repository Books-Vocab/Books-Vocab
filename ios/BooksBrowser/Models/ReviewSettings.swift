import Foundation

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

struct ReviewSettings {
    var mode: ReviewSettingsMode
    var customInitialIntervalHours: Double
    var customRememberedMultiplier: Double
    var customForgotMultiplier: Double
    var customMinimumIntervalHours: Double
    var customMaximumIntervalHours: Double

    static let `default` = ReviewSettings(
        mode: .relaxed,
        customInitialIntervalHours: 12,
        customRememberedMultiplier: 1.9,
        customForgotMultiplier: 0.45,
        customMinimumIntervalHours: 6,
        customMaximumIntervalHours: 1440
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
}

final class ReviewSettingsStore: ObservableObject {
    static let shared = ReviewSettingsStore()

    private enum Keys {
        static let mode = "review_settings_mode"
        static let customParams = "review_settings_custom_params"
    }

    @Published private(set) var settings: ReviewSettings

    private init() {
        let defaults = UserDefaults.standard
        let modeRaw = defaults.string(forKey: Keys.mode)
        let mode = modeRaw.flatMap(ReviewSettingsMode.init(rawValue:)) ?? .relaxed

        var customInitial: Double = 12
        var customRemembered: Double = 1.9
        var customForgot: Double = 0.45
        var customMin: Double = 6
        var customMax: Double = 1440

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
            customMaximumIntervalHours: customMax
        )
    }

    func update(_ settings: ReviewSettings) {
        self.settings = settings
        let defaults = UserDefaults.standard
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
    }

    init(previewSettings: ReviewSettings) {
        self.settings = previewSettings
    }
}
