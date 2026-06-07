#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `WordDetailComponents.swift`:
/// - `VocabularySyncBadge` across all `VocabularySyncState` raw values.
/// - `WordDetailGraphLinkRow` across its visual variants (tappable / static /
///   pending shimmer / hidden), plus stress (long word + long reason).
///
/// 故意餵合成 fixture（`KGCardLinkSummary` value init / raw status Int），
/// catalog 不依賴 backend / SwiftData。兩個元件皆非 @MainActor，可直接在
/// Scenario closure 內建構。
enum WordDetailComponentScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Word Detail Components · Sync Badge") {
            Scenario("Pending", layout: .fill) {
                AppThemeContainer {
                    Self.badgeStack(status: VocabularySyncState.pending.rawValue)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Synced", layout: .fill) {
                AppThemeContainer {
                    Self.badgeStack(status: VocabularySyncState.synced.rawValue)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Failed", layout: .fill) {
                AppThemeContainer {
                    Self.badgeStack(status: VocabularySyncState.failed.rawValue)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("All states (stacked)", layout: .fill) {
                AppThemeContainer {
                    Self.allBadges
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        playbook.addScenarios(of: "Word Detail Components · Graph Link Row") {
            Scenario("Tappable links", layout: .fill) {
                AppThemeContainer {
                    Self.linkStack(rows: Self.tappableRows)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Static (no onTap)", layout: .fill) {
                AppThemeContainer {
                    Self.linkStack(rows: Self.staticRows, tappable: false)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Pending shimmer", layout: .fill) {
                AppThemeContainer {
                    Self.linkStack(rows: Self.pendingRows)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Hidden link", layout: .fill) {
                AppThemeContainer {
                    Self.linkStack(rows: Self.hiddenRows)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Mixed states + long reason", layout: .fill) {
                AppThemeContainer {
                    Self.linkStack(rows: Self.mixedRows)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }

    // MARK: - Sync Badge helpers

    private static func badgeStack(status: Int) -> some View {
        let skin = AppSkin.previewNeutral
        return VStack(alignment: .leading, spacing: 12) {
            VocabularySyncBadge(
                status: status,
                successTone: skin.palette.success,
                destructiveTone: skin.palette.destructive
            )
            Spacer(minLength: 0)
        }
        .padding(.top, 24)
        .padding(.horizontal, skin.metrics.pageHorizontalInset)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }

    private static var allBadges: some View {
        let skin = AppSkin.previewNeutral
        return VStack(alignment: .leading, spacing: 16) {
            ForEach(
                [VocabularySyncState.pending, .synced, .failed],
                id: \.rawValue
            ) { state in
                VocabularySyncBadge(
                    status: state.rawValue,
                    successTone: skin.palette.success,
                    destructiveTone: skin.palette.destructive
                )
            }
            Spacer(minLength: 0)
        }
        .padding(.top, 24)
        .padding(.horizontal, skin.metrics.pageHorizontalInset)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }

    // MARK: - Graph Link Row fixtures

    private static let tappableRows: [KGCardLinkSummary] = [
        Self.link(id: "l-1", word: "ephemeral", reason: "與 transient 同屬「短暫」語義群，互為近義連結。"),
        Self.link(id: "l-2", word: "perennial", reason: "反義對照：長存 vs 短暫，構成語義軸的兩端。"),
        Self.link(id: "l-3", word: "fleeting", reason: "同義延伸，常於文學語境中替換使用。")
    ]

    private static let staticRows: [KGCardLinkSummary] = [
        Self.link(id: "s-1", word: "lucid", reason: "詞源相關：lux（光），延伸為「清晰」。"),
        Self.link(id: "s-2", word: "translucent", reason: "共享 luc- 詞根，半透明之意。")
    ]

    private static let pendingRows: [KGCardLinkSummary] = [
        KGCardLinkSummary.pending(id: "pending-1", cardId: "card-x", word: "nebulous"),
        KGCardLinkSummary.pending(id: "pending-2", cardId: "card-x", word: "amorphous")
    ]

    private static let hiddenRows: [KGCardLinkSummary] = [
        Self.link(id: "h-1", word: "obfuscate", reason: "（此 reason 在 hidden 狀態不顯示）", hidden: true),
        Self.link(id: "h-2", word: "elucidate", reason: "（已隱藏連結）", hidden: true)
    ]

    private static let mixedRows: [KGCardLinkSummary] = [
        Self.link(
            id: "m-1",
            word: "antediluvian",
            reason: "字面為「大洪水之前」，引申為極度古老、過時；常與 archaic、obsolete 構成「陳舊」語義群，並在修辭上帶有戲謔誇張的語氣。"
        ),
        KGCardLinkSummary.pending(id: "pending-m", cardId: "card-m", word: "primordial"),
        Self.link(id: "m-3", word: "modern", reason: "時間軸反義端點。", hidden: true)
    ]

    // MARK: - Helpers

    private static func link(
        id: String,
        word: String,
        reason: String,
        hidden: Bool = false
    ) -> KGCardLinkSummary {
        KGCardLinkSummary(
            id: id,
            cardId: "card-\(id)",
            word: word,
            kind: "semantic",
            label: word,
            confidence: 0.82,
            reason: reason,
            hidden: hidden
        )
    }

    private static func linkStack(
        rows: [KGCardLinkSummary],
        tappable: Bool = true
    ) -> some View {
        let skin = AppSkin.previewNeutral
        return VStack(spacing: 0) {
            ForEach(rows) { row in
                WordDetailGraphLinkRow(
                    link: row,
                    onTap: (tappable && !row.isPending && !row.isHidden) ? {} : nil,
                    onDelete: {},
                    onHide: {},
                    onUnhide: {}
                )
                .padding(.horizontal, skin.metrics.listRowHorizontalInset)
                Divider().opacity(0.4)
            }
            Spacer(minLength: 0)
        }
        .padding(.top, 16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }
}
#endif
