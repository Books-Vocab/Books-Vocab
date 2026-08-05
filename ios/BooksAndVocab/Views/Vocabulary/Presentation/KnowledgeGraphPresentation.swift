import SwiftUI

struct KnowledgeGraphNode: Identifiable, Equatable {
    let id: String
    let word: String
    let tier: String?
    let colorHex: String?
    let ratio: Double?
    let degree: Int
    let badgeSystemImage: String?

    init(
        id: String, word: String, tier: String?, colorHex: String?,
        ratio: Double?, degree: Int, badgeSystemImage: String? = nil
    ) {
        self.id = id
        self.word = word
        self.tier = tier
        self.colorHex = colorHex
        self.ratio = ratio
        self.degree = degree
        self.badgeSystemImage = badgeSystemImage
    }
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
        showIsolatedNodes: Bool = false,
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
            guard showIsolatedNodes || degree > 0 else { return nil }

            let tier: String
            let colorHex: String?
            let nodeRatio: Double?
            if entry.isArchived {
                return nil
            } else if entry.cardRole == .dictionary {
                tier = "dictionary"
                colorHex = nil
                nodeRatio = nil
            } else if entry.reviewCount == 0 {
                tier = "gray"
                colorHex = nil
                nodeRatio = nil
            } else {
                tier = "gradient"
                let r = reviewRatio(for: entry, now: now)
                colorHex = ReviewGradient.cssHex(for: r)
                nodeRatio = r
            }

            return KnowledgeGraphNode(
                id: kgId,
                word: entry.word,
                tier: tier,
                colorHex: colorHex,
                ratio: nodeRatio,
                degree: degree,
                badgeSystemImage: entry.cardRole == .dictionary ? "book.closed" : nil
            )
        }
    }

    private static func reviewRatio(for entry: VocabularyEntry, now: Date) -> Double {
        let startDate = entry.lastReviewedAt ?? entry.dateAdded
        let interval = max(entry.nextReviewAt.timeIntervalSince(startDate), 60)
        let elapsed = max(0, now.timeIntervalSince(startDate))
        return max(elapsed / interval, 0)
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

    static func theme(for skin: AppSkin) -> KnowledgeGraphTheme {
        KnowledgeGraphTheme(
            backgroundHex: cssHex(skin.palette.pageBackground),
            tierHexes: [
                "gray": cssHex(skin.palette.quaternaryText),
                "dictionary": cssHex(skin.palette.tertiaryText),
                "archived": cssHex(skin.palette.quaternaryText)
            ],
            edgeHexes: [
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
        nodes: [KnowledgeGraphNode],
        syncedEntryCount: Int = 0,
        linkCount: Int = 0,
        showsIsolatedNodes: Bool = false,
        onRetry: (() -> Void)? = nil
    ) -> KnowledgeGraphPresenter.State.EmptyState? {
        if !isLoggedIn {
            return .init(
                title: KnowledgeGraphCopy.loginTitle,
                systemImage: "person.crop.circle.badge.exclamationmark",
                description: KnowledgeGraphCopy.loginDescription
            )
        }
        if isLoading {
            return .init(
                title: KnowledgeGraphCopy.loadingTitle,
                systemImage: "point.3.connected.trianglepath.dotted",
                description: KnowledgeGraphCopy.loadingDescription
            )
        }
        if let errorMessage {
            return .init(
                title: KnowledgeGraphCopy.errorTitle,
                systemImage: "exclamationmark.triangle",
                description: errorMessage,
                action: onRetry.map { retry in
                    AppEmptyStateAction(
                        title: KnowledgeGraphCopy.retryTitle,
                        systemImage: "arrow.clockwise",
                        handler: retry
                    )
                }
            )
        }
        if nodes.isEmpty {
            // 細分：有同步單字但無連結 vs 完全無單字
            if syncedEntryCount > 0 && linkCount == 0 {
                return .init(
                    title: KnowledgeGraphCopy.noLinksTitle,
                    systemImage: "point.3.connected.trianglepath.dotted",
                    description: KnowledgeGraphCopy.noLinksDescription
                )
            }
            if syncedEntryCount > 0 && !showsIsolatedNodes {
                return .init(
                    title: KnowledgeGraphCopy.noLinkedNodesTitle,
                    systemImage: "point.3.connected.trianglepath.dotted",
                    description: KnowledgeGraphCopy.noLinkedNodesDescription
                )
            }
            return .init(
                title: KnowledgeGraphCopy.emptyGraphTitle,
                systemImage: "point.3.connected.trianglepath.dotted",
                description: KnowledgeGraphCopy.emptyGraphDescription
            )
        }
        return nil
    }

    private static func cssHex(_ color: Color) -> String {
        var r: CGFloat = 0
        var g: CGFloat = 0
        var b: CGFloat = 0
        var a: CGFloat = 0
        PlatformColor(color).getRed(&r, green: &g, blue: &b, alpha: &a)
        return String(format: "#%02X%02X%02X", Int(r * 255), Int(g * 255), Int(b * 255))
    }
}
