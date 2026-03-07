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
    @Environment(\.vocabSkin) private var vocabSkin
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
                headerView
                    .padding(.top, 32)
                    .padding(.bottom, 24)
                    .animation(.spring(response: 0.4, dampingFraction: 0.8), value: phase)

                if authManager.isLoggedIn && !steps.isEmpty {
                    VocabCard(padding: 0) {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(Array(steps.enumerated()), id: \.element.id) { index, step in
                                stepRow(step)

                                if index < steps.count - 1 {
                                    Divider()
                                        .padding(.leading, 32)
                                }
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 6)
                    }
                    .padding(.horizontal, 20)
                }

                Spacer()

                if !summaryText.isEmpty {
                    Text(summaryText)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(phase == .failed ? vocabSkin.palette.destructive : vocabSkin.palette.secondaryText)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 24)
                        .padding(.bottom, 12)
                }

                actionButton
                    .padding(.horizontal, 20)
                    .padding(.bottom, 20)
            }
            .vocabCanvasBackground()
            .navigationTitle("同步")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.hidden, for: .navigationBar)
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
                    .font(.system(size: 44, weight: .light))
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                Text("尚未登入帳號")
                    .font(vocabSkin.typography.sectionTitle)
                Text("登入後即可將您的生詞庫同步至雲端與 Mochi。")
                    .font(vocabSkin.typography.body)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
                    .padding(.horizontal, 40)
            }
        } else {
            switch phase {
            case .ready:
                VStack(spacing: 8) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(.system(size: 44, weight: .light))
                        .foregroundStyle(vocabSkin.palette.accent)

                    if pendingEntries.isEmpty {
                        Text("強制同步到 Mochi")
                            .font(vocabSkin.typography.sectionTitle)
                    } else {
                        let dels = deleteActions.count
                        let adds = addActions.count
                        VStack(spacing: 4) {
                            Text("\(pendingEntries.count) 個待處理動作")
                                .font(vocabSkin.typography.sectionTitle)
                            HStack(spacing: vocabSkin.spacing.inlineGap) {
                                if adds > 0 {
                                    VocabToneChip(text: "\(adds) 新增", tone: vocabSkin.palette.success)
                                }
                                if dels > 0 {
                                    VocabToneChip(text: "\(dels) 刪除", tone: vocabSkin.palette.destructive)
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
                    .font(vocabSkin.typography.sectionTitle)
            }
            .transition(.blurReplace)
        case .completed:
            VStack(spacing: 8) {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 44, weight: .light))
                    .foregroundStyle(vocabSkin.palette.success)
                    .symbolEffect(.bounce)
                Text("同步完成")
                    .font(vocabSkin.typography.sectionTitle)
            }
            .transition(.blurReplace)
        case .failed:
            VStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 44, weight: .light))
                    .foregroundStyle(vocabSkin.palette.destructive)
                Text("同步失敗")
                    .font(vocabSkin.typography.sectionTitle)
            }
            .transition(.blurReplace)
        }
        }
    }

    // MARK: - Step Row

    private func stepRow(_ step: PipelineStep) -> some View {
        HStack(spacing: 12) {
            Group {
                switch step.status {
                case .waiting:
                    Image(systemName: "circle")
                        .foregroundStyle(vocabSkin.palette.quaternaryText)
                case .running:
                    ProgressView()
                        .controlSize(.small)
                case .retry:
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .symbolEffect(.scale.up, options: .repeating)
                        .foregroundStyle(vocabSkin.tierColor(for: "intermediate"))
                case .done:
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(vocabSkin.palette.success)
                        .symbolEffect(.bounce)
                case .skipped:
                    Image(systemName: "minus.circle.fill")
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                case .error:
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(vocabSkin.palette.destructive)
                }
            }
            .frame(width: 20)

            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(step.label)
                        .font(vocabSkin.typography.body.weight(.medium))
                        .foregroundStyle(step.status == .waiting ? vocabSkin.palette.tertiaryText : vocabSkin.palette.primaryText)
                    Spacer()
                    if step.status == .running && step.total > 0 {
                        Text("\(step.current)/\(step.total)")
                            .font(vocabSkin.typography.monoLabel)
                            .foregroundStyle(vocabSkin.palette.secondaryText)
                            .contentTransition(.numericText())
                            .animation(.spring, value: step.current)
                    }

                    StepDurationView(step: step)
                }

                if !step.detail.isEmpty && step.status != .waiting {
                    let detailColor = step.status == .error ? vocabSkin.palette.destructive :
                                      step.status == .retry ? vocabSkin.tierColor(for: "intermediate") :
                                      vocabSkin.palette.secondaryText

                    Text(step.detail)
                        .font(vocabSkin.typography.caption)
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
                .buttonStyle(.vocabAction(.primary))
                .disabled(!kgService.isConnected)

                if !kgService.isConnected {
                    Text("KG 伺服器未連線")
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.destructive)
                }
            } else {
                Button {
                    showSettings = true
                } label: {
                    Text("前往設定登入")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.vocabAction(.neutral))
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
            .buttonStyle(.vocabAction(.neutral))
        case .completed:
            Button {
                dismiss()
            } label: {
                Text("完成")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.vocabAction(.primary))
        case .failed:
            Button {
                resetForRetry()
            } label: {
                Label("重試", systemImage: "arrow.clockwise")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.vocabAction(.warning))
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
    @Environment(\.vocabSkin) private var vocabSkin
    let step: PipelineStep
    
    var body: some View {
        if let start = step.startTime {
            if let end = step.endTime {
                Text(formatDuration(end.timeIntervalSince(start)))
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            } else {
                TimelineView(.periodic(from: .now, by: 0.1)) { timeline in
                    Text(formatDuration(timeline.date.timeIntervalSince(start)))
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(step.status == .retry ? vocabSkin.tierColor(for: "intermediate") : vocabSkin.palette.secondaryText)
                }
            }
        }
    }
    
    private func formatDuration(_ duration: TimeInterval) -> String {
        return String(format: "%.1fs", duration)
    }
}
