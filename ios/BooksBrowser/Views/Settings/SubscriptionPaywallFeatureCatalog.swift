#if os(iOS)
import SwiftUI

struct SubscriptionPaywallFeatureDescriptor: Equatable {
    let title: String
    let marketingDescription: String?
    let freeMark: SettingsPlanComparisonRow.Mark
    let proMark: SettingsPlanComparisonRow.Mark
    let includeInActiveList: Bool
}

enum SubscriptionPaywallFeatureCatalog {
    // Computed (not `static let`) so each access re-resolves `L10n.string` against the
    // current `AppLanguageStore` language — in-app locale switches must update the paywall.
    static var descriptors: [SubscriptionPaywallFeatureDescriptor] {
        [
        .init(
            title: L10n.string("閱讀器（EPUB/PDF/TXT/MD）"),
            marketingDescription: nil,
            freeMark: .check,
            proMark: .check,
            includeInActiveList: false
        ),
        .init(
            title: L10n.string("本地生詞捕捉"),
            marketingDescription: nil,
            freeMark: .check,
            proMark: .check,
            includeInActiveList: false
        ),
        .init(
            title: L10n.string("AI 翻譯與語境解釋"),
            marketingDescription: L10n.string("閱讀時即時查詢翻譯與語境"),
            freeMark: .label(L10n.string("有限")),
            proMark: .check,
            includeInActiveList: true
        ),
        .init(
            title: L10n.string("雲端同步與跨裝置狀態"),
            marketingDescription: L10n.string("生詞與閱讀進度跨裝置同步"),
            freeMark: .label(L10n.string("有限")),
            proMark: .check,
            includeInActiveList: true
        ),
        .init(
            title: L10n.string("知識圖譜與關聯卡片"),
            marketingDescription: L10n.string("視覺化詞彙關聯與間隔複習"),
            freeMark: .label(L10n.string("有限")),
            proMark: .check,
            includeInActiveList: true
        ),
        .init(
            title: L10n.string("間隔複習（Today Review）"),
            marketingDescription: nil,
            freeMark: .label(L10n.string("有限")),
            proMark: .check,
            includeInActiveList: false
        ),
        .init(
            title: L10n.string("Podcast 跨集播放"),
            marketingDescription: nil,
            freeMark: .label(L10n.string("有限")),
            proMark: .check,
            includeInActiveList: false
        ),
        .init(
            title: L10n.string("每日 AI 額度"),
            marketingDescription: nil,
            freeMark: .label("1x"),
            proMark: .label("10x"),
            includeInActiveList: false
        )
        ]
    }

    static var comparisonRows: [SettingsPlanComparisonRow] {
        descriptors.map {
            SettingsPlanComparisonRow(
                title: $0.title,
                freeMark: $0.freeMark,
                proMark: $0.proMark
            )
        }
    }

    static func activeItems(successTone: Color) -> [SettingsSubscriptionFeatureItem] {
        descriptors
            .filter(\.includeInActiveList)
            .map {
                SettingsSubscriptionFeatureItem(
                    title: $0.title,
                    description: nil,
                    icon: "checkmark.circle.fill",
                    tone: successTone
                )
            }
    }

    static func paywallItems(accentTone: Color) -> [SettingsSubscriptionFeatureItem] {
        descriptors
            .compactMap { descriptor in
                guard let marketingDescription = descriptor.marketingDescription else {
                    return nil
                }
                return SettingsSubscriptionFeatureItem(
                    title: descriptor.title,
                    description: marketingDescription,
                    icon: "sparkles",
                    tone: accentTone
                )
            }
    }
}
#endif
