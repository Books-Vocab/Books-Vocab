//
//  SettingsView+Bindings.swift
//  Books & Vocab
//

import SwiftUI

extension SettingsView {
    var translationSourceLangBinding: Binding<TranslationLanguage> {
        Binding(
            get: { coordinator.translationSourceLang },
            set: { coordinator.translationSourceLang = $0 }
        )
    }

    var translationTargetLangBinding: Binding<TranslationLanguage> {
        Binding(
            get: { coordinator.translationTargetLang },
            set: { coordinator.translationTargetLang = $0 }
        )
    }

    var manualLoginBinding: Binding<String>? {
#if DEBUG
        Binding(
            get: { coordinator.manualLoginUserId },
            set: { coordinator.manualLoginUserId = $0 }
        )
#else
        nil
#endif
    }

    var debugLocalServerURLBinding: Binding<String>? {
#if DEBUG
        Binding(
            get: { coordinator.debugLocalServerURL },
            set: { coordinator.debugLocalServerURL = $0 }
        )
#else
        nil
#endif
    }
}
