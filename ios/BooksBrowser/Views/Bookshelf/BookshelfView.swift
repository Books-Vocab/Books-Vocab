#if os(iOS)
//
//  BookshelfView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import TipKit
import UniformTypeIdentifiers
import Inject

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
            .navigationTitle("書庫".localized)
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
                    .accessibilityLabel("設定".localized)
                    .accessibilityIdentifier("bookshelf.settingsButton")

                    #if targetEnvironment(macCatalyst)
                    // 可見的同步 affordance（Mac 無 pull-to-refresh）。⌘R 由
                    // `MacMenuCommands` 全域擁有（任一畫面可觸發），此處**不**再綁一次
                    // ⌘R 以免雙重綁定；兩者均經 `ExplicitSync` 給一致的 toast 回饋。
                    Button(action: { Task { await performSync() } }) {
                        AppToolbarGlyph(systemImage: "arrow.clockwise")
                    }
                    .accessibilityLabel("同步".localized)
                    .accessibilityIdentifier("bookshelf.refreshButton")
                    #endif
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: coordinator.presentImporter) {
                        AppToolbarGlyph(systemImage: "plus")
                    }
                    .accessibilityLabel("匯入".localized)
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
                coordinator.errorDiagnosis.map { L10n.format("匯入錯誤・%@", $0) } ?? "匯入錯誤".localized,
                isPresented: $coordinator.showError
            ) {
                Button("確定".localized, role: .cancel, action: coordinator.dismissError)
            } message: {
                Text(coordinator.errorMessage ?? "未知錯誤".localized)
            }
            .settingsSheet(isPresented: $coordinator.showSettings)
            .loginGateSheet($loginGate)
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
        ScrollView {
            // Mochi 16/24 節奏 — 用 s4 取代既有 s5(20)，對齊 Mochi long-form 留白
            VStack(spacing: AppSpacing.s4) {
                Spacer(minLength: 120)

                AppEmptyStateContent(
                    title: "尚無書籍".localized,
                    systemImage: "book",
                    description: "匯入電子書開始閱讀（EPUB・TXT・MD・PDF）".localized,
                    guidanceText: "點擊上方匯入按鈕加入你的第一本書",
                    style: .bookshelf(appTheme)
                )

                TipView(EPUBGuideTip()) { action in
                    if action.id == EPUBGuideTip.guideActionID {
                        openURL(AppURLs.guide)
                    }
                }
                .padding(.horizontal)

                Button("匯入".localized) {
                    coordinator.presentImporter()
                }
                .buttonStyle(.appAction(.outline))
                .fixedSize(horizontal: false, vertical: true)

                if !authManager.isDemoMode && !authManager.isLoggedIn {
                    Button(action: { loginGate.presentLogin() }) {
                        Label("登入帳號".localized, systemImage: "person.crop.circle")
                    }
                    .buttonStyle(.appAction(.outline))

                    Button(action: {
                        authManager.enterDemoMode(modelContainer: modelContext.container)
                    }) {
                        HStack(spacing: 6) {
                            Image(systemName: "play.circle")
                            Text("體驗複習與圖譜".localized)
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
                    .accessibilityLabel("\(book.title), \(book.author)")
                    .accessibilityHint("點兩下開始閱讀".localized)
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
                            Label("刪除".localized, systemImage: "trash")
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
            Text("了解更多".localized)
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
            title: coordinator.errorDiagnosis.map { L10n.format("匯入錯誤・%@", $0) } ?? "匯入錯誤".localized,
            systemImage: "exclamationmark.triangle",
            description: message.localized
        ) {
            HStack(spacing: AppSpacing.s2) {
                Button("再試匯入".localized) {
                    coordinator.presentImporter()
                }
                .buttonStyle(.appCompactAction(.primary))

                Button("關閉".localized) {
                    coordinator.clearError()
                }
                .buttonStyle(.appCompactAction(.outline))
            }
        }
    }

    // MARK: - 載入覆蓋層

    private var loadingOverlay: some View {
        ZStack {
            appTheme.palette.scrim
                .ignoresSafeArea()

            VStack(spacing: AppSpacing.s4) {
                if let ratio = coordinator.loadingProgress {
                    ProgressView(value: ratio, total: 1.0)
                        .progressViewStyle(.linear)
                        .frame(width: AppBookshelfMetrics.loadingProgressWidth)
                } else {
                    ProgressView()
                        .scaleEffect(1.0)
                }
                Text(coordinator.loadingMessage)
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)
            }
            .padding(AppBookshelfMetrics.loadingOverlayPadding)
            .compatibleGlass(in: .rect(cornerRadius: AppRadius.md))
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
            .sensoryFeedback(.selection, trigger: configuration.isPressed) { _, newValue in newValue }
    }
}

extension ButtonStyle where Self == BookshelfCardButtonStyle {
    static var bookshelfCard: BookshelfCardButtonStyle { BookshelfCardButtonStyle() }
}
#endif
