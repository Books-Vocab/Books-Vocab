//
//  NotebookEditSheet.swift
//  BooksBrowser
//
//  新建 / 編輯單字本的 sheet

import SwiftUI
import PhotosUI

struct NotebookAppearance {
    let name: String
    let color: String?
    let coverPattern: String?
    let coverImagePath: String?
}

struct NotebookEditSheet: View {
    enum Mode {
        case create
        case edit(name: String, color: String?, coverPattern: String?, coverImagePath: String?)
    }

    let mode: Mode
    let onSave: (NotebookAppearance) -> Void

    @Environment(\.dismiss) private var dismiss
    @Environment(\.vocabSkin) private var skin

    @State private var name: String = ""
    @State private var selectedColor: String?
    @State private var selectedPattern: String?
    @State private var coverImagePath: String?
    @State private var selectedPhoto: PhotosPickerItem?
    @State private var isProcessingPhoto = false

    init(mode: Mode, onSave: @escaping (NotebookAppearance) -> Void) {
        self.mode = mode
        self.onSave = onSave
        switch mode {
        case .create:
            _name = State(initialValue: "")
            _selectedColor = State(initialValue: nil)
            _selectedPattern = State(initialValue: nil)
            _coverImagePath = State(initialValue: nil)
        case .edit(let n, let c, let p, let img):
            _name = State(initialValue: n)
            _selectedColor = State(initialValue: c)
            _selectedPattern = State(initialValue: p)
            _coverImagePath = State(initialValue: img)
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    NotebookCoverView(
                        color: NotebookPalette.color(for: selectedColor),
                        pattern: selectedPattern.flatMap { NotebookCoverPattern(rawValue: $0) },
                        coverImagePath: coverImagePath,
                        name: name.isEmpty ? "預覽".localized : name
                    )
                    .frame(height: 100)
                    .clipShape(RoundedRectangle(cornerRadius: skin.radii.card, style: .continuous))
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                }

                Section {
                    TextField("單字本名稱".localized, text: $name)
                }

                Section("顏色".localized) {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 36))], spacing: 10) {
                        ForEach(NotebookPalette.colors, id: \.hex) { item in
                            Circle()
                                .fill(Color(hex: item.hex) ?? skin.palette.accent)
                                .frame(width: 32, height: 32)
                                .overlay {
                                    if selectedColor == item.hex {
                                        Image(systemName: "checkmark")
                                            .font(.system(size: 12, weight: .bold))
                                            .foregroundStyle(.white)
                                    }
                                }
                                .onTapGesture { selectedColor = item.hex }
                                .accessibilityLabel(item.name)
                        }
                    }
                    .padding(.vertical, 4)
                }

                Section("圖案".localized) {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            patternOption(nil, label: "無")
                            ForEach(NotebookCoverPattern.allCases) { pattern in
                                patternOption(pattern.rawValue, label: pattern.label)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }

                Section("自訂圖片".localized) {
                    HStack {
                        PhotosPicker(selection: $selectedPhoto, matching: .images) {
                            Label(coverImagePath == nil ? "選擇圖片".localized : "更換圖片".localized, systemImage: "photo")
                        }

                        if coverImagePath != nil {
                            Spacer()
                            Button(role: .destructive) {
                                removeCoverImage()
                            } label: {
                                Label("移除".localized, systemImage: "trash")
                            }
                        }
                    }
                    .disabled(isProcessingPhoto)

                    if isProcessingPhoto {
                        ProgressView("處理中...".localized)
                    }
                }
            }
            .navigationTitle(isCreating ? "新增單字本".localized : "編輯單字本".localized)
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isCreating ? "建立".localized : "儲存".localized) {
                        onSave(NotebookAppearance(
                            name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                            color: selectedColor,
                            coverPattern: selectedPattern,
                            coverImagePath: coverImagePath
                        ))
                        dismiss()
                    }
                    .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .onChange(of: selectedPhoto) { _, item in
                guard let item else { return }
                Task { await processPhoto(item) }
            }
        }
        .appSheet(.large)
    }

    @ViewBuilder
    private func patternOption(_ patternId: String?, label: String) -> some View {
        let isSelected = selectedPattern == patternId
        let color = NotebookPalette.color(for: selectedColor)
        VStack(spacing: 4) {
            ZStack {
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(patternId == nil ? skin.palette.mutedFill : color)
                    .frame(width: 48, height: 36)
                if let pid = patternId, let p = NotebookCoverPattern(rawValue: pid) {
                    p.patternOverlay(size: CGSize(width: 48, height: 36))
                        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                }
                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.white)
                        .font(.system(size: 14))
                }
            }
            Text(label)
                .font(.system(size: 10))
                .foregroundStyle(skin.palette.secondaryText)
        }
        .onTapGesture { selectedPattern = patternId }
    }

    private var isCreating: Bool {
        if case .create = mode { return true }
        return false
    }

    @MainActor
    private func processPhoto(_ item: PhotosPickerItem) async {
        isProcessingPhoto = true
        defer { isProcessingPhoto = false }

        guard let data = try? await item.loadTransferable(type: Data.self) else { return }

        #if os(macOS)
        guard let nsImage = NSImage(data: data) else { return }
        let cgImage = nsImage.cgImage(forProposedRect: nil, context: nil, hints: nil)
        guard let cg = cgImage else { return }
        let resized = NSImage(cgImage: cg, size: NSSize(width: min(CGFloat(cg.width), 600), height: min(CGFloat(cg.height), 400)))
        guard let tiffData = resized.tiffRepresentation,
              let rep = NSBitmapImageRep(data: tiffData),
              let jpegData = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.7]) else { return }
        #else
        guard let uiImage = UIImage(data: data) else { return }
        let maxDim: CGFloat = 600
        let scale = min(maxDim / uiImage.size.width, maxDim / uiImage.size.height, 1.0)
        let newSize = CGSize(width: uiImage.size.width * scale, height: uiImage.size.height * scale)
        let renderer = UIGraphicsImageRenderer(size: newSize)
        let resizedImage = renderer.image { _ in uiImage.draw(in: CGRect(origin: .zero, size: newSize)) }
        guard let jpegData = resizedImage.jpegData(compressionQuality: 0.7) else { return }
        #endif

        guard jpegData.count <= 500_000 else { return }

        let filename = "notebook_cover_\(UUID().uuidString).jpg"
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
            .appendingPathComponent("NotebookCovers", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let fileURL = dir.appendingPathComponent(filename)
        try? jpegData.write(to: fileURL)
        coverImagePath = fileURL.path
        selectedPattern = nil
    }

    private func removeCoverImage() {
        if let path = coverImagePath {
            try? FileManager.default.removeItem(atPath: path)
        }
        coverImagePath = nil
    }
}
