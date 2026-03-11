import SwiftUI
import UIKit

struct KnowledgeGraphNode: Identifiable, Equatable {
    let id: String
    let word: String
    let tier: String?
    let degree: Int
}

struct KnowledgeGraphEdge: Identifiable, Equatable {
    let id: String
    let from: String
    let to: String
    let kind: String
}

struct KnowledgeGraphTheme: Equatable {
    let backgroundHex: String
    let tierHexes: [String: String]
    let edgeHexes: [String: String]
    let labelHex: String
    let labelShadowHex: String
}

enum KnowledgeGraphPresentation {
    static func nodes(
        from entries: [VocabularyEntry],
        links: [KGGraphLink],
        now: Date = Date()
    ) -> [KnowledgeGraphNode] {
        var degreeMap: [String: Int] = [:]
        for link in links {
            degreeMap[link.fromId, default: 0] += 1
            degreeMap[link.toId, default: 0] += 1
        }

        return entries.compactMap { entry in
            guard entry.isSynced, entry.syncAction != .delete, let kgId = entry.kgCardId else { return nil }
            let degree = degreeMap[kgId] ?? 0
            guard degree > 0 else { return nil }
            let tier = entry.isArchived ? "archived" : reviewTone(for: entry, now: now)
            return KnowledgeGraphNode(
                id: kgId,
                word: entry.word,
                tier: tier,
                degree: degree
            )
        }
    }

    private static func reviewTone(for entry: VocabularyEntry, now: Date) -> String {
        guard entry.reviewCount > 0 else { return "gray" }
        let startDate = entry.lastReviewedAt ?? entry.dateAdded
        let interval = max(entry.nextReviewAt.timeIntervalSince(startDate), 60)
        let elapsed = max(0, now.timeIntervalSince(startDate))
        let fraction = min(max(elapsed / interval, 0), 1)
        if fraction >= 1 { return "red" }
        if fraction >= 0.72 { return "orange" }
        if fraction >= 0.4 { return "yellow" }
        return "green"
    }

    static func edges(
        from links: [KGGraphLink],
        validNodeIDs: Set<String>
    ) -> [KnowledgeGraphEdge] {
        links.compactMap { link in
            guard validNodeIDs.contains(link.fromId), validNodeIDs.contains(link.toId) else {
                return nil
            }
            return KnowledgeGraphEdge(
                id: link.id,
                from: link.fromId,
                to: link.toId,
                kind: link.kind
            )
        }
    }

    static func theme(for skin: VocabSkin) -> KnowledgeGraphTheme {
        KnowledgeGraphTheme(
            backgroundHex: cssHex(skin.palette.pageBackground),
            tierHexes: [
                "green": cssHex(skin.palette.success),
                "yellow": cssHex(skin.palette.tierIntermediate),
                "orange": cssHex(skin.palette.tierAdvanced),
                "red": cssHex(skin.palette.destructive),
                "gray": cssHex(skin.palette.secondaryText),
                "archived": cssHex(skin.palette.quaternaryText)
            ],
            edgeHexes: [
                "confusable": cssHex(skin.palette.tierAdvanced),
                "contrasts_with": cssHex(skin.palette.link),
                "shares_usage": cssHex(skin.palette.success)
            ],
            labelHex: cssHex(skin.palette.primaryText),
            labelShadowHex: cssHex(skin.palette.pageBackground)
        )
    }

    static func emptyState(
        isLoggedIn: Bool,
        isLoading: Bool,
        errorMessage: String?,
        nodes: [KnowledgeGraphNode]
    ) -> KnowledgeGraphPresenter.State.EmptyState? {
        if !isLoggedIn {
            return .init(
                title: "需登入帳號".localized,
                systemImage: "person.crop.circle.badge.exclamationmark",
                description: "請至設定中登入以查閱您的知識關聯。".localized
            )
        }
        if isLoading {
            return .init(
                title: "正在載入關聯圖...".localized,
                systemImage: "point.3.connected.trianglepath.dotted",
                description: "正在向伺服器拉取知識連結與節點資訊。".localized
            )
        }
        if let errorMessage {
            return .init(
                title: "載入失敗".localized,
                systemImage: "exclamationmark.triangle",
                description: errorMessage
            )
        }
        if nodes.isEmpty {
            return .init(
                title: "知識圖譜為空".localized,
                systemImage: "point.3.connected.trianglepath.dotted",
                description: "知識庫中尚無單字，或尚未與伺服器同步。".localized
            )
        }
        return nil
    }

    private static func cssHex(_ color: Color) -> String {
        var r: CGFloat = 0
        var g: CGFloat = 0
        var b: CGFloat = 0
        var a: CGFloat = 0
        UIColor(color).getRed(&r, green: &g, blue: &b, alpha: &a)
        return String(format: "#%02X%02X%02X", Int(r * 255), Int(g * 255), Int(b * 255))
    }
}
