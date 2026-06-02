//
//  BlockChrome.swift
//  BooksBrowser
//
//  每個 block 的外框 — 頂部含 ✕ 關閉鈕（複用既有 VocabChromeIconButton chrome）。
//

import SwiftUI

struct BlockChrome<Content: View>: View {
    let onClose: () -> Void
    @ViewBuilder var content: Content

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                VocabChromeIconButton(
                    systemImage: "xmark",
                    label: L10n.string("關閉"),
                    action: onClose
                )
            }
            .padding(AppSpacing.s2)

            content
        }
    }
}
