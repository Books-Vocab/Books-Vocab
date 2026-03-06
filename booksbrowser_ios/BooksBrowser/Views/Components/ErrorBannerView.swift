//
//  ErrorBannerView.swift
//  BooksBrowser
//
//  統一錯誤提示條：從頂部滑入，非阻斷式
//

import SwiftUI

struct ErrorBannerView: View {
    @Environment(\.colorScheme) private var colorScheme
    let message: String
    var onDismiss: (() -> Void)? = nil
    var onRetry: (() -> Void)? = nil

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.footnote)
                .foregroundStyle(AppColors.warning(colorScheme))

            Text(message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)

            Spacer()

            if let retry = onRetry {
                Button(action: retry) {
                    Image(systemName: "arrow.clockwise")
                        .font(.caption)
                        .foregroundStyle(AppColors.accent(colorScheme))
                }
            }

            if let dismiss = onDismiss {
                Button(action: dismiss) {
                    Image(systemName: "xmark")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(AppColors.warning(colorScheme).opacity(0.08))
        .overlay(
            Rectangle()
                .frame(height: 1)
                .foregroundStyle(AppColors.warning(colorScheme).opacity(0.2)),
            alignment: .bottom
        )
    }
}
