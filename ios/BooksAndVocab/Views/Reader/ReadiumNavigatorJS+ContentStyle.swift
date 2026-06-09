#if os(iOS)
//
//  ReadiumNavigatorJS+ContentStyle.swift
//  Books & Vocab
//

import Foundation

extension ReadiumNavigatorJS {
    static func buildContentStyleScript(contentStyleCSS: String) -> String {
        """
        (function() {
            function ensureContentStyleTag() {
                var style = document.getElementById('reader-content-style');
                if (!style) {
                    style = document.createElement('style');
                    style.id = 'reader-content-style';
                    document.head.appendChild(style);
                }
                return style;
            }

            window.__applyReaderContentStyle = function(css) {
                ensureContentStyleTag().textContent = css;
            };

            window.__applyReaderContentStyle(`\(contentStyleCSS)`);
        })();
        """
    }
}
#endif
