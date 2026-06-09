#if os(iOS)
//
//  ReadiumNavigatorJS.swift
//  Books & Vocab
//

import Foundation

enum ReadiumNavigatorJS {
    static func buildInjectionScript(
        fontFaceCSS: String,
        contentStyleCSS: String,
        underlineOpacity: Double,
        isDebugMode: String
    ) -> String {
        [
            buildBaseStyleScript(fontFaceCSS: fontFaceCSS, underlineOpacity: underlineOpacity),
            buildContentStyleScript(contentStyleCSS: contentStyleCSS),
            buildHighlightScript(),
            buildDebugScript(isDebugMode: isDebugMode),
            buildSelectionScript(isDebugMode: isDebugMode)
        ].joined(separator: "\n\n")
    }
}
#endif
