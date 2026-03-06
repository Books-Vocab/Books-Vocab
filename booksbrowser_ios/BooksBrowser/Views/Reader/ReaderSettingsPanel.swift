//
//  ReaderSettingsPanel.swift
//  BooksBrowser
//
//  Created by Antigravity on 2026/2/25.
//

import SwiftUI

/// 仿 Apple Books 的閱讀設定面板
struct ReaderSettingsPanel: View {
    @Bindable var settings: ReaderSettings
    let onDismiss: () -> Void
    
    var body: some View {
        NavigationStack {
            Form {
                // ── 尺寸調整區 ──
                Section {
                    // 字體大小：A⁻ / 倍率 / A⁺
                    HStack(spacing: 0) {
                        Button {
                            settings.fontSize = max(0.75, settings.fontSize - 0.125)
                        } label: {
                            Text("A")
                                .font(.system(size: 14, weight: .medium))
                                .frame(maxWidth: .infinity)
                                .frame(height: 44)
                                .contentShape(Rectangle())
                        }
                        .disabled(settings.fontSize <= 0.75)
                        .buttonStyle(.plain)
                        
                        Text(String(format: "%.2gx", settings.fontSize))
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .frame(width: 48, alignment: .center)
                        
                        Button {
                            settings.fontSize = min(2.0, settings.fontSize + 0.125)
                        } label: {
                            Text("A")
                                .font(.system(size: 22, weight: .medium))
                                .frame(maxWidth: .infinity)
                                .frame(height: 44)
                                .contentShape(Rectangle())
                        }
                        .disabled(settings.fontSize >= 2.0)
                        .buttonStyle(.plain)
                    }
                    .foregroundStyle(.primary)

                    // 行距滑桿
                    HStack(spacing: 14) {
                        Image(systemName: "text.line.spacing")
                            .font(.system(size: 14))
                            .foregroundStyle(.secondary)
                        
                        Slider(value: $settings.lineHeight, in: 1.0...2.5, step: 0.1)
                            .tint(.primary)
                        
                        Text(String(format: "%.1f", settings.lineHeight))
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .frame(width: 28, alignment: .trailing)
                    }
                    .padding(.vertical, 4)
                } header: {
                    Text("排版")
                }

                // ── 外觀與字體區 ──
                Section {
                    // 字體
                    Picker("字體", selection: $settings.font) {
                        ForEach(ReaderFont.allCases) { font in
                            Text(font.rawValue).tag(font)
                        }
                    }
                    .pickerStyle(.menu)

                    // 主題
                    HStack(spacing: 8) {
                        ForEach(ReaderTheme.allCases) { theme in
                            Button {
                                withAnimation(.spring(response: 0.3, dampingFraction: 0.75)) {
                                    settings.theme = theme
                                }
                            } label: {
                                HStack(spacing: 6) {
                                    Image(systemName: theme.icon)
                                        .font(.system(size: 13))
                                    Text(theme.rawValue)
                                        .font(.subheadline)
                                        .fontWeight(settings.theme == theme ? .medium : .regular)
                                }
                                .padding(.vertical, 12)
                                .frame(maxWidth: .infinity)
                                .background(
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .fill(settings.theme == theme ? Color.primary.opacity(0.12) : Color.clear)
                                )
                                .overlay(
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .stroke(Color.primary.opacity(0.1), lineWidth: settings.theme == theme ? 1 : 0)
                                )
                                .foregroundStyle(settings.theme == theme ? .primary : .secondary)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 4)
                } header: {
                    Text("外觀")
                }

                // ── 單字底線區 ──
                Section {
                    let opacityOptions: [(label: String, value: Double)] = [
                        ("隱藏", 0.0),
                        ("淡", 0.15),
                        ("中", 0.35),
                        ("深", 0.60)
                    ]
                    
                    HStack(spacing: 8) {
                        ForEach(opacityOptions, id: \.label) { option in
                            Button {
                                withAnimation(.spring(response: 0.3, dampingFraction: 0.75)) {
                                    settings.underlineOpacity = option.value
                                }
                            } label: {
                                Text(option.label)
                                    .font(.subheadline)
                                    .fontWeight(settings.underlineOpacity == option.value ? .medium : .regular)
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 10)
                                    .background(
                                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                                            .fill(settings.underlineOpacity == option.value ? Color.primary.opacity(0.12) : Color.clear)
                                    )
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                                            .stroke(Color.primary.opacity(0.1), lineWidth: settings.underlineOpacity == option.value ? 1 : 0)
                                    )
                                    .foregroundStyle(settings.underlineOpacity == option.value ? .primary : .secondary)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 4)
                } header: {
                    Text("生字底線強度")
                }

                // ── 開發者選項區 ──
                Section {
                    Toggle("顯示點擊熱區", isOn: $settings.showHitTestingDebug)
                        .tint(.primary)
                } header: {
                    Text("開發者與除錯")
                }
            }
            .formStyle(.grouped)
            .navigationTitle("閱讀設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        onDismiss()
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.tertiary)
                            .font(.system(size: 22))
                    }
                }
            }
        }
    }
}

#Preview {
    ZStack {
        Color.gray.opacity(0.2).ignoresSafeArea()
        VStack {
            Spacer()
            ReaderSettingsPanel(settings: ReaderSettings.shared) {}
                .padding(.horizontal)
        }
    }
}
