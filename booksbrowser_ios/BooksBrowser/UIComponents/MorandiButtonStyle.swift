//
//  MorandiButtonStyle.swift
//  BooksBrowser
//
//  iOS 26 詩意風格按鈕：結合微阻尼彈簧 (Liquid Glass 動態) 與莫蘭迪紙張質感
//

import SwiftUI

struct MorandiButtonStyle: ButtonStyle {
    let colorScheme: ColorScheme
    var isProminent: Bool = true
    var tintColor: Color? = nil
    
    func makeBody(configuration: Configuration) -> some View {
        let baseColor = tintColor ?? (isProminent ? AppColors.accent(colorScheme) : .secondary)
        let bgColor = isProminent ? baseColor.opacity(configuration.isPressed ? 0.2 : 0.12) : Color.clear
        
        configuration.label
            .font(AppFonts.h2()) // 採用稍微粗一點的小標題字型，增加質感
            .foregroundStyle(isProminent ? baseColor : baseColor.opacity(configuration.isPressed ? 0.6 : 1.0))
            .padding(.vertical, AppMetrics.spacingMedium)
            .padding(.horizontal, AppMetrics.spacingLarge)
            .background(
                RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous)
                    .fill(bgColor)
            )
            // 將邊框做到極細且低對比度的「紙緣」感
            .overlay(
                RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous)
                    .stroke(baseColor.opacity(0.1), lineWidth: 0.5)
            )
            .scaleEffect(configuration.isPressed ? 0.97 : 1.0)
            // iOS 26 精神的有機彈性動畫 (Fluid Motion)
            .animation(AppMotion.buttonSpring, value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == MorandiButtonStyle {
    static func morandi(colorScheme: ColorScheme, isProminent: Bool = true, tintColor: Color? = nil) -> MorandiButtonStyle {
        MorandiButtonStyle(colorScheme: colorScheme, isProminent: isProminent, tintColor: tintColor)
    }
}
