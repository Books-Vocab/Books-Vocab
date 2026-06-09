#if os(iOS)
//
//  ReadiumNavigatorJS+BaseStyle.swift
//  Books & Vocab
//

import Foundation

extension ReadiumNavigatorJS {
    static func buildBaseStyleScript(
        fontFaceCSS: String,
        underlineOpacity: Double
    ) -> String {
        """
        (function() {
            // Inject custom @font-face declarations so WKWebView can use bundled fonts
            if (!document.getElementById('custom-font-faces')) {
                var fontStyle = document.createElement('style');
                fontStyle.id = 'custom-font-faces';
                fontStyle.textContent = `\(fontFaceCSS)`;
                document.head.appendChild(fontStyle);
            }

            if (!document.getElementById('reader-base-style')) {
                var style = document.createElement('style');
                style.id = 'reader-base-style';
                document.head.appendChild(style);
            }

            document.getElementById('reader-base-style').textContent = `
                :root {
                    --vocab-opacity: \(underlineOpacity);
                }

                html, body {
                    touch-action: manipulation;
                    overscroll-behavior-x: none;
                }

                * {
                    text-align: left !important;
                }

                .debug-tap-point {
                    position: absolute;
                    width: 6px;
                    height: 6px;
                    background-color: red;
                    border-radius: 50%;
                    transform: translate(-50%, -50%);
                    z-index: 9999;
                    pointer-events: none;
                }
                .debug-hit-box {
                    position: absolute;
                    z-index: 9998;
                    pointer-events: none;
                    border-width: 1px;
                    border-style: solid;
                }
                .debug-hit-box.success {
                    background-color: rgba(0, 255, 0, 0.1);
                    border-color: rgba(0, 255, 0, 0.5);
                }
                .debug-hit-box.fail {
                    background-color: rgba(255, 255, 0, 0.1);
                    border-color: rgba(255, 255, 0, 0.5);
                }

                .debug-word-box {
                    outline: 1px solid rgba(130, 130, 130, 0.40);
                    border-radius: 2px;
                    background-color: transparent !important;
                }
            `;
        })();
        """
    }
}
#endif
