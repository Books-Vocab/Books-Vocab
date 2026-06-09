#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `LinkReasonSheet` — the bottom sheet shown when a user
/// taps a card-link chip in the vocabulary detail surface. It renders a synthetic
/// `KGCardLinkSummary` (label + word + reason) plus a navigate CTA and an optional
/// hide action.
///
/// 全部餵合成的 `KGCardLinkSummary`，不接 Presenter / SwiftData / backend。
/// 涵蓋：一般長度 reason、極短 reason、超長 reason（stress 換行）、
/// 無 hide 動作、空 reason 邊界。
enum LinkReasonSheetScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Link Reason Sheet") {
            Scenario("Loaded · medium reason", layout: .fill) {
                sheet(link: Self.mediumReason, withHide: true)
            }
            Scenario("Short reason", layout: .fill) {
                sheet(link: Self.shortReason, withHide: true)
            }
            Scenario("Long reason (stress)", layout: .fill) {
                sheet(link: Self.longReason, withHide: true)
            }
            Scenario("No hide action", layout: .fill) {
                sheet(link: Self.mediumReason, withHide: false)
            }
            Scenario("Empty reason", layout: .fill) {
                sheet(link: Self.emptyReason, withHide: true)
            }
        }
    }

    // MARK: - Sheet helper

    private static func sheet(link: KGCardLinkSummary, withHide: Bool) -> some View {
        AppThemeContainer {
            LinkReasonSheet(
                link: link,
                onNavigate: {},
                onHide: withHide ? {} : nil
            )
            .appSkin(AppSkin.previewNeutral)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background(AppSkin.previewNeutral.palette.pageBackground.ignoresSafeArea())
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: - Fixtures

    private static func link(
        word: String,
        kind: String,
        label: String,
        confidence: Double,
        reason: String
    ) -> KGCardLinkSummary {
        KGCardLinkSummary(
            id: UUID().uuidString,
            cardId: UUID().uuidString,
            word: word,
            kind: kind,
            label: label,
            confidence: confidence,
            reason: reason,
            hidden: false
        )
    }

    private static let mediumReason = link(
        word: "forestall",
        kind: "shares_usage",
        label: "相似用法",
        confidence: 0.82,
        reason: "兩個單字都帶有「預先採取行動以阻止某事發生」的語意，常出現在談判、政策與風險管理的語境中，可互相對照記憶。"
    )

    private static let shortReason = link(
        word: "deft",
        kind: "synonym",
        label: "同義詞",
        confidence: 0.95,
        reason: "皆指動作靈巧。"
    )

    private static let longReason = link(
        word: "schadenfreude",
        kind: "shares_root",
        label: "相關概念",
        confidence: 0.61,
        reason: "兩者都描述「他人不幸所引發的情緒反應」，但細微差異值得注意：前者源自德語 Schaden（傷害）+ Freude（喜悅），強調看到他人受挫時心中浮現的隱密快感；後者則偏向中性的旁觀情緒，不必然帶有惡意。理解這條連結有助於在閱讀文學評論、心理學文本與社會議題討論時，準確掌握作者的情感立場與修辭意圖，並避免在翻譯時誤把幸災樂禍的貶義色彩抹平成中立描述。"
    )

    private static let emptyReason = link(
        word: "laconic",
        kind: "shares_usage",
        label: "相似用法",
        confidence: 0.4,
        reason: ""
    )
}
#endif
