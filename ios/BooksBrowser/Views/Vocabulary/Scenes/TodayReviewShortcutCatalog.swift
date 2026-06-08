#if os(iOS)
import Foundation

struct TodayReviewShortcutHint: Identifiable, Equatable {
    let id: String
    let key: String
    let label: String
    var isPrimary = false
}

enum TodayReviewShortcutCatalog {
    static var shuffleLabel: String { L10n.string("洗牌") }
    static var firstRunHint: String { L10n.string("可用方向鍵評分，按 Space 展開答案") }
    static var overlayTitle: String { L10n.string("快捷鍵") }
    static var doneLabel: String { L10n.string("完成") }
    static var reviewSectionTitle: String { L10n.string("複習") }
    static var navigationSectionTitle: String { L10n.string("導覽") }
    static var sessionSectionTitle: String { L10n.string("工作階段") }

    static func activeHints(
        hasCurrentCard: Bool,
        revealStage: TodayReviewRevealStage,
        isAutoPlaying: Bool,
        isAutoPlayPaused: Bool
    ) -> [TodayReviewShortcutHint] {
        guard hasCurrentCard else {
            return completionHints
        }
        return isAutoPlaying
            ? autoplayHints(isAutoPlayPaused: isAutoPlayPaused)
            : reviewHints(revealStage: revealStage)
    }

    static var completionHints: [TodayReviewShortcutHint] {
        [
            .init(id: "esc", key: "Esc", label: L10n.string("返回"), isPrimary: true),
            .init(id: "help", key: "?", label: overlayTitle)
        ]
    }

    static func reviewHints(revealStage: TodayReviewRevealStage) -> [TodayReviewShortcutHint] {
        let spaceLabel = revealStage == .front ? L10n.string("展開") : L10n.string("收回")
        return [
            .init(id: "space", key: "Space", label: spaceLabel, isPrimary: true),
            .init(id: "left", key: "←", label: L10n.string("忘記"), isPrimary: true),
            .init(id: "right", key: "→", label: L10n.string("記得"), isPrimary: true),
            .init(id: "detail", key: "D", label: L10n.string("詳情")),
            .init(id: "help", key: "?", label: overlayTitle)
        ]
    }

    static func autoplayHints(isAutoPlayPaused: Bool) -> [TodayReviewShortcutHint] {
        [
            .init(
                id: "pause",
                key: "P",
                label: isAutoPlayPaused ? L10n.string("繼續") : L10n.string("暫停"),
                isPrimary: true
            ),
            .init(id: "left", key: "←", label: L10n.string("上一張"), isPrimary: true),
            .init(id: "right", key: "→", label: L10n.string("下一張"), isPrimary: true),
            .init(id: "esc", key: "Esc", label: L10n.string("關閉")),
            .init(id: "help", key: "?", label: overlayTitle)
        ]
    }

    static var navigationHints: [TodayReviewShortcutHint] {
        [
            .init(id: "up", key: "↑", label: L10n.string("上一張")),
            .init(id: "down", key: "↓", label: L10n.string("下一張")),
            .init(id: "shuffle", key: "S", label: shuffleLabel),
            .init(id: "detail", key: "D", label: L10n.string("查看詳情"))
        ]
    }

    static var sessionHints: [TodayReviewShortcutHint] {
        [
            .init(id: "play", key: "P", label: L10n.string("自動播放")),
            .init(id: "esc", key: "Esc", label: L10n.string("關閉")),
            .init(id: "help", key: "?", label: L10n.string("顯示快捷鍵"))
        ]
    }
}
#endif
