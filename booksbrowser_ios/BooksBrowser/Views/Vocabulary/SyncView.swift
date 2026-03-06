//
//  SyncView.swift
//  BooksBrowser
//
//  Sync progress sheet — dynamic step list with real-time SSE progress.
//

import SwiftUI
import SwiftData

/// Pipeline step display model
struct PipelineStep: Identifiable {
    let id: String
    let label: String
    var status: StepStatus = .waiting
    var current: Int = 0
    var total: Int = 0
    var detail: String = ""
    var startTime: Date?
    var endTime: Date?

    enum StepStatus {
        case waiting, running, retry, done, skipped, error
    }
}

/// Sync progress sheet
struct SyncView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Environment(\.colorScheme) private var colorScheme
    @Query(filter: #Predicate<VocabularyEntry> { $0.syncStatus != 1 })
    private var pendingEntries: [VocabularyEntry]

    @Environment(\.kgService) private var kgService

    @State private var steps: [PipelineStep] = []
    @State private var phase: Phase = .ready
    @State private var summaryText: String = ""
    @State private var pipelineTask: Task<Void, Never>?
    @State private var showSettings = false
    @Environment(\.authManager) private var authManager

    enum Phase {
        case ready, running, completed, failed
    }

    // MARK: - Computed

    private var deleteActions: [VocabularyEntry] {
        pendingEntries.filter { $0.actionType == "delete" }
    }

    private var addActions: [VocabularyEntry] {
        pendingEntries.filter { $0.actionType == "add" }
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Header
                headerView
                    .padding(.top, 32)
                    .padding(.bottom, 24)
                    .animation(.spring(response: 0.4, dampingFraction: 0.8), value: phase)

                // Steps
                if authManager.isLoggedIn && !steps.isEmpty {
                    GlassEffectContainer {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(steps) { step in
                                stepRow(step)
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 4)
                    }
                    .glassEffect(.regular, in: .rect(cornerRadius: 16))
                    .padding(.horizontal, 20)
                }

                Spacer()

                // Summary
                if !summaryText.isEmpty {
                    Text(summaryText)
                        .font(AppFonts.subhead())
                        .foregroundStyle(phase == .failed ? AppColors.destructive(colorScheme) : .secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 24)
                        .padding(.bottom, 12)
                }

                // Action button
                actionButton
                    .padding(.horizontal, 20)
                    .padding(.bottom, 20)
            }
            .navigationTitle("同步")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    if phase == .ready || phase == .completed || phase == .failed {
                        Button("關閉") { dismiss() }
                    }
                }
            }
            .onAppear { buildSteps() }
        }
    }

    // MARK: - Header

    @ViewBuilder
    private var headerView: some View {
        if !authManager.isLoggedIn {
            VStack(spacing: 12) {
                Image(systemName: "person.crop.circle.badge.exclamationmark")
                    .font(AppFonts.hero(weight: .light))
                    .foregroundStyle(.tertiary)
                Text("尚未登入帳號")
                    .font(AppFonts.h1())
                Text("登入後即可將您的生詞庫同步至雲端與 Mochi。")
                    .font(AppFonts.subhead())
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 40)
            }
        } else {
            switch phase {
            case .ready:
                VStack(spacing: 8) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(AppFonts.hero(weight: .light))
                        .foregroundStyle(AppColors.accent(colorScheme))

                    if pendingEntries.isEmpty {
                        Text("強制同步到 Mochi")
                            .font(AppFonts.h1())
                    } else {
                        let dels = deleteActions.count
                        let adds = addActions.count
                        VStack(spacing: 4) {
                            Text("\(pendingEntries.count) 個待處理動作")
                                .font(AppFonts.h2())
                            HStack(spacing: AppMetrics.spacingMedium) {
                                if adds > 0 {
                                    Label("\(adds) 新增", systemImage: "plus.circle")
                                        .font(.caption)
                                        .foregroundStyle(AppColors.saved(colorScheme))
                                }
                                if dels > 0 {
                                    Label("\(dels) 刪除", systemImage: "trash")
                                        .font(.caption)
                                        .foregroundStyle(AppColors.destructive(colorScheme))
                                }
                            }
                        }
                    }
                }
                .transition(.blurReplace)

        case .running:
            VStack(spacing: 8) {
                ProgressView()
                    .controlSize(.large)
                Text("同步中…")
                    .font(AppFonts.h1())
            }
            .transition(.blurReplace)
        case .completed:
            VStack(spacing: 8) {
                Image(systemName: "checkmark.circle.fill")
                    .font(AppFonts.hero(weight: .light))
                    .foregroundStyle(AppColors.saved(colorScheme))
                    .symbolEffect(.bounce)
                Text("同步完成")
                    .font(AppFonts.h1())
            }
            .transition(.blurReplace)
        case .failed:
            VStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(AppFonts.hero(weight: .light))
                    .foregroundStyle(AppColors.destructive(colorScheme))
                Text("同步失敗")
                    .font(AppFonts.h1())
            }
            .transition(.blurReplace)
        }
        }
    }

    // MARK: - Step Row

    private func stepRow(_ step: PipelineStep) -> some View {
        HStack(spacing: 12) {
            // Status icon
            Group {
                switch step.status {
                case .waiting:
                    Image(systemName: "circle")
                        .foregroundStyle(.quaternary)
                case .running:
                    ProgressView()
                        .controlSize(.small)
                case .retry:
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .symbolEffect(.scale.up, options: .repeating)
                        .foregroundStyle(AppColors.warning(colorScheme))
                case .done:
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(AppColors.saved(colorScheme))
                        .symbolEffect(.bounce)
                case .skipped:
                    Image(systemName: "minus.circle.fill")
                        .foregroundStyle(.secondary)
                case .error:
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(AppColors.destructive(colorScheme))
                }
            }
            .frame(width: 20)

            VStack(alignment: .leading, spacing: 2) {
                // Label + progress
                HStack {
                    Text(step.label)
                        .font(AppFonts.subhead(weight: .medium))
                        .foregroundStyle(step.status == .waiting ? .tertiary : .primary)
                    Spacer()
                    if step.status == .running && step.total > 0 {
                        Text("\(step.current)/\(step.total)")
                            .font(AppFonts.monoNumbers(size: 12))
                            .foregroundStyle(.secondary)
                            .contentTransition(.numericText())
                            .animation(.spring, value: step.current)
                    }
                    
                    StepDurationView(step: step)
                }

                // Detail text (shown when done/error/running with detail)
                if !step.detail.isEmpty && step.status != .waiting {
                    let detailColor = step.status == .error ? AppColors.destructive(colorScheme) :
                                      step.status == .retry ? AppColors.warning(colorScheme) :
                                      .secondary
                    
                    Text(step.detail)
                        .font(.caption2)
                        .foregroundStyle(detailColor)
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, AppMetrics.spacingMedium)
    }

    // MARK: - Action Button

    @ViewBuilder
    private var actionButton: some View {
        switch phase {
        case .ready:
            if authManager.isLoggedIn {
                Button {
                    startSync()
                } label: {
                    Label("開始同步", systemImage: "arrow.triangle.2.circlepath")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.morandi(colorScheme: colorScheme))
                .disabled(!kgService.isConnected)

                if !kgService.isConnected {
                    Text("⚠️ KG 伺服器未連線")
                        .font(.caption)
                        .foregroundStyle(AppColors.destructive(colorScheme))
                }
            } else {
                Button {
                    showSettings = true
                } label: {
                    Text("前往設定登入")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.morandi(colorScheme: colorScheme))
                .sheet(isPresented: $showSettings) {
                    SettingsView()
                }
            }
        case .running:
            Button(role: .cancel) {
                cancelSync()
            } label: {
                Text("取消")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.morandi(colorScheme: colorScheme, isProminent: false))
        case .completed:
            Button {
                dismiss()
            } label: {
                Text("完成")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.morandi(colorScheme: colorScheme))
        case .failed:
            Button {
                resetForRetry()
            } label: {
                Label("重試", systemImage: "arrow.clockwise")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.morandi(colorScheme: colorScheme, tintColor: AppColors.warning(colorScheme)))
        }
    }

    // MARK: - Build Dynamic Steps

    private func buildSteps() {
        var list: [PipelineStep] = []

        if !deleteActions.isEmpty {
            list.append(PipelineStep(id: "upload_delete", label: "刪除 KG 單字"))
        }
        if !addActions.isEmpty {
            list.append(PipelineStep(id: "upload_add", label: "上傳新單字"))
        }

        list.append(PipelineStep(id: "trigger", label: "觸發背景 AI 處理"))
        list.append(PipelineStep(id: "pull", label: "下載知識庫至本地"))

        steps = list
    }

    // MARK: - Step Helpers

    private func updateStep(_ id: String, status: PipelineStep.StepStatus, current: Int = 0, total: Int = 0, detail: String = "") {
        if let idx = steps.firstIndex(where: { $0.id == id }) {
            withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
                steps[idx].status = status
                steps[idx].current = current
                steps[idx].total = total
                if !detail.isEmpty {
                    steps[idx].detail = detail
                }
                
                // Timer tracking
                if status == .running && steps[idx].startTime == nil {
                    steps[idx].startTime = Date()
                }
                if status == .done || status == .skipped || status == .error {
                    if steps[idx].endTime == nil {
                        steps[idx].endTime = Date()
                    }
                }
            }
        }
    }

    // MARK: - Sync Logic

    private func startSync() {
        phase = .running

        pipelineTask = Task {
            do {
                let deletes = deleteActions
                let adds = addActions

                // --- Phase: Delete from KG ---
                if !deletes.isEmpty {
                    updateStep("upload_delete", status: .running, total: deletes.count)

                    // Fallible block: Don't stop the whole pipeline if uploading deletes fails
                    var deleted = 0
                    var failedWords: [String] = []
                    for entry in deletes {
                        if Task.isCancelled { break }
                        do {
                            try await kgService.deleteCard(word: entry.word)
                            modelContext.delete(entry)
                            deleted += 1
                            updateStep("upload_delete", status: .running, current: deleted, total: deletes.count)
                        } catch {
                            failedWords.append(entry.word)
                        }
                    }
                    try? modelContext.save()

                    if failedWords.isEmpty {
                        updateStep("upload_delete", status: .done, current: deleted, total: deleted,
                                   detail: "已刪除 \(deleted) 個單字")
                    } else {
                        updateStep("upload_delete", status: .error, current: deleted, total: deletes.count,
                                   detail: "部分失敗: \(failedWords.joined(separator: ", "))")
                    }
                }

                // --- Phase: Upload adds to KG ---
                if !adds.isEmpty {
                    updateStep("upload_add", status: .running, total: adds.count)

                    do {
                        let response = try await kgService.batchAdd(entries: adds)

                        for entry in adds {
                            if let cardId = response.cardIds[entry.word] {
                                entry.kgCardId = cardId
                            }
                        }
                        try? modelContext.save()

                        let newCount = response.created
                        let skipCount = response.skipped
                        updateStep("upload_add", status: .done, current: adds.count, total: adds.count,
                                   detail: "\(newCount) 新增, \(skipCount) 已存在")
                    } catch {
                        updateStep("upload_add", status: .error, current: 0, total: adds.count, detail: error.localizedDescription)
                    }
                }

                // --- Phase: Trigger Pipeline ---
                updateStep("trigger", status: .running)
                do {
                    try await kgService.triggerPipeline()
                    updateStep("trigger", status: .done, detail: "已交由伺服器背景處理")
                } catch {
                    updateStep("trigger", status: .error, detail: "無法觸發: \(error.localizedDescription)")
                }

                // --- Phase: Pull Latest Knowledge Graph ---
                updateStep("pull", status: .running, detail: "Fetching cards from KG...")
                
                try await kgService.pullCardsToLocal(container: modelContext.container) { detail, current, total in
                    Task { @MainActor in
                        updateStep("pull", status: .running, current: current, total: total, detail: detail)
                    }
                }
                
                await MainActor.run {
                    updateStep("pull", status: .done, current: 1, total: 1, detail: "本地知識庫已建立完成")
                    phase = .completed
                }

            } catch {
                await MainActor.run {
                    summaryText = error.localizedDescription
                    phase = .failed
                }
            }
        }
    }

    private func cancelSync() {
        pipelineTask?.cancel()
        pipelineTask = nil
        phase = .failed
        summaryText = "同步已取消"
    }

    private func resetForRetry() {
        buildSteps()
        phase = .ready
        summaryText = ""
    }
}

// MARK: - Helper Views

struct StepDurationView: View {
    let step: PipelineStep
    
    var body: some View {
        if let start = step.startTime {
            if let end = step.endTime {
                Text(formatDuration(end.timeIntervalSince(start)))
                    .font(AppFonts.monoNumbers(size: 12))
                    .foregroundStyle(.tertiary)
            } else {
                TimelineView(.periodic(from: .now, by: 0.1)) { timeline in
                    Text(formatDuration(timeline.date.timeIntervalSince(start)))
                        .font(AppFonts.monoNumbers(size: 12))
                        .foregroundStyle(step.status == .retry ? AppColors.warning(.light) : .secondary) // Fallback color scheme, ideally using environment but tertiary/secondary are adaptive
                }
            }
        }
    }
    
    private func formatDuration(_ duration: TimeInterval) -> String {
        return String(format: "%.1fs", duration)
    }
}
