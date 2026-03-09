import SwiftUI

struct ReaderSettingsPanelPresenter: View {
    struct State {
        let fontSizeText: String
        let canDecreaseFontSize: Bool
        let canIncreaseFontSize: Bool
    }

    struct Bindings {
        let lineHeight: Binding<Double>
        let font: Binding<ReaderFont>
        let theme: Binding<ReaderTheme>
        let underlineOpacity: Binding<Double>
        let showHitTestingDebug: Binding<Bool>
        let translationPanelMode: Binding<TranslationPanelMode>
    }

    let state: State
    let bindings: Bindings
    let onDecreaseFontSize: () -> Void
    let onIncreaseFontSize: () -> Void
    let onSelectTheme: (ReaderTheme) -> Void
    let onSelectUnderlineOpacity: (Double) -> Void
    let onDismiss: () -> Void

    private let opacityOptions: [(label: String, value: Double)] = [
        ("隱藏", 0.0),
        ("淡", 0.15),
        ("中", 0.35),
        ("深", 0.60)
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack(spacing: 0) {
                        Button(action: onDecreaseFontSize) {
                            Text("A")
                                .font(.system(size: 14, weight: .medium))
                                .frame(maxWidth: .infinity)
                                .frame(height: 44)
                                .contentShape(Rectangle())
                        }
                        .disabled(!state.canDecreaseFontSize)
                        .buttonStyle(.plain)

                        Text(state.fontSizeText)
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .frame(width: 48, alignment: .center)

                        Button(action: onIncreaseFontSize) {
                            Text("A")
                                .font(.system(size: 22, weight: .medium))
                                .frame(maxWidth: .infinity)
                                .frame(height: 44)
                                .contentShape(Rectangle())
                        }
                        .disabled(!state.canIncreaseFontSize)
                        .buttonStyle(.plain)
                    }
                    .foregroundStyle(.primary)

                    HStack(spacing: 14) {
                        Image(systemName: "text.line.spacing")
                            .font(.system(size: 14))
                            .foregroundStyle(.secondary)

                        Slider(value: bindings.lineHeight, in: 1.0...2.5, step: 0.1)
                            .tint(.primary)

                        Text(String(format: "%.1f", bindings.lineHeight.wrappedValue))
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .frame(width: 28, alignment: .trailing)
                    }
                    .padding(.vertical, 4)
                } header: {
                    Text("排版")
                }

                Section {
                    Picker("字體", selection: bindings.font) {
                        ForEach(ReaderFont.allCases) { font in
                            Text(font.rawValue).tag(font)
                        }
                    }
                    .pickerStyle(.menu)

                    HStack(spacing: 8) {
                        ForEach(ReaderTheme.allCases) { theme in
                            Button {
                                onSelectTheme(theme)
                            } label: {
                                HStack(spacing: 6) {
                                    Image(systemName: theme.icon)
                                        .font(.system(size: 13))
                                    Text(theme.rawValue)
                                        .font(.subheadline)
                                        .fontWeight(bindings.theme.wrappedValue == theme ? .medium : .regular)
                                }
                                .padding(.vertical, 12)
                                .frame(maxWidth: .infinity)
                                .background(
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .fill(bindings.theme.wrappedValue == theme ? Color.primary.opacity(0.12) : Color.clear)
                                )
                                .overlay(
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .stroke(Color.primary.opacity(0.1), lineWidth: bindings.theme.wrappedValue == theme ? 1 : 0)
                                )
                                .foregroundStyle(bindings.theme.wrappedValue == theme ? .primary : .secondary)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 4)
                } header: {
                    Text("外觀")
                }

                Section {
                    HStack(spacing: 8) {
                        ForEach(opacityOptions, id: \.label) { option in
                            Button {
                                onSelectUnderlineOpacity(option.value)
                            } label: {
                                Text(option.label.localized)
                                    .font(.subheadline)
                                    .fontWeight(bindings.underlineOpacity.wrappedValue == option.value ? .medium : .regular)
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 10)
                                    .background(
                                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                                            .fill(bindings.underlineOpacity.wrappedValue == option.value ? Color.primary.opacity(0.12) : Color.clear)
                                    )
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                                            .stroke(Color.primary.opacity(0.1), lineWidth: bindings.underlineOpacity.wrappedValue == option.value ? 1 : 0)
                                    )
                                    .foregroundStyle(bindings.underlineOpacity.wrappedValue == option.value ? .primary : .secondary)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 4)
                } header: {
                    Text("生字底線強度")
                }

                Section {
                    Toggle("顯示點擊熱區", isOn: bindings.showHitTestingDebug)
                        .tint(.primary)
                } header: {
                    Text("開發者與除錯")
                }

                Section {
                    Picker("閱讀介面風格", selection: bindings.translationPanelMode) {
                        ForEach(TranslationPanelMode.allCases) { mode in
                            Label(mode.label, systemImage: mode.icon).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                } header: {
                    Text("閱讀介面風格")
                }
            }
            .formStyle(.grouped)
            .navigationTitle("閱讀設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: onDismiss) {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.tertiary)
                            .font(.system(size: 22))
                    }
                }
            }
        }
    }
}
