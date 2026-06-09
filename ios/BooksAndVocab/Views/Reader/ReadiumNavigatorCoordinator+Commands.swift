#if os(iOS)
import Foundation
import ReadiumNavigator
import ReadiumShared

enum BridgeCommand {
    case host(HostCommand)
    case navigator(NavigatorCommand)
    case dom(DOMCommand)
}

enum HostCommand {
    case setInteractionBlocked(Bool)
}

enum NavigatorCommand {
    case navigate(Locator)
    case applyPreferences(EPUBPreferences)
}

enum DOMCommand {
    case clearActiveHighlight
    case clearAllVocabHighlights
    case markVocabWords([String])
    case markNewVocabWord(String)
    case removeVocabWord(String)
    case setContentStyle(String)
    case setUnderlineOpacity(Double)
    case setDebugMode(Bool)
}

extension ReadiumNavigatorView.Coordinator {
    func sync(
        with snapshot: ReadiumNavigatorView.BridgeSnapshot,
        in host: NavigatorHostViewController
    ) {
        apply(planner.makeCommands(from: snapshot), in: host)
    }

    func apply(_ commands: [BridgeCommand], in host: NavigatorHostViewController) {
        for command in commands {
            switch command {
            case .host(let hostCommand):
                apply(hostCommand, in: host)
            case .navigator(let navigatorCommand):
                apply(navigatorCommand, in: host)
            case .dom(let domCommand):
                apply(domCommand)
            }
        }
    }

    func apply(_ command: HostCommand, in host: NavigatorHostViewController) {
        switch command {
        case .setInteractionBlocked(let isBlocked):
            if let blocker = host.view.viewWithTag(9001) {
                blocker.isUserInteractionEnabled = isBlocked
            }
        }
    }

    func apply(_ command: NavigatorCommand, in host: NavigatorHostViewController) {
        switch command {
        case .navigate(let locator):
            Task { @MainActor in
                AppLog.reader.debug("Attempting navigation to: \(String(describing: locator.href))")
                let success = await navigator?.go(to: locator)
                AppLog.reader.debug("Navigation result: \(String(describing: success))")
            }
        case .applyPreferences(let preferences):
            isApplyingPreferences = true
            Task { @MainActor in
                host.epubNavigator?.submitPreferences(preferences)
                try? await Task.sleep(for: .seconds(ReaderMetrics.applyPreferencesSettleDelay))
                self.isApplyingPreferences = false
            }
        }
    }

    func apply(_ command: DOMCommand) {
        domExecutor.execute(
            command,
            navigator: navigator,
            clearActiveHighlight: { [weak self] in self?.clearActiveHighlight() },
            clearAllVocabHighlights: { [weak self] in self?.clearAllVocabHighlights() },
            markVocabWords: { [weak self] words in self?.markVocabWords(words) },
            markNewVocabWord: { [weak self] word in self?.markNewVocabWord(word) },
            removeVocabWord: { [weak self] word in self?.removeVocabWord(word) }
        )
    }
}
#endif
