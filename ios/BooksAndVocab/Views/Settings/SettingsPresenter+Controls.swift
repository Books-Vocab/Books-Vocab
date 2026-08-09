import SwiftUI

// MARK: - Card/Chrome/TextInput Modifiers, Input Fields
//
// 自繪的 +/- 步進按鈕 `SettingsStepperIconButton` 已於 APP-20260808-240a94 退場：
// 唯一呼叫端「複習節奏」改用原生 `Stepper`，上下界由傳 nil 的 increment/decrement
// closure 表達，不再由 app 自己畫按鈕與著色。

struct SettingsCardModifier: ViewModifier {
    @Environment(\.appSkin) private var appSkin

    func body(content: Content) -> some View {
        AppSectionCard(padding: 0, style: .settings(appSkin)) {
            content
        }
    }
}

extension View {
    func settingsCard() -> some View {
        modifier(SettingsCardModifier())
    }

    func appSettingsButtonChrome() -> some View {
        modifier(SettingsButtonChromeModifier())
    }

    func appSettingsTextInputStyle(alignment: TextAlignment = .trailing) -> some View {
        modifier(SettingsTextInputModifier(alignment: alignment))
    }
}

/// Settings control chrome — `pageBackground` 底 + `cardBorder` 描邊 + `control` 圓角的同構樣式，
/// 透過共用 `AppSectionCard` 渲染（不手刻 border+bg），給 stepper / 按鈕 / 輸入欄等控件容器複用。
private extension AppSectionCardStyle {
    static func settingsControl(_ skin: AppSkin) -> AppSectionCardStyle {
        .init(
            background: skin.palette.pageBackground,
            border: skin.palette.cardBorder,
            roundness: skin.roundness.control,
            borderOpacity: 1,
            elevation: .z0
        )
    }
}

struct SettingsButtonChromeModifier: ViewModifier {
    @Environment(\.appSkin) private var appSkin

    func body(content: Content) -> some View {
        AppSectionCard(padding: appSkin.spacing.cardPadding, style: .settingsControl(appSkin)) {
            content
        }
    }
}

struct SettingsTextInputModifier: ViewModifier {
    @Environment(\.appSkin) private var appSkin
    let alignment: TextAlignment

    func body(content: Content) -> some View {
        content
            .font(appSkin.typography.monoLabel)
            .multilineTextAlignment(alignment)
            .platformTextInputConfig()
    }
}

struct SettingsLabeledInputField<Content: View>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let title: String
    let content: Content

    init(title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        AppSectionCard(padding: appSkin.spacing.cardPadding, style: .settingsControl(appSkin)) {
            VStack(alignment: .leading, spacing: appSkin.spacing.rowMicroGap) {
                Text(title)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)

                content
            }
        }
        .enableInjection()
    }
}
