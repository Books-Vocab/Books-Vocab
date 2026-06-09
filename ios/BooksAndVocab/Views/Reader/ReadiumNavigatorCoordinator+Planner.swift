#if os(iOS)
import Foundation
import ReadiumNavigator
import ReadiumShared

struct BridgePlanner {
    var lastClearHighlightTrigger: UUID?
    var lastRemoveWordId: UUID?
    var lastNavigateId: UUID?
    var lastVocabCount: Int = 0
    var lastVocabWordsSet: Set<String> = []
    var lastBookUniqueWordsCount: Int?
    var lastPreferences: EPUBPreferences?
    var lastUnderlineOpacity: Double?
    var lastContentStyleCSS: String?
    var lastHitTestingDebug: Bool?

    mutating func makeCommands(
        from snapshot: ReadiumNavigatorView.BridgeSnapshot
    ) -> [BridgeCommand] {
        var commands: [BridgeCommand] = []

        commands.append(.host(.setInteractionBlocked(snapshot.isInteractionBlocked)))
        commands.append(contentsOf: commandsForClearHighlight(trigger: snapshot.clearHighlightTrigger))
        commands.append(contentsOf: commandsForVocabularyHighlights(
            lookedUpWords: snapshot.lookedUpWords,
            bookUniqueWords: snapshot.bookUniqueWords
        ))
        commands.append(contentsOf: commandsForRemovedWord(trigger: snapshot.removeWordTrigger))
        commands.append(contentsOf: commandsForNavigation(trigger: snapshot.navigateToLocator))
        commands.append(contentsOf: commandsForPreferences(snapshot.viewConfiguration.epubPreferences))
        commands.append(contentsOf: commandsForContentStyle(snapshot.viewConfiguration.contentStyleCSS))
        commands.append(contentsOf: commandsForUnderlineOpacity(snapshot.viewConfiguration.underlineOpacity))
        commands.append(contentsOf: commandsForDebugMode(snapshot.viewConfiguration.showHitTestingDebug))
        return commands
    }

    private mutating func commandsForClearHighlight(trigger: UUID) -> [BridgeCommand] {
        guard lastClearHighlightTrigger != trigger else { return [] }
        lastClearHighlightTrigger = trigger
        return [.dom(.clearActiveHighlight)]
    }

    /// 以 set 內容（非 count）權威判斷底線變化。換綁定單字本時新舊字數可能相同
    /// 但內容互換，舊版只看 count 會漏更新 —— 改用 added/removed 差集驅動：
    /// - 純新增 → markVocabWords / markNewVocabWord（增量，不整片清）
    /// - 純移除 → removeVocabWord（少量）或 clearAll+remark（大量）
    /// - 內容互換（同時有新增與移除）→ clearAllVocabHighlights + markVocabWords 權威重畫
    private mutating func commandsForVocabularyHighlights(
        lookedUpWords: [String],
        bookUniqueWords: Set<String>?
    ) -> [BridgeCommand] {
        let currentSet = Set(lookedUpWords)
        let didLoadBookWords = (bookUniqueWords != nil && lastBookUniqueWordsCount == nil)
        let added = currentSet.subtracting(lastVocabWordsSet)
        let removed = lastVocabWordsSet.subtracting(currentSet)

        defer {
            lastVocabCount = currentSet.count
            lastVocabWordsSet = currentSet
        }

        // 首次拿到 bookUniqueWords：以新 filter 權威重 mark 全集（即使 set 未變）。
        if didLoadBookWords {
            return commandsForAddedVocabulary(
                lookedUpWords: lookedUpWords,
                didLoadBookWords: true,
                bookUniqueWords: bookUniqueWords
            )
        }

        if added.isEmpty && removed.isEmpty { return [] }

        // 純新增：增量 mark（保留單字即時標記的 markNewVocabWord 路徑）。
        if removed.isEmpty {
            return commandsForAddedVocabulary(
                lookedUpWords: Array(added),
                didLoadBookWords: false,
                bookUniqueWords: bookUniqueWords
            )
        }

        // 純移除：少量逐字移除、大量整片清後重 mark。
        if added.isEmpty {
            return commandsForRemovedVocabulary(
                newCount: currentSet.count,
                removedWords: removed,
                remainingWords: currentSet,
                bookUniqueWords: bookUniqueWords
            )
        }

        // 內容互換（換綁定 notebook）：權威清空 + 重 mark 當前綁定本的有效字。
        var commands: [BridgeCommand] = [.dom(.clearAllVocabHighlights)]
        let validWords = filterValidWords(currentSet, bookWords: bookUniqueWords)
        if !validWords.isEmpty {
            commands.append(.dom(.markVocabWords(validWords)))
        }
        return commands
    }

    private mutating func commandsForRemovedVocabulary(
        newCount: Int,
        removedWords: Set<String>,
        remainingWords: Set<String>,
        bookUniqueWords: Set<String>?
    ) -> [BridgeCommand] {
        if newCount == 0 || removedWords.count > ReaderMetrics.bulkRemovalRemarkThreshold {
            var commands: [BridgeCommand] = [.dom(.clearAllVocabHighlights)]
            if newCount > 0 {
                let validWords = filterValidWords(remainingWords, bookWords: bookUniqueWords)
                if !validWords.isEmpty {
                    commands.append(.dom(.markVocabWords(validWords)))
                }
            }
            return commands
        }

        return removedWords.map { .dom(.removeVocabWord($0)) }
    }

    private mutating func commandsForAddedVocabulary(
        lookedUpWords: [String],
        didLoadBookWords: Bool,
        bookUniqueWords: Set<String>?
    ) -> [BridgeCommand] {
        if didLoadBookWords {
            lastBookUniqueWordsCount = bookUniqueWords?.count ?? 0
            let validWords = filterValidWords(lookedUpWords, bookWords: bookUniqueWords)
            AppLog.reader.info("生字預過濾：全域 \(lookedUpWords.count) 字 -> 本書 \(validWords.count) 字 (\(String(format: "%.1f", (1.0 - Double(validWords.count)/Double(max(1, lookedUpWords.count))) * 100))% 縮減)")
            return validWords.isEmpty ? [] : [.dom(.markVocabWords(validWords))]
        }

        let addedWords = lookedUpWords.filter { !lastVocabWordsSet.contains($0) }
        if addedWords.count == 1 {
            return [.dom(.markNewVocabWord(addedWords[0]))]
        } else if !addedWords.isEmpty {
            let validNew = filterValidWords(addedWords, bookWords: bookUniqueWords)
            if !validNew.isEmpty {
                return [.dom(.markVocabWords(validNew))]
            }
        }
        return []
    }

    private mutating func commandsForRemovedWord(trigger: (word: String, id: UUID)?) -> [BridgeCommand] {
        guard let trigger, lastRemoveWordId != trigger.id else { return [] }
        lastRemoveWordId = trigger.id
        return [.dom(.removeVocabWord(trigger.word))]
    }

    private mutating func commandsForNavigation(trigger: (locator: Locator, id: UUID)?) -> [BridgeCommand] {
        guard let trigger, lastNavigateId != trigger.id else { return [] }
        lastNavigateId = trigger.id
        return [.navigator(.navigate(trigger.locator))]
    }

    private mutating func commandsForPreferences(_ preferences: EPUBPreferences) -> [BridgeCommand] {
        guard lastPreferences != preferences else { return [] }
        lastPreferences = preferences
        return [.navigator(.applyPreferences(preferences))]
    }

    private mutating func commandsForUnderlineOpacity(_ opacity: Double) -> [BridgeCommand] {
        if let lastUnderlineOpacity, opacity != lastUnderlineOpacity {
            self.lastUnderlineOpacity = opacity
            return [.dom(.setUnderlineOpacity(opacity))]
        } else if lastUnderlineOpacity == nil {
            lastUnderlineOpacity = opacity
        }
        return []
    }

    private mutating func commandsForContentStyle(_ css: String) -> [BridgeCommand] {
        if let lastContentStyleCSS, css != lastContentStyleCSS {
            self.lastContentStyleCSS = css
            return [.dom(.setContentStyle(css))]
        } else if lastContentStyleCSS == nil {
            lastContentStyleCSS = css
        }
        return []
    }

    private mutating func commandsForDebugMode(_ isEnabled: Bool) -> [BridgeCommand] {
        if let lastHitTestingDebug, isEnabled != lastHitTestingDebug {
            self.lastHitTestingDebug = isEnabled
            return [.dom(.setDebugMode(isEnabled))]
        } else if lastHitTestingDebug == nil {
            lastHitTestingDebug = isEnabled
        }
        return []
    }
}
#endif
