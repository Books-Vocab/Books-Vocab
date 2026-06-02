//
//  PanelDataEnvironment.swift
//  BooksBrowser
//
//  panel 是 root master 的 sibling（非 child），讀不到 root closure 的 @Query。
//  故由 section wrapper 在 container 層經 environment 注入 live 資料給 resolver。
//

import SwiftUI

private struct PanelVocabEntriesKey: EnvironmentKey {
    static let defaultValue: [VocabularyEntry] = []
}

extension EnvironmentValues {
    /// 供 `PanelHost` resolver 反查 live `VocabularyEntry`（由 vocab section wrapper 注入）。
    var panelVocabEntries: [VocabularyEntry] {
        get { self[PanelVocabEntriesKey.self] }
        set { self[PanelVocabEntriesKey.self] = newValue }
    }
}
