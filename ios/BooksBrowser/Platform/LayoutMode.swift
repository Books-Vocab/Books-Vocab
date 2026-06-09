//
//  LayoutMode.swift
//  Books & Vocab
//
//  統一 compact/regular layout 判斷

import SwiftUI

enum LayoutMode: Equatable {
    case compact
    case regular

    /// Notebook grid card 鎖定 aspect ratio — 整卡（含 cover + metadata）3:4 直式。
    /// 修掉左右兩本 metadata 高度不齊撐高破節奏的 bug。
    static let notebookCardAspectRatio: CGFloat = 3.0 / 4.0

    init(horizontalSizeClass: UserInterfaceSizeClass?) {
        self = (horizontalSizeClass == .compact) ? .compact : .regular
    }

    /// 是否使用 inline detail panel（而非 sheet）
    var usesInlineDetail: Bool {
        self == .regular
    }

    /// 內容最大寬度
    var contentMaxWidth: CGFloat {
        switch self {
        case .compact: return .infinity
        case .regular: return 720
        }
    }

    /// 書架封面高度
    var bookshelfCoverHeight: CGFloat {
        switch self {
        case .compact: return AppBookshelfMetrics.coverHeightCompact
        case .regular: return AppBookshelfMetrics.coverHeightRegular
        }
    }

    /// 書架 grid item
    var bookshelfGridItem: GridItem {
        switch self {
        case .compact: return GridItem(.adaptive(minimum: 150, maximum: 200), spacing: AppShellMetrics.sectionSpacing)
        case .regular: return GridItem(.adaptive(minimum: 180, maximum: 240), spacing: AppShellMetrics.sectionSpacing)
        }
    }

    /// 單字本書架 grid item
    var notebookGridItem: GridItem {
        switch self {
        case .compact: return GridItem(.adaptive(minimum: 160, maximum: 200), spacing: AppShellMetrics.sectionSpacing)
        case .regular: return GridItem(.adaptive(minimum: 200, maximum: 260), spacing: AppShellMetrics.sectionSpacing)
        }
    }

    #if os(iOS)
    /// Reader header title max width
    var readerTitleMaxWidth: CGFloat {
        switch self {
        case .compact: return ReaderPresentationMetrics.Header.titleMaxWidth
        case .regular: return ReaderPresentationMetrics.Header.titleMaxWidthRegular
        }
    }
    #endif
}
