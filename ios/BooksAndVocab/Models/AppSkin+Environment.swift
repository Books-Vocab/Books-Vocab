//
//  AppSkin+Environment.swift
//  Books & Vocab
//
//  AppSkin 的 SwiftUI Environment 注入點 —— EnvironmentKey + EnvironmentValues + View.appSkin()。
//

import SwiftUI

private struct AppSkinEnvironmentKey: EnvironmentKey {
    static let defaultValue = AppSkin.themed(.light)
}

extension EnvironmentValues {
    var appSkin: AppSkin {
        get { self[AppSkinEnvironmentKey.self] }
        set { self[AppSkinEnvironmentKey.self] = newValue }
    }
}

extension View {
    func appSkin(_ skin: AppSkin) -> some View {
        environment(\.appSkin, skin)
    }
}
