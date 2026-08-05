//
//  AppHeroIcon.swift
//  Books & Vocab
//
//  認證/歡迎畫面共用的 App icon hero — WelcomeView 與 LoginSheet 原各寫一份
//  逐字相同的 80×80 圓角圖示，收斂為單一元件以保持品牌呈現一致。
//

import SwiftUI

struct AppHeroIcon: View {
    var body: some View {
        Image("AppIconImage") // i18n-allow: asset name
            .resizable()
            .scaledToFit()
            .frame(width: 80, height: 80)
            .clipShape(AppRoundedRect(roundness: AppRoundness.icon))
    }
}
