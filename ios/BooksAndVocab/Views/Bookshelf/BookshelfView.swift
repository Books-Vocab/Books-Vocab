#if os(iOS)
//
//  BookshelfView.swift
//  Books & Vocab
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import TipKit
import UniformTypeIdentifiers

/// 書架主頁 — 簡約留白設計
struct BookshelfView: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.modelContext) private var modelContext

    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }
    @Environment(\.bookshelfImportService) private var bookshelfImportService
    @Environment(\.bookFileManager) private var bookFileManager
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.authManager) private var authManager
    @Environment(\.kgService) private var kgService
    @Query(sort: \Book.dateLastRead, order: .reverse) private var books: [Book]
    @State private var coordinator = BookshelfCoordinator()
    @State private var loginGate = LoginGateState()
    @State private var navigationPath = NavigationPath()

    // podcast 已抽離為獨立頂層 section（見 `PodcastHomeView`），本 view 回歸純書架：
    // 不再持有 podcastSeries query / overlay-pane selection / PodcastNavRoute 路由。
    // root content 恒定 + `navigationDestination(for: Book.self)` 的 reader push 契約保留。

    private var columns: [GridItem] { [layoutMode.bookshelfGridItem] }

    private var coverHeight: CGFloat { layoutMode.bookshelfCoverHeight }

    var body: some View {
        NavigationStack(path: $navigationPath) {
            ZStack {
                appTheme.palette.pageBackground
                    .ignoresSafeArea()

                // root content 恒定：books grid / empty。這是 NavigationStack
                // 的直接 root subtree，其 structural identity **必須穩定**——
                // root-content swap 會永久破壞 value-based push（NAVDBG 坐實）。
                // 對齊 NotebookListView 的 root-恒定模式。
                if books.isEmpty {
                    emptyState
                } else {
                    bookGrid
                }

                if coordinator.isLoading {
                    loadingOverlay
                        .transition(.overlayFade)
                }
            }
            .safeAreaInset(edge: .top, spacing: 0) {
                if let message = coordinator.errorMessage, !coordinator.showError {
                    importErrorBanner(message: message)
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        .padding(.top, AppSpacing.s2)
                        .transition(.statusRowReveal)
                }
            }
            .animation(AppMotion.phaseChange, value: coordinator.showError)
            .animation(AppMotion.phaseChange, value: coordinator.errorMessage)
            .navigationTitle(BookshelfCopy.navigationTitle)
            .largeNavigationBarTitle()
            .animatePhaseChange(books.isEmpty)
            .animateContentFade(coordinator.isLoading)
            // navigationDestination 統一掛在 NavigationStack root，接住書籍 →
            // reader 的 value-based push（freeze-fix 契約；podcast 路由已隨
            // 獨立 section 遷出至 `PodcastHomeView`）。
            .navigationDestination(for: Book.self) { book in
                switch book.format {
                case .epub, .txt, .md:
                    ReaderView(book: book)
                case .pdf:
                    PDFReaderView(book: book)
                }
            }
            .toolbar {
                ToolbarItemGroup(placement: .topBarLeading) {
                    Button(action: coordinator.presentSettings) {
                        AppToolbarGlyph(systemImage: "gearshape")
                    }
                    .accessibilityLabel(BookshelfCopy.settingsAccessibilityLabel)
                    .accessibilityIdentifier("bookshelf.settingsButton")

                    #if targetEnvironment(macCatalyst)
                    // 可見的同步 affordance（Mac 無 pull-to-refresh）。⌘R 由
                    // `MacMenuCommands` 全域擁有（任一畫面可觸發），此處**不**再綁一次
                    // ⌘R 以免雙重綁定；兩者均經 `ExplicitSync` 給一致的 toast 回饋。
                    Button(action: { Task { await performSync() } }) {
                        AppToolbarGlyph(systemImage: "arrow.clockwise")
                    }
                    .accessibilityLabel(BookshelfCopy.syncAccessibilityLabel)
                    .accessibilityIdentifier("bookshelf.refreshButton")
                    #endif
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: coordinator.presentImporter) {
                        AppToolbarGlyph(systemImage: "plus")
                    }
                    .accessibilityLabel(BookshelfCopy.importAccessibilityLabel)
                    .accessibilityIdentifier("bookshelf.importButton")
                }
            }
            .fileImporter(
                isPresented: $coordinator.isImporting,
                allowedContentTypes: [
                    UTType(filenameExtension: "epub") ?? .data,
                    .plainText,
                    UTType(filenameExtension: "md") ?? .data,
                    .pdf,
                ],
                allowsMultipleSelection: true
            ) { result in
                coordinator.handleFileImport(
                    result,
                    modelContext: modelContext,
                    importService: bookshelfImportService,
                    toastCoordinator: toastCoordinator
                )
            }
            .alert(
                BookshelfCopy.importErrorTitle(diagnosis: coordinator.errorDiagnosis),
                isPresented: $coordinator.showError
            ) {
                Button(BookshelfCopy.confirmButtonTitle, role: .cancel, action: coordinator.dismissError)
            } message: {
                Text(coordinator.errorMessage ?? BookshelfCopy.unknownErrorTitle)
            }
            .settingsSheet(isPresented: $coordinator.showSettings)
            .loginGateSheet($loginGate)
            .onAppear {
                // probe rig：見 AppRuntimeOptions.shouldOpenSettingsOnLaunch。
                if AppRuntimeOptions.shouldOpenSettingsOnLaunch() {
                    coordinator.showSettings = true
                }
            }
        }
        // 匯入書籍 ⌘I(Mac menu)— 對應 toolbar importButton。
        .focusedSceneValue(\.importBook, ImportBookAction { coordinator.presentImporter() })
        .enableInjection()
    }

    /// Shared sync action for pull-to-refresh (iOS/iPadOS) and toolbar button (Mac Catalyst).
    /// 資格 gate（登出 / demo → no-op）由 `ExplicitSync` 集中處理，此處只供 facts。
    private func performSync() async {
        await coordinator.sync(
            container: modelContext.container,
            kgService: kgService,
            isLoggedIn: authManager.isLoggedIn,
            isDemoMode: authManager.isDemoMode,
            toastCoordinator: toastCoordinator
        )
    }

    // MARK: - 空狀態

    @Environment(\.openURL) private var openURL

    private var emptyState: some View {
        let copy = BookshelfCopy.emptyState
        return ScrollView {
            // Mochi 16/24 節奏 — 用 s4 取代既有 s5(20)，對齊 Mochi long-form 留白
            VStack(spacing: AppSpacing.s4) {
                Spacer(minLength: 120)

                AppEmptyStateContent(
                    title: copy.title,
                    systemImage: "book",
                    description: copy.description,
                    guidanceText: copy.guidanceText,
                    style: .bookshelf(appTheme)
                )
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("bookshelf.emptyState")

                // 空 ≠ 真空：CloudKit 還原/失敗時明說，0 列才不會被誤讀成
                // 「沒有書」（2026-06-11 書庫透明化）。settled / localOnly 不渲染。
                cloudRestoreStatus

                TipView(EPUBGuideTip()) { action in
                    if action.id == EPUBGuideTip.guideActionID {
                        openURL(AppURLs.guide)
                    }
                }
                .padding(.horizontal)

                Button(copy.primaryActionTitle) {
                    coordinator.presentImporter()
                }
                .buttonStyle(.appAction(.outline))
                .accessibilityIdentifier("bookshelf.emptyState.importButton")
                .fixedSize(horizontal: false, vertical: true)

                if !authManager.isDemoMode && !authManager.isLoggedIn {
                    Button(action: { loginGate.presentLogin() }) {
                        Label(copy.loginActionTitle, systemImage: "person.crop.circle")
                    }
                    .buttonStyle(.appAction(.outline))
                    .accessibilityIdentifier("bookshelf.emptyState.loginButton")

                    Button(action: {
                        authManager.enterDemoMode(modelContainer: modelContext.container)
                    }) {
                        HStack(spacing: 6) {
                            Image(systemName: "play.circle")
                            Text(copy.demoActionTitle)
                        }
                        .font(AppFonts.caption(weight: .medium))
                        .foregroundStyle(appTheme.palette.accent)
                    }
                    .buttonStyle(.plain)
                }

                Spacer(minLength: 120)
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        }
#if !targetEnvironment(macCatalyst)
        .refreshable {
            await performSync()
        }
#endif
    }

    private var cloudMonitor: CloudKitMirroringMonitor { .shared }

    @ViewBuilder
    private var cloudRestoreStatus: some View {
        switch cloudMonitor.phase {
        case .waitingFirstEvent, .restoring:
            HStack(spacing: AppSpacing.s2) {
                ProgressView()
                    .controlSize(.small)
                Text(cloudMonitor.phase == .restoring
                     ? BookshelfCopy.cloudRestoringHint
                     : BookshelfCopy.cloudCheckingHint)
                    .font(AppFonts.caption(weight: .medium))
                    .foregroundStyle(appTheme.palette.secondaryText)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("bookshelf.emptyState.cloudStatus")
        case .failed(let message):
            Label(BookshelfCopy.cloudSyncErrorHint(message), systemImage: "exclamationmark.icloud")
                .font(AppFonts.caption(weight: .medium))
                .foregroundStyle(appTheme.palette.warning)
                .multilineTextAlignment(.center)
                .accessibilityIdentifier("bookshelf.emptyState.cloudStatus")
        case .settled, .localOnly:
            EmptyView()
        }
    }

    // MARK: - 書籍網格

    // bookGrid 僅在 body 的 `else`（!books.isEmpty）分支渲染，故無須內層 guard
    // （podcast section 移出後攤平；攤平前的 `if !books.isEmpty` 為恒真死碼）。
    private var bookGrid: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: AppShellMetrics.sectionSpacing) {
                ForEach(books) { book in
                    NavigationLink(value: book) {
                        BookCard(book: book, coverHeight: coverHeight)
                    }
                    .buttonStyle(.bookshelfCard)
                    .accessibilityIdentifier("book.card.\(book.id.uuidString)")
                    .accessibilityLabel("\(book.title), \(book.author)")
                    .accessibilityHint(BookshelfCopy.readBookHint)
                    .transition(.bookshelfCard)
                    .contextMenu {
                        Button(role: .destructive) {
                            coordinator.deleteBook(
                                book,
                                modelContext: modelContext,
                                fileManager: bookFileManager,
                                toastCoordinator: toastCoordinator
                            )
                        } label: {
                            Label(BookshelfCopy.deleteTitle, systemImage: "trash")
                        }
                    }
                }
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppSpacing.s2)
            .animateContentFade(books.count)

            epubGuideHint
                .padding(.top, AppSpacing.s6)
                .padding(.bottom, AppSpacing.s7)
        }
#if !targetEnvironment(macCatalyst)
        .refreshable {
            await performSync()
        }
#endif
    }

    // MARK: - EPUB 取得提示

    private var epubGuideHint: some View {
        Link(destination: AppURLs.guide) {
            Text(BookshelfCopy.readMoreTitle)
                .font(AppFonts.caption2())
                .foregroundStyle(appTheme.palette.quaternaryText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, AppSpacing.s2)
        }
    }

    // MARK: - 匯入錯誤橫幅

    /// Alert 關閉後仍持續顯示的 inline error；提供「再試匯入」與「關閉」CTA。
    /// 對齊 `ui_state_matrix.md`：alert 是 transient，inline banner 是 persistent。
    @ViewBuilder
    private func importErrorBanner(message: String) -> some View {
        AppStateMessageCard(
            title: BookshelfCopy.importErrorTitle(diagnosis: coordinator.errorDiagnosis),
            systemImage: "exclamationmark.triangle",
            description: message.localized
        ) {
            HStack(spacing: AppSpacing.s2) {
                Button(BookshelfCopy.retryImportTitle) {
                    coordinator.presentImporter()
                }
                .buttonStyle(.appCompactAction(.primary))

                Button(BookshelfCopy.closeTitle) {
                    coordinator.clearError()
                }
                .buttonStyle(.appCompactAction(.outline))
            }
        }
    }

    // MARK: - 載入覆蓋層

    private var loadingOverlay: some View {
        BookshelfLoadingOverlay(
            message: coordinator.loadingMessage,
            progress: coordinator.loadingProgress
        )
    }

}

struct BookshelfLoadingOverlay: View {
    @Environment(\.appTheme) private var appTheme
    let message: String
    let progress: Double?

    var body: some View {
        ZStack {
            appTheme.palette.scrim
                .ignoresSafeArea()

            AppStateMessageCard(
                title: message.localized,
                systemImage: "square.and.arrow.down",
                style: .themed(appTheme)
            ) {
                if let progress {
                    ProgressView(value: progress, total: 1.0)
                        .progressViewStyle(.linear)
                        .frame(width: AppBookshelfMetrics.loadingProgressWidth)
                } else {
                    ProgressView()
                        .controlSize(.regular)
                }
            }
            .frame(maxWidth: 360)
            .padding(AppBookshelfMetrics.loadingOverlayPadding)
        }
    }
}

// MARK: - 書架卡 Button Style（Mochi 北極星五：TapFeedback triplet，無 elevation 升降）

/// 封面卡 press feedback：scale + opacity + haptic，resting/press 都不換 elevation 階。
/// 取代既有 `.liftable`（liftable 會 z1↔z2 切換，違反 list 卡 resting z0 的鐵律）。
/// `internal`（非 fileprivate）— `PodcastHomeView` 的 series 卡共用同一 tap feedback。
struct BookshelfCardButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? AppMotion.TapFeedback.scaleDown : 1)
            .opacity(configuration.isPressed ? AppMotion.TapFeedback.opacityDip : 1)
            .animation(AppMotion.TapFeedback.animation, value: configuration.isPressed)
            .appFeedback(.selection, trigger: configuration.isPressed) { _, newValue in newValue }
    }
}

extension ButtonStyle where Self == BookshelfCardButtonStyle {
    static var bookshelfCard: BookshelfCardButtonStyle { BookshelfCardButtonStyle() }
}
#endif
