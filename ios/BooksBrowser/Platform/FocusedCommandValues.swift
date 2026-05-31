//
//  FocusedCommandValues.swift
//  BooksBrowser
//
//  畫面相關 menu 命令的 focusedSceneValue 通道。動作分散在 per-view coordinator,
//  scene 層 menu 無法直接 reference,故 view 用 .focusedSceneValue publish 一個動作,
//  menu 用 @FocusedValue 取出 + .disabled(action == nil) 自動 enable/disable。
//
//  用 wrapper struct(非裸 closure)當 FocusedValue,語意清楚、diffing 穩定。
//  未 gate Catalyst:.focusedSceneValue 在 iPhone/iPad 無 menu 消費端時為無害 no-op。
//

import SwiftUI

struct ImportBookAction { let run: () -> Void }
struct NewNotebookAction { let run: () -> Void }
struct StartReviewAction { let run: () -> Void }

private struct ImportBookKey: FocusedValueKey { typealias Value = ImportBookAction }
private struct NewNotebookKey: FocusedValueKey { typealias Value = NewNotebookAction }
private struct StartReviewKey: FocusedValueKey { typealias Value = StartReviewAction }

extension FocusedValues {
    var importBook: ImportBookAction? {
        get { self[ImportBookKey.self] }
        set { self[ImportBookKey.self] = newValue }
    }
    var newNotebook: NewNotebookAction? {
        get { self[NewNotebookKey.self] }
        set { self[NewNotebookKey.self] = newValue }
    }
    var startReview: StartReviewAction? {
        get { self[StartReviewKey.self] }
        set { self[StartReviewKey.self] = newValue }
    }
}
