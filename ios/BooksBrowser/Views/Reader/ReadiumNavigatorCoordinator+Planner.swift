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

    private mutating func commandsForVocabularyHighlights(
        lookedUpWords: [String],
        bookUniqueWords: Set<String>?
    ) -> [BridgeCommand] {
        let previousCount = lastVocabCount
        let currentCount = lookedUpWords.count
        let currentSet = Set(lookedUpWords)
        let didLoadBookWords = (bookUniqueWords != nil && lastBookUniqueWordsCount == nil)
        var commands: [BridgeCommand] = []

        if currentCount < previousCount {
            let removedWords = lastVocabWordsSet.subtracting(currentSet)
            commands.append(contentsOf: commandsForRemovedVocabulary(
                newCount: currentCount,
                removedWords: removedWords,
                remainingWords: currentSet,
                bookUniqueWords: bookUniqueWords
            ))
        } else if currentCount > previousCount || didLoadBookWords {
            commands.append(contentsOf: commandsForAddedVocabulary(
                lookedUpWords: lookedUpWords,
                didLoadBookWords: didLoadBookWords,
                bookUniqueWords: bookUniqueWords
            ))
        }

        lastVocabCount = currentCount
        lastVocabWordsSet = currentSet
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
