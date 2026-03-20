//
//  ReadiumNavigatorJS.swift
//  BooksBrowser
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

    private static func buildBaseStyleScript(
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

    private static func buildContentStyleScript(contentStyleCSS: String) -> String {
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

    private static func buildHighlightScript() -> String {
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

    private static func buildDebugScript(isDebugMode: String) -> String {
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

    private static func buildSelectionScript(isDebugMode: String) -> String {
        """
        // 監聽原生的文字選取狀態
        document.addEventListener('selectionchange', function() {
            var sel = window.getSelection();
            var isSelecting = sel.rangeCount > 0 && !sel.isCollapsed;
            if (window.__lastIsSelecting !== isSelecting) {
                window.__lastIsSelecting = isSelecting;
                window.webkit.messageHandlers.selectionState.postMessage(isSelecting ? 'active' : 'inactive');
            }
        });

        function dismissActiveSelection() {
            window.getSelection().removeAllRanges();
            window.webkit.messageHandlers.wordDeselect.postMessage('deselect');
        }

        function getDistanceToRect(x, y, rect) {
            var dx = Math.max(rect.left - x, 0, x - rect.right);
            var dy = Math.max(rect.top - y, 0, y - rect.bottom);
            return Math.sqrt(dx * dx + dy * dy);
        }

        function drawDebugBox(rect, isSuccess, isDebug) {
            if (!isDebug) return;
            var box = document.createElement('div');
            box.className = 'debug-hit-box ' + (isSuccess ? 'success' : 'fail');
            box.style.left = (rect.left + window.scrollX) + 'px';
            box.style.top = (rect.top + window.scrollY) + 'px';
            box.style.width = rect.width + 'px';
            box.style.height = rect.height + 'px';
            document.body.appendChild(box);
        }

        function clearDebugMarkers(isDebug, event) {
            document.querySelectorAll('.debug-tap-point, .debug-hit-box').forEach(function(el) {
                el.remove();
            });

            if (!isDebug) return;
            var dot = document.createElement('div');
            dot.className = 'debug-tap-point';
            dot.style.left = (event.clientX + window.scrollX) + 'px';
            dot.style.top = (event.clientY + window.scrollY) + 'px';
            document.body.appendChild(dot);
        }

        function unwrapActiveElement(el) {
            if (el.classList.contains('vocab-word') || el.classList.contains('debug-word-box')) {
                el.classList.remove('active-word');
                return;
            }

            var parent = el.parentNode;
            while (el.firstChild) parent.insertBefore(el.firstChild, el);
            parent.removeChild(el);
            parent.normalize();
        }

        function clearExistingActiveWords() {
            document.querySelectorAll('.active-word').forEach(function(el) {
                unwrapActiveElement(el);
            });
        }

        function findContextContainer(startEl) {
            var container = startEl;
            while (container) {
                var tag = (container.tagName || '').toUpperCase();
                if (tag === 'P' || tag === 'DIV' || tag === 'SECTION' || tag === 'BODY') return container;
                container = container.parentElement;
            }
            return null;
        }

        function extractContextFromElement(startEl, word) {
            var container = findContextContainer(startEl);
            var fullText = container ? container.textContent : (startEl ? startEl.textContent : word);
            fullText = fullText.trim();

            var sentences = fullText.match(/[^.!?]*[.!?]+[ ]?|[^.!?]+$/g);
            if (!sentences || sentences.length <= 1) {
                if (fullText.length <= 300) return fullText;
                var wordPos = fullText.toLowerCase().indexOf(word.toLowerCase());
                if (wordPos < 0) wordPos = Math.floor(fullText.length / 2);
                var start = Math.max(0, wordPos - 150);
                var end = Math.min(fullText.length, wordPos + word.length + 150);
                return fullText.substring(start, end).trim();
            }

            var wordLower = word.toLowerCase();
            var targetIdx = -1;
            for (var i = 0; i < sentences.length; i++) {
                if (sentences[i].toLowerCase().indexOf(wordLower) >= 0) {
                    targetIdx = i;
                    break;
                }
            }
            if (targetIdx < 0) return fullText.substring(0, 300).trim();

            var result = sentences[targetIdx].trim();
            if (result.length < 80) {
                if (targetIdx > 0 && sentences[targetIdx - 1].trim().length > 15) {
                    result = sentences[targetIdx - 1].trim() + ' ' + result;
                } else if (targetIdx < sentences.length - 1) {
                    result = result + ' ' + sentences[targetIdx + 1].trim();
                }
            }

            // Strip leading fragment (short leftover from previous sentence)
            result = result.replace(/^[A-Za-z,\u{2019}\u{2018}' ]{1,15}[.!?] /, '');

            return result;
        }

        function buildWordRangeFromPoint(event) {
            var range = document.caretRangeFromPoint(event.clientX, event.clientY);
            if (!range) return null;

            var textNode = range.startContainer;
            if (textNode.nodeType !== Node.TEXT_NODE) return null;

            var text = textNode.textContent;
            var offset = range.startOffset;
            var start = offset;
            while (start > 0 && /[a-zA-Z'\\\\-]/.test(text[start - 1])) start--;
            var end = offset;
            while (end < text.length && /[a-zA-Z'\\\\-]/.test(text[end])) end++;

            var word = text.slice(start, end).replace(/^['-]+|['-]+$/g, '');
            if (word.length < 2) return null;

            var wordRange = document.createRange();
            wordRange.setStart(textNode, start);
            wordRange.setEnd(textNode, end);
            return {
                textNode: textNode,
                text: text,
                word: word,
                range: wordRange,
                rect: wordRange.getBoundingClientRect()
            };
        }

        function activateWordRange(wordData) {
            try {
                var parentEl = wordData.textNode.parentElement;
                if (parentEl && (parentEl.classList.contains('vocab-word') || parentEl.classList.contains('debug-word-box'))) {
                    parentEl.classList.add('active-word');
                } else {
                    var span = document.createElement('span');
                    span.className = 'active-word';
                    wordData.range.surroundContents(span);
                }
            } catch (err) {}
        }

        // 單字點擊偵測
        document.addEventListener('click', function(e) {
            if (e.target.closest('a')) return;

            var isDebug = \(isDebugMode);
            var maxHitDistance = 12.0; // 允許的最大點擊誤差（px）

            clearDebugMarkers(isDebug, e);

            // 檢查是否點擊的是已經 active-word 的元素（toggle off）
            var clickedActive = e.target.closest('.active-word');
            if (clickedActive) {
                var dist = getDistanceToRect(e.clientX, e.clientY, clickedActive.getBoundingClientRect());
                if (dist > maxHitDistance) {
                    dismissActiveSelection();
                    return;
                }

                unwrapActiveElement(clickedActive);
                dismissActiveSelection();
                return;
            }

            clearExistingActiveWords();

            // ★ 優先偵測：點擊位置是否在 .vocab-word 內（片語優先）
            var vocabSpan = e.target.closest('.vocab-word');
            if (vocabSpan) {
                var rect = vocabSpan.getBoundingClientRect();
                var dist = getDistanceToRect(e.clientX, e.clientY, rect);
                
                if (dist <= maxHitDistance) {
                    drawDebugBox(rect, true, isDebug);
                    var vocabWord = vocabSpan.textContent.trim();
                    if (vocabWord.length >= 2) {
                        vocabSpan.classList.add('active-word');
                        window.webkit.messageHandlers.wordTap.postMessage(
                            JSON.stringify({
                                word: vocabWord,
                                context: extractContextFromElement(vocabSpan.parentElement, vocabWord)
                            })
                        );
                        return;
                    }
                } else {
                    drawDebugBox(rect, false, isDebug);
                }
            }

            // 處理一般文字點擊 (Caret Range 吸附)
            var wordData = buildWordRangeFromPoint(e);
            if (!wordData) {
                dismissActiveSelection();
                return;
            }

            // 判斷落點與單字外框的距離
            var dist = getDistanceToRect(e.clientX, e.clientY, wordData.rect);
            console.log('Distance: ' + dist);

            if (dist > maxHitDistance) {
                drawDebugBox(wordData.rect, false, isDebug);
                dismissActiveSelection();
                return;
            }
            
            // 距離在容許範圍內 -> 成功觸發選取
            drawDebugBox(wordData.rect, true, isDebug);
            activateWordRange(wordData);

            window.webkit.messageHandlers.wordTap.postMessage(
                JSON.stringify({
                    word: wordData.word,
                    context: extractContextFromElement(wordData.textNode.parentElement, wordData.word)
                })
            );
        }, true);
        """
    }
}
