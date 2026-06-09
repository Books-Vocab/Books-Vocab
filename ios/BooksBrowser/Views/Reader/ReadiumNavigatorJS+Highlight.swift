#if os(iOS)
//
//  ReadiumNavigatorJS+Highlight.swift
//  Books & Vocab
//

import Foundation

extension ReadiumNavigatorJS {
    static func buildHighlightScript() -> String {
        """
        // 標記單一生字（底線）
        window.__markVocabWord = function(word) {
            var lowerWord = word.toLowerCase();
            var walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null, false
            );
            var textNodes = [];
            while (walker.nextNode()) textNodes.push(walker.currentNode);

            var escaped = word.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');

            textNodes.forEach(function(node) {
                var parent = node.parentElement;
                if (!parent) return;
                if (parent.classList.contains('vocab-word')) return;
                if (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE') return;

                var regex = new RegExp('\\\\b(' + escaped + ')\\\\b', 'gi');
                if (!regex.test(node.textContent)) return;
                regex.lastIndex = 0;

                var fragment = document.createDocumentFragment();
                var parts = node.textContent.split(regex);
                parts.forEach(function(part) {
                    if (part.toLowerCase() === lowerWord) {
                        var span = document.createElement('span');
                        span.className = 'vocab-word';
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

            // 跨節點 fallback：處理連字號詞可能被拆成多個 text node 的情況
            if (word.indexOf('-') === -1) return;
            if (document.querySelector('.vocab-word') &&
                Array.from(document.querySelectorAll('.vocab-word')).some(
                    function(el) { return el.textContent.toLowerCase() === lowerWord; }
                )) return;

            var walker2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
            var nodes2 = [];
            while (walker2.nextNode()) nodes2.push(walker2.currentNode);

            for (var i = 0; i < nodes2.length; i++) {
                var combined = '';
                var span = 0;
                while (span < 10 && i + span < nodes2.length) {
                    combined += nodes2[i + span].textContent;
                    span++;
                    var testRegex = new RegExp(escaped, 'i');
                    if (testRegex.test(combined)) {
                        var wrapper = document.createElement('span');
                        wrapper.className = 'vocab-word';
                        var firstNode = nodes2[i];
                        firstNode.parentNode.insertBefore(wrapper, firstNode);
                        for (var j = 0; j < span; j++) {
                            wrapper.appendChild(nodes2[i + j]);
                        }
                        return;
                    }
                }
            }
        };

        // 批量標記生字（分批 DOM 遍歷，並向 Swift 回報進度）
        window.__markVocabWords = function(words) {
            // Generation token：每次呼叫遞增。翻頁/換章觸發的新一輪 mark 會使
            // 仍排在 setTimeout 佇列中的舊批次作廢（見 processBatch 開頭檢查），
            // 避免舊批次對已 detached 的 DOM 節點做無效遍歷、並回報過期的
            // markingProgress 造成初次載入時的進度撕裂。
            var gen = (window.__markGeneration || 0) + 1;
            window.__markGeneration = gen;
            if (!words || words.length === 0) {
                window.webkit.messageHandlers.markingProgress.postMessage(JSON.stringify({done:0,total:0}));
                return;
            }
            var lowerSet = {};
            words.forEach(function(w) { lowerSet[w.toLowerCase()] = true; });
            var escaped = words.map(function(w) {
                return w.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
            });
            var regex = new RegExp('\\\\b(' + escaped.join('|') + ')\\\\b', 'gi');

            var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
            var textNodes = [];
            while (walker.nextNode()) textNodes.push(walker.currentNode);

            var total = textNodes.length;
            if (total === 0) {
                window.webkit.messageHandlers.markingProgress.postMessage(JSON.stringify({done:0,total:0}));
                return;
            }

            var batchSize = 80;
            var processed = 0;

            function processBatch() {
                if (gen !== window.__markGeneration) return; // 被新一輪 mark 取代 → 中止舊批次
                var end = Math.min(processed + batchSize, total);
                for (var i = processed; i < end; i++) {
                    var node = textNodes[i];
                    var parent = node.parentElement;
                    if (!parent) continue;
                    if (parent.classList.contains('vocab-word')) continue;
                    if (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE') continue;
                    if (!regex.test(node.textContent)) { regex.lastIndex = 0; continue; }
                    regex.lastIndex = 0;

                    var parts = node.textContent.split(regex);
                    if (parts.length <= 1) continue;
                    var fragment = document.createDocumentFragment();
                    parts.forEach(function(part) {
                        if (lowerSet[part.toLowerCase()]) {
                            var span = document.createElement('span');
                            span.className = 'vocab-word';
                            span.textContent = part;
                            fragment.appendChild(span);
                        } else if (part.length > 0) {
                            fragment.appendChild(document.createTextNode(part));
                        }
                    });
                    if (node.parentNode) node.parentNode.replaceChild(fragment, node);
                }
                processed = end;
                window.webkit.messageHandlers.markingProgress.postMessage(JSON.stringify({done:processed,total:total}));
                if (processed < total) {
                    setTimeout(processBatch, 0);
                } else {
                    // 跨節點 fallback for hyphenated words
                    var hyphenatedWords = words.filter(function(w) { return w.indexOf('-') !== -1; });
                    if (hyphenatedWords.length > 0) {
                        var marked = {};
                        document.querySelectorAll('.vocab-word').forEach(function(el) {
                            marked[el.textContent.toLowerCase()] = true;
                        });
                        hyphenatedWords.forEach(function(hw) {
                            if (marked[hw.toLowerCase()]) return;
                            window.__markVocabWord(hw);
                        });
                    }
                }
            }
            processBatch();
        };

        // 移除生字底線
        window.__removeVocabWord = function(word) {
            var lowerWord = word.toLowerCase();
            document.querySelectorAll('.vocab-word').forEach(function(el) {
                if (el.textContent.toLowerCase() === lowerWord) {
                    el.classList.remove('vocab-word', 'active-word');
                    if (el.classList.contains('debug-word-box')) return; // 保留 debug 狀態
                    var parent = el.parentNode;
                    while (el.firstChild) parent.insertBefore(el.firstChild, el);
                    parent.removeChild(el);
                    parent.normalize();
                }
            });
        };
        """
    }
}
#endif
