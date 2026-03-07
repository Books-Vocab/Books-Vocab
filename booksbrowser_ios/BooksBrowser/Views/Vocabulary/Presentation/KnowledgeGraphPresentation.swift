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
        links: [KGGraphLink]
    ) -> [KnowledgeGraphNode] {
        var degreeMap: [String: Int] = [:]
        for link in links {
            degreeMap[link.fromId, default: 0] += 1
            degreeMap[link.toId, default: 0] += 1
        }

        return entries.compactMap { entry in
            guard entry.isSynced, let kgId = entry.kgCardId else { return nil }
            let degree = degreeMap[kgId] ?? 0
            guard degree > 0 else { return nil }
            return KnowledgeGraphNode(
                id: kgId,
                word: entry.word,
                tier: entry.difficultyTier,
                degree: degree
            )
        }
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
                "core": cssHex(skin.palette.success),
                "intermediate": cssHex(skin.tierColor(for: "intermediate")),
                "advanced": cssHex(skin.tierColor(for: "advanced")),
                "rare": cssHex(skin.palette.destructive),
                "unknown": cssHex(skin.palette.secondaryText)
            ],
            edgeHexes: [
                "confusable": cssHex(skin.tierColor(for: "advanced")),
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
                title: "需登入帳號",
                systemImage: "person.crop.circle.badge.exclamationmark",
                description: "請至設定中登入以查閱您的知識關聯。"
            )
        }
        if isLoading {
            return .init(
                title: "正在載入關聯圖...",
                systemImage: "point.3.connected.trianglepath.dotted",
                description: "正在向伺服器拉取知識連結與節點資訊。"
            )
        }
        if let errorMessage {
            return .init(
                title: "載入失敗",
                systemImage: "exclamationmark.triangle",
                description: errorMessage
            )
        }
        if nodes.isEmpty {
            return .init(
                title: "知識圖譜為空",
                systemImage: "point.3.connected.trianglepath.dotted",
                description: "知識庫中尚無單字，或尚未與伺服器同步。"
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
