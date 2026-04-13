#if os(iOS)
//
//  PodcastPlayerView.swift
//  BooksBrowser
//
//  ⚠️ MINIMAL STUB — 第三輪 bisect（PR #368/#370 未解 crash）
//
//  PR #370 的 stub 仍保留整個 struct 的 property wrappers（@Query /
//  @State default values / @Environment / @AppStorage），這些在 struct
//  instantiate 時即被 DynamicProperty.update() 觸發，body 是否用到它們
//  無關。本輪把 PodcastPlayerView 整個壓縮成「只有 episodeId + Text」的
//  絕對最小 struct，零 property wrapper、零 helper method。
//
//  判讀：
//  - tap 後不再 crash → 根因鎖定在原 struct 的 property wrapper init
//    （最可疑：@Query allVocabulary / @AppStorage / 某個 @State default
//    的交互）。下一輪精準恢復各段落分輪 bisect。
//  - tap 後仍 crash → 根因不在 PodcastPlayerView 內部，轉查
//    PodcastEpisodeListView 側（LazyVStack + closure NavigationLink + 2
//    層 push + parent BookshelfView 的 navigationDestination(for: Book.self)
//    交互）。
//
//  原 full player 實作見 git log 897f660/3c75ef5/58881b3 之前的版本；
//  bisect 結束後 revert 並針對性重寫。
//

import SwiftUI

struct PodcastPlayerView: View {
    let episodeId: String

    var body: some View {
        VStack(spacing: 12) {
            Text("MINIMAL STUB")
                .font(.headline)
            Text("episodeId:")
            Text(episodeId)
                .font(.system(.body, design: .monospaced))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .navigationBarTitleDisplayMode(.inline)
    }
}
#endif
