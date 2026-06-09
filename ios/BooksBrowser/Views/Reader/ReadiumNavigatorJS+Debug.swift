#if os(iOS)
//
//  ReadiumNavigatorJS+Debug.swift
//  Books & Vocab
//

import Foundation

extension ReadiumNavigatorJS {
    static func buildDebugScript(isDebugMode: String) -> String {
        """
        // 全版標記：Token Calculator 除錯效果
        window.__toggleDebugBoxes = function(enabled) {
            if (!enabled) {
                document.querySelectorAll('.debug-word-box').forEach(function(el) {
                    if (el.classList.contains('vocab-word') || el.classList.contains('active-word')) {
                        el.classList.remove('debug-word-box');
                        el.style.backgroundColor = '';
                        el.style.outline = '';
                    } else {
                        var parent = el.parentNode;
                        while(el.firstChild) parent.insertBefore(el.firstChild, el);
                        parent.removeChild(el);
                        parent.normalize();
                    }
                });
                return;
            }
            
            if (document.querySelector('.debug-word-box')) return;
            
            var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
            var textNodes = [];
            while (walker.nextNode()) {
                var parent = walker.currentNode.parentElement;
                if (parent && (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE')) continue;
                textNodes.push(walker.currentNode);
            }
            
            textNodes.forEach(function(node) {
                var parent = node.parentElement;
                if (!parent) return;
                if (parent.classList.contains('vocab-word') || parent.classList.contains('active-word')) {
                    if (!parent.classList.contains('debug-word-box')) {
                        parent.classList.add('debug-word-box');
                    }
                    return;
                }
                if (!(/[a-zA-Z'\\\\-]+/.test(node.textContent))) return;
                
                var fragment = document.createDocumentFragment();
                var parts = node.textContent.split(/([a-zA-Z'\\\\-]+)/);
                parts.forEach(function(part) {
                    if (/[a-zA-Z'\\\\-]+/.test(part)) {
                        var span = document.createElement('span');
                        span.className = 'debug-word-box';
                        span.textContent = part;
                        fragment.appendChild(span);
                    } else if (part.length > 0) {
                        fragment.appendChild(document.createTextNode(part));
                    }
                });
                if (fragment.childNodes.length > 0) {
                    parent.replaceChild(fragment, node);
                }
            });
        };

        // 初始自動繪製 Token 黑盒
        if (\(isDebugMode)) {
            setTimeout(function() { window.__toggleDebugBoxes(true); }, 500);
        }
        """
    }
}
#endif
