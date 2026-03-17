//
//  NotebookEditSheet.swift
//  BooksBrowser
//
//  新建 / 編輯單字本的 sheet

import SwiftUI

struct NotebookEditSheet: View {
    enum Mode {
        case create
        case edit(name: String, color: String?)
    }

    let mode: Mode
    let onSave: (String, String?) -> Void

    @Environment(\.dismiss) private var dismiss
    @Environment(\.vocabSkin) private var skin

    @State private var name: String = ""
    @State private var selectedColor: String?

    private let colorOptions: [(String, Color)] = [
        ("#5B8C5A", .green),
        ("#4A90D9", .blue),
        ("#D4A843", .orange),
        ("#A855C7", .purple),
        ("#D9534F", .red),
        ("#6B7280", .gray),
    ]

    init(mode: Mode, onSave: @escaping (String, String?) -> Void) {
        self.mode = mode
        self.onSave = onSave
        switch mode {
        case .create:
            _name = State(initialValue: "")
            _selectedColor = State(initialValue: nil)
        case .edit(let existingName, let existingColor):
            _name = State(initialValue: existingName)
            _selectedColor = State(initialValue: existingColor)
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("單字本名稱".localized, text: $name)
                }

                Section("顏色".localized) {
                    HStack(spacing: skin.spacing.inlineGap) {
                        ForEach(colorOptions, id: \.0) { hex, color in
                            Circle()
                                .fill(color)
                                .frame(width: 32, height: 32)
                                .overlay {
                                    if selectedColor == hex {
                                        Image(systemName: "checkmark")
                                            .font(.caption.bold())
                                            .foregroundStyle(.white)
                                    }
                                }
                                .onTapGesture { selectedColor = hex }
                        }
                    }
                }
            }
            .navigationTitle(isCreating ? "新增單字本".localized : "編輯單字本".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isCreating ? "建立".localized : "儲存".localized) {
                        onSave(name.trimmingCharacters(in: .whitespacesAndNewlines), selectedColor)
                        dismiss()
                    }
                    .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
    }

    private var isCreating: Bool {
        if case .create = mode { return true }
        return false
    }
}
