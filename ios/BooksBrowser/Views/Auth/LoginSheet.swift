//
//  LoginSheet.swift
//  BooksBrowser
//
//  獨立登入 sheet，供空狀態 / Guest 面板呼叫。
//

import SwiftUI
import SwiftData

struct LoginSheet: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.authManager) private var authManager
    @Environment(\.modelContext) private var modelContext
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("登入帳號".localized)
                .inlineNavigationBarTitle()
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("取消".localized) { dismiss() }
                    }
                }
        }
        .onChange(of: authManager.isLoggedIn) { _, isLoggedIn in
            if isLoggedIn { dismiss() }
        }
    }

    private var content: some View {
        VStack(spacing: AppMetrics.spacingLarge) {
            Spacer()

            // Hero
            VStack(spacing: AppMetrics.spacingSmall) {
                Image("AppIconImage")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 80, height: 80)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))

                Text("解鎖完整功能".localized)
                    .font(vocabSkin.typography.displayTitle)
                    .foregroundStyle(vocabSkin.palette.primaryText)

                Text("AI 翻譯・知識圖譜・雲端同步".localized)
                    .font(vocabSkin.typography.body)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
            }

            Spacer()

            // Auth buttons
            VStack(spacing: vocabSkin.spacing.controlGap) {
                Button {
                    authManager.loginWithGoogle(modelContainer: modelContext.container)
                } label: {
                    loginButtonLabel(
                        title: "以 Google 繼續",
                        systemImage: nil,
                        isGoogle: true
                    )
                }
                .buttonStyle(.pressable)
                .accessibilityLabel("使用 Google 帳號登入".localized)

                Button {
                    authManager.loginWithApple(modelContainer: modelContext.container)
                } label: {
                    loginButtonLabel(
                        title: "以 Apple 繼續",
                        systemImage: "apple.logo",
                        isGoogle: false
                    )
                }
                .buttonStyle(.pressable)
                .accessibilityLabel("使用 Apple 帳號登入".localized)
            }
            .padding(.horizontal, AppMetrics.spacingMedium)
            .padding(.bottom, AppMetrics.spacingLarge)

            // Error
            if let error = authManager.authError {
                VocabStateMessageCard(
                    title: "登入暫時失敗".localized,
                    systemImage: "exclamationmark.triangle.fill",
                    description: error
                )
                .padding(.horizontal, AppMetrics.spacingMedium)
            }
        }
        .overlay {
            if authManager.isAuthenticating {
                ZStack {
                    vocabSkin.palette.pageBackground.opacity(0.85)
                    VStack(spacing: vocabSkin.spacing.controlGap) {
                        ProgressView().controlSize(.regular)
                        Text("正在驗證帳號…".localized)
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                    }
                }
                .transition(.contentSwap)
            }
        }
        .animatePhaseChange(authManager.isAuthenticating)
    }

    private func loginButtonLabel(title: String, systemImage: String?, isGoogle: Bool) -> some View {
        HStack(spacing: AppMetrics.spacingSmall) {
            if isGoogle {
                Text("G")
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .frame(width: AppSettingsMetrics.socialBadgeSize, height: AppSettingsMetrics.socialBadgeSize)
                    .background(Circle().fill(vocabSkin.palette.cardBackground))
                    .overlay(Circle().stroke(vocabSkin.palette.cardBorder, lineWidth: 1))
            } else if let systemImage {
                Image(systemName: systemImage)
                    .font(vocabSkin.typography.iconTiny)
                    .foregroundStyle(vocabSkin.palette.pageBackground)
                    .frame(width: AppSettingsMetrics.socialBadgeSize, height: AppSettingsMetrics.socialBadgeSize)
                    .background(Circle().fill(AppBrandColors.appleBlack))
            }

            Text(title.localized)
                .font(vocabSkin.typography.body.weight(.medium))

            Spacer()

            Image(systemName: "chevron.right")
                .font(vocabSkin.typography.iconTiny)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
        }
        .padding(.horizontal, AppMetrics.spacingMedium)
        .padding(.vertical, AppMetrics.spacingSmall)
        .background(
            RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                .fill(vocabSkin.palette.cardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.card, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                )
        )
    }
}

#Preview {
    AppThemeContainer {
        LoginSheet()
    }
}
