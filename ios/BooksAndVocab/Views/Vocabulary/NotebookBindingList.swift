#if os(iOS)
import SwiftUI
import SwiftData

/// 單字本選擇清單（presentational）。Reader（書）與 Podcast（系列）綁定 picker 共用。
///
/// 刻意不標示「預設」—— 對使用者而言所有單字本平權（每個容器綁定即真相，無 magic
/// 預設本概念）。選一本即透過 `onSelect` 固化綁定。
struct NotebookBindingList: View {
    let notebooks: [Notebook]
    let selectedNotebookId: String?
    let onSelect: (Notebook) -> Void

    @Environment(\.appTheme) private var theme

    var body: some View {
        Section {
            ForEach(notebooks) { notebook in
                row(notebook)
            }
        } header: {
            Text("單字本".localized)
                .font(AppFonts.caption(weight: .medium))
        }
    }

    private func row(_ notebook: Notebook) -> some View {
        Button {
            onSelect(notebook)
        } label: {
            HStack(spacing: AppSpacing.s2) {
                RoundedRectangle(cornerRadius: AppRadius.xs)
                    .fill(notebook.color.flatMap { Color(hex: $0) } ?? theme.palette.accent) // token-allow: user notebook data color
                    .frame(width: 4, height: AppSpacing.s7)

                Text(notebook.name)
                    .font(AppFonts.body())
                    .foregroundStyle(theme.palette.primaryText)
                    .lineLimit(1)
                    .truncationMode(.tail)

                Spacer()

                if selectedNotebookId == notebook.remoteId {
                    Image(systemName: "checkmark")
                        .font(AppFonts.subhead(weight: .semibold))
                        .foregroundStyle(theme.palette.accent)
                }
            }
            .contentShape(Rectangle())
        }
    }
}
#endif
