//
//  ReadiumNavigatorJS.swift
//  BooksBrowser
//

import Foundation

enum ReadiumNavigatorJS {
    static func buildInjectionScript(
        fontFaceCSS: String,
        underlineOpacity: Double,
        isDebugMode: String
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

            var style = document.createElement('style');
            style.textContent = `
                /* ═══════════════════════════════════════════════
                   莫蘭迪色彩系統 × 介面隱形化
                   ─ 1px 細線、低對比底線、克制的存在感 ─
                   ═══════════════════════════════════════════════ */

                :root {
                    --vocab-opacity: \(underlineOpacity);
                    /* 增加頂部間距，避免浮動 Liquid Glass Header 擋住由上往下看的文字 */
                    --RS__pageGutterTop: 72px !important;
                    /* 增加底部間距，避免極簡進度條或未來可能的版型擋住最下面一行 */
                    --RS__pageGutterBottom: 48px !important;
                }

                html, body {
                    touch-action: manipulation;
                    overscroll-behavior-x: none;
                }

                /* ── Light Mode ── */
                .active-word {
                    outline: 1px solid rgba(80, 80, 80, 0.40);
                    outline-offset: 1.5px;
                    border-radius: 3px;
                    background: rgba(80, 80, 80, 0.04) !important;
                }
                .vocab-word {
                    background: linear-gradient(to top, hsla(215, 30%, 58%, var(--vocab-opacity)) 35%, transparent 35%);
                    border-radius: 2px;
                }
                .active-word.vocab-word {
                    outline: 1px solid rgba(80, 80, 80, 0.40);
                    outline-offset: 1.5px;
                    background: rgba(80, 80, 80, 0.04) !important;
                }
                .active-word .vocab-word {
                    background: rgba(80, 80, 80, 0.04) !important;
                }

                /* ── Sepia Mode（暖紙調） ── */
                :root[data-readium-theme="sepia"] .active-word {
                    outline: 1px solid rgba(90, 70, 50, 0.40);
                    outline-offset: 1.5px;
                    background: rgba(90, 70, 50, 0.05) !important;
                }
                :root[data-readium-theme="sepia"] .vocab-word {
                    background: linear-gradient(to top, hsla(22, 28%, 55%, var(--vocab-opacity)) 35%, transparent 35%);
                }
                :root[data-readium-theme="sepia"] .active-word.vocab-word {
                    outline: 1px solid rgba(90, 70, 50, 0.40);
                    outline-offset: 1.5px;
                    background: rgba(90, 70, 50, 0.05) !important;
                }
                :root[data-readium-theme="sepia"] .active-word .vocab-word {
                    background: rgba(90, 70, 50, 0.05) !important;
                }

                /* ── Dark Mode（深暖灰） ── */
                :root[data-readium-theme="dark"] .active-word {
                    outline: 1px solid rgba(200, 195, 185, 0.35);
                    outline-offset: 1.5px;
                    background: rgba(200, 195, 185, 0.06) !important;
                }
                :root[data-readium-theme="dark"] .vocab-word {
                    background: linear-gradient(to top, hsla(215, 28%, 70%, clamp(0, calc(var(--vocab-opacity) * 1.6), 1)) 35%, transparent 35%);
                }
                :root[data-readium-theme="dark"] .active-word.vocab-word {
                    outline: 1px solid rgba(200, 195, 185, 0.35);
                    outline-offset: 1.5px;
                    background: rgba(200, 195, 185, 0.06) !important;
                }
                :root[data-readium-theme="dark"] .active-word .vocab-word {
                    background: rgba(200, 195, 185, 0.06) !important;
                }
                
                /* ── 排版基線 ── */
                * {
                    text-align: left !important;
                }

                /* ── Debug 標記樣式 ── */
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
                
                /* 全域單字框 (Token Calculator 效果) */
                .debug-word-box {
                    outline: 1px solid rgba(130, 130, 130, 0.40);
                    border-radius: 2px;
                    background-color: transparent !important;
                }
            `;
            document.head.appendChild(style);
        })();

        // 標記單一生字（底線）
        window.__markVocabWord = function(word) {
            var lowerWord = word.toLowerCase();
            var walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null, false
            );
            var textNodes = [];
            while (walker.nextNode()) textNodes.push(walker.currentNode);

            textNodes.forEach(function(node) {
                var parent = node.parentElement;
                if (!parent) return;
                if (parent.classList.contains('vocab-word')) return;
                if (parent.tagName === 'SCRIPT' || parent.tagName === 'STYLE') return;

                var escaped = word.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
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
        };

        // 批量標記生字（分批 DOM 遍歷，並向 Swift 回報進度）
        window.__markVocabWords = function(words) {
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

        // 監聽原生的文字選取狀態
        document.addEventListener('selectionchange', function() {
            var sel = window.getSelection();
            var isSelecting = sel.rangeCount > 0 && !sel.isCollapsed;
            if (window.__lastIsSelecting !== isSelecting) {
                window.__lastIsSelecting = isSelecting;
                window.webkit.messageHandlers.selectionState.postMessage(isSelecting ? 'active' : 'inactive');
            }
        });

        // 單字點擊偵測
        document.addEventListener('click', function(e) {
            if (e.target.closest('a')) return;

            var isDebug = \(isDebugMode);
            var maxHitDistance = 12.0; // 允許的最大點擊誤差（px）

            // 清理舊的 Debug 標記
            document.querySelectorAll('.debug-tap-point, .debug-hit-box').forEach(function(el) {
                el.remove();
            });

            // 畫出點擊位置 (Debug)
            if (isDebug) {
                var dot = document.createElement('div');
                dot.className = 'debug-tap-point';
                dot.style.left = (e.clientX + window.scrollX) + 'px';
                dot.style.top = (e.clientY + window.scrollY) + 'px';
                document.body.appendChild(dot);
            }

            // 計算點到矩形的最短距離
            function getDistanceToRect(x, y, rect) {
                var dx = Math.max(rect.left - x, 0, x - rect.right);
                var dy = Math.max(rect.top - y, 0, y - rect.bottom);
                return Math.sqrt(dx * dx + dy * dy);
            }

            // 畫出範圍框 (Debug)
            function drawDebugBox(rect, isSuccess) {
                if (!isDebug) return;
                var box = document.createElement('div');
                box.className = 'debug-hit-box ' + (isSuccess ? 'success' : 'fail');
                box.style.left = (rect.left + window.scrollX) + 'px';
                box.style.top = (rect.top + window.scrollY) + 'px';
                box.style.width = rect.width + 'px';
                box.style.height = rect.height + 'px';
                document.body.appendChild(box);
            }

            // 檢查是否點擊的是已經 active-word 的元素（toggle off）
            var clickedActive = e.target.closest('.active-word');
            if (clickedActive) {
                var dist = getDistanceToRect(e.clientX, e.clientY, clickedActive.getBoundingClientRect());
                if (dist > maxHitDistance) {
                   // 點擊偏移過大，視為空白點擊
                   window.getSelection().removeAllRanges();
                   window.webkit.messageHandlers.wordDeselect.postMessage('deselect');
                   return;
                }

                // toggle off：移除 highlight，發送 deselect
                if (clickedActive.classList.contains('vocab-word') || clickedActive.classList.contains('debug-word-box')) {
                    clickedActive.classList.remove('active-word');
                } else {
                    var parent = clickedActive.parentNode;
                    while (clickedActive.firstChild) parent.insertBefore(clickedActive.firstChild, clickedActive);
                    parent.removeChild(clickedActive);
                    parent.normalize();
                }
                window.getSelection().removeAllRanges();
                window.webkit.messageHandlers.wordDeselect.postMessage('deselect');
                return;
            }

            // 清除舊的 active-word（保留 vocab-word 或 debug-word-box）
            document.querySelectorAll('.active-word').forEach(function(el) {
                if (el.classList.contains('vocab-word') || el.classList.contains('debug-word-box')) {
                    el.classList.remove('active-word');
                    return;
                }
                var parent = el.parentNode;
                while (el.firstChild) parent.insertBefore(el.firstChild, el);
                parent.removeChild(el);
                parent.normalize();
            });

            // ★ 優先偵測：點擊位置是否在 .vocab-word 內（片語優先）
            var vocabSpan = e.target.closest('.vocab-word');
            if (vocabSpan) {
                var rect = vocabSpan.getBoundingClientRect();
                var dist = getDistanceToRect(e.clientX, e.clientY, rect);
                
                if (dist <= maxHitDistance) {
                    drawDebugBox(rect, true);
                    var vocabWord = vocabSpan.textContent.trim();
                    if (vocabWord.length >= 2) {
                        vocabSpan.classList.add('active-word');
                        var container = vocabSpan.parentElement;
                        while (container && container.tagName !== 'P' && container.tagName !== 'DIV'
                               && container.tagName !== 'SECTION' && container.tagName !== 'BODY') {
                            container = container.parentElement;
                        }
                        var context = container ? container.textContent : vocabWord;
                        if (context.length > 500) context = context.substring(0, 500);
                        window.webkit.messageHandlers.wordTap.postMessage(
                            JSON.stringify({word: vocabWord, context: context.trim()})
                        );
                        return;
                    }
                } else {
                    drawDebugBox(rect, false);
                }
            }

            // 處理一般文字點擊 (Caret Range 吸附)
            var range = document.caretRangeFromPoint(e.clientX, e.clientY);
            if (!range) {
                window.getSelection().removeAllRanges();
                window.webkit.messageHandlers.wordDeselect.postMessage('deselect');
                return;
            }

            var textNode = range.startContainer;
            if (textNode.nodeType !== Node.TEXT_NODE) {
                window.getSelection().removeAllRanges();
                window.webkit.messageHandlers.wordDeselect.postMessage('deselect');
                return;
            }

            var text = textNode.textContent;
            var offset = range.startOffset;

            // 擴展取得單字邊界
            var start = offset;
            while (start > 0 && /[a-zA-Z'\\\\-]/.test(text[start - 1])) start--;
            var end = offset;
            while (end < text.length && /[a-zA-Z'\\\\-]/.test(text[end])) end++;

            var word = text.slice(start, end).replace(/^['-]+|['-]+$/g, '');
            if (word.length < 2) {
                window.webkit.messageHandlers.wordDeselect.postMessage('deselect');
                return;
            }

            // 量測吸附單字實際的 Bounding Box
            var wordRange = document.createRange();
            wordRange.setStart(textNode, start);
            wordRange.setEnd(textNode, end);
            var wordRect = wordRange.getBoundingClientRect();

            // 判斷落點與單字外框的距離
            var dist = getDistanceToRect(e.clientX, e.clientY, wordRect);
            console.log('Distance: ' + dist);

            if (dist > maxHitDistance) {
                drawDebugBox(wordRect, false);
                // 距離過遠 -> 視為點擊空白處
                window.getSelection().removeAllRanges();
                window.webkit.messageHandlers.wordDeselect.postMessage('deselect');
                return;
            }
            
            // 距離在容許範圍內 -> 成功觸發選取
            drawDebugBox(wordRect, true);

            var container = textNode.parentElement;
            while (container && container.tagName !== 'P' && container.tagName !== 'DIV'
                   && container.tagName !== 'SECTION' && container.tagName !== 'BODY') {
                container = container.parentElement;
            }
            var context = container ? container.textContent : text;
            if (context.length > 500) context = context.substring(0, 500);

            try {
                var parentEl = textNode.parentElement;
                if (parentEl && (parentEl.classList.contains('vocab-word') || parentEl.classList.contains('debug-word-box'))) {
                    parentEl.classList.add('active-word');
                } else {
                    var span = document.createElement('span');
                    span.className = 'active-word';
                    wordRange.surroundContents(span);
                }
            } catch (err) {}

            window.webkit.messageHandlers.wordTap.postMessage(
                JSON.stringify({word: word, context: context.trim()})
            );
        }, true);
        """
    }
}
