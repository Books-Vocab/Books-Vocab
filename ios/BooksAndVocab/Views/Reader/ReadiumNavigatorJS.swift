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
        var scripts = [
            buildBaseStyleScript(fontFaceCSS: fontFaceCSS, underlineOpacity: underlineOpacity),
            buildContentStyleScript(contentStyleCSS: contentStyleCSS),
            buildHighlightScript()
        ]
#if DEBUG
        scripts.append(buildDebugScript(isDebugMode: isDebugMode))
#endif
        scripts.append(buildSelectionScript(isDebugMode: isDebugMode))
        return scripts.joined(separator: "\n\n")
    }
}
#endif
