import SwiftUI

// MARK: - Data in

/// 畫一張複習卡所需要的全部資料。與複習 session 的互動狀態無關 —— 這是把卡片從
/// 「先造一個 presenter」的型別枷鎖裡解出來的那一刀。
struct ReviewCardContent {
    let card: CardPresentation
    let linkGroups: [ReviewCardLinkGroup]
    let backDocument: CardDocument
}

struct ReviewCardLinkGroup: Identifiable {
    let id: String
    let label: String
    let items: [KGCardLinkSummary]
    let overflowCount: Int
}

/// 卡片能發出的意圖。欄位全 optional；`.none` ＝ 純展示（設定頁預覽 / catalog），
/// 一顆 callback 都不接。
struct ReviewCardActions {
    var advanceReveal: (() -> Void)? = nil
    var collapseReveal: (() -> Void)? = nil
    var detailTap: (() -> Void)? = nil
    var linkTap: ((KGCardLinkSummary) -> Void)? = nil
    var addLink: (() -> Void)? = nil
    var explainCollocation: ((String) -> Void)? = nil
    var viewCollocationExplanation: ((String) -> Void)? = nil
    var deleteCollocationExplanation: ((String) -> Void)? = nil

    static let none = ReviewCardActions()
}

// MARK: - Review Card

/// 一張完整的複習卡：正面摺頁 ＋ 右上角 chrome ＋ 背面摺頁 ＋ 摺疊動畫。
///
/// 輸入全是資料。牌堆的事（slot transform、高度 cap、clipShape、geometryGroup、
/// zIndex、animation、gesture、DEBUG 幾何探針）留在 `TodayReviewSwipeDeck`，
/// 互動鎖由呼叫端算好後用 `interactive` 傳進來 —— 卡片內部不判 dismiss 相位。
///
/// `profile` 走參數而非 `@Environment(\.reviewCardLayoutStore)`：設定頁的即時預覽
/// 必須能餵一份尚未落地的 draft profile。
struct ReviewCardView: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.speechService) private var speechService

    let content: ReviewCardContent
    let profile: ReviewCardLayoutProfile
    let viewport: ReviewCardViewport
    let showsAnswer: Bool
    var mountsBack: Bool = true
    var interactive: Bool = true
    var borderOpacity: Double = TodayReviewMetrics.cardBorderActiveOpacity
    var measuresSections: Bool = true
    var collocationExplanations: [String: String] = [:]
    var actions: ReviewCardActions = .none
    var onFrontHeightChange: ((CGFloat) -> Void)? = nil

    /// 三階量測快取，屬於這張卡自己（原本住在 presenter 的 @State，只有卡片渲染
    /// 讀寫）。
    @State private var reviewNaturalSectionHeights: [ReviewCardMeasurementKey: CGFloat] = [:]
    @State private var reviewIntermediateSectionHeights: [ReviewCardMeasurementKey: CGFloat] = [:]
    @State private var reviewCompactSectionHeights: [ReviewCardMeasurementKey: CGFloat] = [:]
    /// 自量的寬度（量測 key 的 bucket）與正面高度（背面預算的被減數）。
    @State private var containerWidth: CGFloat = 393
    @State private var measuredFrontHeight: CGFloat = 0

    var body: some View {
        VStack(spacing: 0) {
            frontFoldSurface(
                content,
                showsAnswer: showsAnswer,
                interactive: interactive,
                borderOpacity: borderOpacity,
                viewport: viewport
            )
            .overlay(alignment: .topTrailing) {
                // chrome 常駐於每張卡（裝飾），只有互動中的那張可點 —— promote 時
                // chrome 不換樹、無「裸卡 pop」。
                frontCardChrome(content.card, interactive: interactive)
            }
            // 正面實測高度：背面預算的被減數，同時回吐給牌堆去填 slotFrontHeights。
            // 兩份量測只留這一份。
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                guard height > 0, abs(measuredFrontHeight - height) > 0.5 else { return }
                measuredFrontHeight = height
                onFrontHeightChange?(height)
            }

            // 永遠存在於 view tree — PaperFoldModifier(Animatable) 直接驅動摺疊動畫。
            // frame(height: 0) 使摺疊時不佔 layout 空間，但內部 minHeight 使 view 仍以
            // 完整尺寸渲染（fold 視覺正確）。
            answerFoldSurface(content, viewport: viewport, mounted: mountsBack)
                .padding(.top, TodayReviewMetrics.stackLayerMicroOffset)
                .modifier(PaperFoldModifier(progress: showsAnswer ? 1 : 0))
                .frame(height: showsAnswer ? nil : 0, alignment: .top)
                .allowsHitTesting(showsAnswer)
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { newWidth in
            guard newWidth > 0, abs(containerWidth - newWidth) > 0.5 else { return }
            containerWidth = newWidth
        }
        .enableInjection()
    }

    // MARK: Dimensions

    var reviewCardPadding: CGFloat { TodayReviewMetrics.foldPadding }
    var answerCardHeight: CGFloat { TodayReviewMetrics.answerMinHeight }

    /// 右上角 chrome（喇叭 + 詳情）兩顆 44pt HIG 觸控框 + 中間 inlineGap 的總寬，
    /// 供單字列保留 trailing 空間，避免長詞被圖示擋住。與 frontCardChrome 佈局同源。
    var frontChromeReserveWidth: CGFloat { 44 * 2 + appSkin.spacing.inlineGap }

    // MARK: Front Surface

    /// 卡正面摺頁面。`showsAnswer` / `interactive` 由呼叫端投影（牌堆的 preview slot
    /// 恆 false），`borderOpacity` 由 `TodayReviewCardSlotLayout.borderOpacity` 內插
    /// （0.45 → 0.72），promote 翻面時邊框零 pop。`todayReview.card.front` a11y
    /// 識別子只掛在互動中的那張。
    func frontFoldSurface(
        _ currentCard: ReviewCardContent,
        showsAnswer: Bool,
        interactive: Bool,
        borderOpacity: Double,
        viewport: ReviewCardViewport
    ) -> some View {
        let card = currentCard.card
        let layout = reviewCardLayout(for: currentCard, face: .front, availableHeight: viewport.frontHeight)
        // `viewport.frontHeight` 是天花板，不是繪製高度：正面貼合解出的內容（保留
        // 120pt 地板），剩下的空間讓給 reveal zone / 背面，不再被貪婪 frame 吃掉一半。
        let drawnHeight = viewport.frontDrawnHeight(
            solvedContentHeight: layout.cardHeight,
            chrome: ReviewCardChrome.verticalInset(for: .front)
        )
        let _ = PerfLog.render.tick("todayReview.front.surface", "mode=\(card.reviewMode.rawValue)")
        // `interactive` 的 guard 必須留著：沒有它，設定頁預覽或 catalog 每次重繪都會
        // 吃掉複習畫面的 fling 計時器，兩個不相干的畫面互相污染。
        if interactive, let clock = TodayReviewState.flingClock {
            PerfLog.review.mark("front.gap", "w=\(card.word) \(PerfChannel.ms(since: clock))ms (fling->current-front body)")
            TodayReviewState.flingClock = nil
        }
        return ReviewFoldSurface(
            position: showsAnswer ? .top : .single,
            borderOpacity: borderOpacity
        ) {
            frontFaceContent(
                currentCard,
                layout: layout,
                drawnHeight: drawnHeight,
                measuresSections: measuresSections && interactive
            )
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .frame(height: drawnHeight, alignment: .topLeading)
            .contentShape(Rectangle())
            .onTapGesture {
                guard !showsAnswer, interactive else { return }
                actions.advanceReveal?()
            }
            // The face is an accessibility CONTAINER, not one merged element.
            // Without this declaration the `.accessibilityLabel` below has no
            // element to attach to, so SwiftUI synthesises one by MERGING the whole
            // face and pushes every property modifier down the subtree: VoiceOver
            // loses the face's own buttons (collocations / knowledge links / add
            // link) and `todayReview.card.front` gets republished on 2–3 nested
            // ~36pt buttons, so a UI-test query resolves a child instead of the card
            // box. Declared BEFORE the property modifiers so that identifier / label
            // / hint / action land on the container itself and stop propagating.
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier(interactive ? "todayReview.card.front" : "")
            .accessibilityLabel(L10n.format("複習卡片正面：%@", card.word))
            .accessibilityHint(showsAnswer || !interactive ? "" : "點一下翻轉卡片".localized)
            .accessibilityAction {
                guard !showsAnswer, interactive else { return }
                actions.advanceReveal?()
            }
        }
    }

    @ViewBuilder
    private func frontFaceContent(
        _ currentCard: ReviewCardContent,
        layout: ReviewCardLayoutSolver.Result,
        drawnHeight: CGFloat,
        measuresSections: Bool
    ) -> some View {
        // 具體高度，不是上界：`.frame(maxHeight:)` 會把父層提案照單全收（彈性 frame
        // 是貪婪的），內容只有一行單字時也一樣。`drawnHeight` 由解出的內容推導，
        // 所以畫出來的高度與 solver 記帳的高度仍是同一個值。
        if layout.requiresScrollFallback {
            ScrollView(.vertical) {
                reviewCardFront(currentCard, layout: layout, measuresSections: measuresSections)
            }
                .frame(height: drawnHeight, alignment: .top)
        } else {
            ViewThatFits(in: .vertical) {
                reviewCardFront(currentCard, layout: layout, measuresSections: measuresSections)
                    .fixedSize(horizontal: false, vertical: true)
                ScrollView(.vertical) {
                    reviewCardFront(currentCard, layout: layout, measuresSections: measuresSections)
                }
            }
            .frame(height: drawnHeight, alignment: .top)
        }
    }

    /// 卡片右上角 chrome（喇叭 / 詳情）。互動中的卡片與背後預覽**共用同一渲染**，
    /// 確保 fling 飛出期間背後預覽已帶完整 chrome、完成時的 swap 隱形（消除「裸卡 pop」）。
    /// `interactive=false`（預覽）時純裝飾：無動作、不可點。
    @ViewBuilder
    func frontCardChrome(_ card: CardPresentation, interactive: Bool) -> some View {
        HStack(spacing: appSkin.spacing.inlineGap) {
            VocabChromeIconButton(
                systemImage: "speaker.wave.2.fill",
                label: "播放發音".localized,
                action: { if interactive { speechService.speak(card.word) } }
            )
            VocabChromeIconButton(
                systemImage: "arrow.up.right",
                label: "查看詳情".localized,
                action: { if interactive { actions.detailTap?() } }
            )
        }
        .padding(reviewCardPadding)
        .allowsHitTesting(interactive)
    }

    func reviewCardFront(
        _ currentCard: ReviewCardContent,
        layout: ReviewCardLayoutSolver.Result,
        measuresSections: Bool
    ) -> some View {
        let card = currentCard.card
        let plan = reviewCardRenderPlan(for: currentCard)
        let _ = PerfLog.review.mark("front.body", "w=\(card.word) answer=\(showsAnswer ? 1 : 0)")
        // Spacing comes from the solver's own arithmetic, never re-derived here.
        return VStack(alignment: .leading, spacing: layout.sectionSpacing) {
            HStack(alignment: .firstTextBaseline, spacing: AppSpacing.s2) {
                switch card.reviewMode {
                case .recognition:
                    Text(card.word)
                        .font(reviewFrontWordFont(for: card.word))
                        .foregroundStyle(appSkin.palette.primaryText)
                        .lineLimit(3)
                        .minimumScaleFactor(0.7)
                        .fixedSize(horizontal: false, vertical: true)
                case .production:
                    Text(card.translation)
                        .font(appSkin.typography.body.weight(.semibold))
                        .foregroundStyle(appSkin.palette.primaryTextMuted)
                        .minimumScaleFactor(0.75)
                }

                // Inline 欄位（詞性）與核心詞共用這條 firstTextBaseline —— 它是單字的
                // 附屬標註，不是自成一列的區塊。
                ForEach(plan.front.inlineFields, id: \.self) { field in
                    reviewOptionalField(
                        field,
                        currentCard: currentCard,
                        face: .front,
                        policy: layout.policy(for: .field(field))
                    )
                }
            }
            // 右上角 chrome（喇叭 / 詳情）是 overlay（必須在 reveal 手勢外才能獨立點），
            // 故在單字列保留其寬度的 trailing 空間，長詞（如 "be eaten alive"）在碰到
            // 圖示前先縮放 / 換行，不被擋字。
            .padding(.trailing, frontChromeReserveWidth)
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                recordReviewSectionHeight(
                    height,
                    currentCard: currentCard,
                    face: .front,
                    section: .core,
                    level: .natural
                )
            }

            ForEach(plan.front.blockFields, id: \.self) { field in
                reviewOptionalField(
                    field,
                    currentCard: currentCard,
                    face: .front,
                    policy: layout.policy(for: .field(field))
                )
                    .background {
                        if measuresSections {
                            reviewMeasurementProbes(
                                field,
                                currentCard: currentCard,
                                face: .front
                            )
                        }
                    }
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                        recordReviewSectionHeight(
                            height,
                            currentCard: currentCard,
                            face: .front,
                            section: .field(field),
                            level: layout.policy(for: .field(field)).measurementLevel
                        )
                    }
            }
        }
        .reviewCardFaceChrome(.front)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(minHeight: layout.cardHeight, alignment: .topLeading)
    }

    // MARK: Combined Answer Surface

    /// 答案摺頁面。`mounted` 由呼叫端投影（牌堆只讓互動中的那張掛真內容，其餘恆 stub）。
    func answerFoldSurface(
        _ currentCard: ReviewCardContent,
        viewport: ReviewCardViewport,
        mounted: Bool
    ) -> some View {
        let card = currentCard.card
        let answerText = card.reviewMode == .production ? card.word : card.translation
        return ReviewFoldSurface(position: .bottom) {
            // Subtraction probe: while the FRONT card is shown the back tree
            // (CardDocumentView / CardRichTextRenderer / VocabTierLabel /
            // reviewLinkStrip) is NOT built — only a zero-cost stub holds the
            // folded slot. Mount is gated by the caller's mount gate, NOT by
            // `showsAnswer`: on reveal it mounts under the opening fold's opacity-0
            // cover; on collapse it STAYS mounted until the PaperFoldModifier
            // progress 1→0 finishes, so the fold folds the REAL content.
            // stub 用 answerCardHeight 撐 minHeight，與真內容同源，
            // 避免折疊→展開時 intrinsic 高度跳動。
            Group {
                if mounted {
                    // Identifier AND label on the MOUNTED branch only, for two
                    // reasons. (1) UI tests read `todayReview.card.back`.exists as
                    // the real flip-state signal (the folded stub deliberately
                    // carries none). (2) The label used to sit on the enclosing
                    // Group, i.e. on BOTH branches: it merged the mounted back into
                    // a single element — VoiceOver could not step through the
                    // knowledge links, collocations or the add-link button — and it
                    // also turned the folded stub into an element announcing the
                    // answer while the card was still face down. Same container rule
                    // as the front face: declare `.contain` first, then attach.
                    combinedAnswerContent(currentCard, viewport: viewport)
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("todayReview.card.back")
                        .accessibilityLabel(L10n.format("翻譯：%@", answerText))
                } else {
                    let _ = PerfLog.review.mark("back.stub", "w=\(card.word)")
                    Color.clear
                        .frame(maxWidth: .infinity, minHeight: answerCardHeight, alignment: .top)
                }
            }
        }
        .overlay(alignment: .top) {
            ReviewFoldChevronPill(
                action: { actions.collapseReveal?() },
                accessibilityLabel: L10n.string("todayReview.fold.collapse")
            )
            .offset(y: -TodayReviewMetrics.chevronButtonSize / 2)
        }
    }

    func combinedAnswerContent(_ currentCard: ReviewCardContent, viewport: ReviewCardViewport) -> some View {
        let card = currentCard.card
        let _ = PerfLog.render.tick(
            "todayReview.answer.surface",
            "mode=\(card.reviewMode.rawValue) blocks=\(currentCard.backDocument.blocks.count)"
        )
        let plan = reviewCardRenderPlan(for: currentCard)
        // The outer insets are already out of `contentHeight`, so the front's
        // measured height is the only thing left to subtract — counting the insets
        // twice was the other half of the disagreeing-budget defect.
        //
        // 扣的是**這張卡自己**量到的正面高度。行為與扣牌堆的 activeCardHeight 等價：
        // 背面只有互動中的那張會 mount，而 activeShellHeight 回傳的就是那一格的高度。
        let backAvailableHeight = viewport.backHeight(
            frontOccupied: measuredFrontHeight + TodayReviewMetrics.stackLayerMicroOffset
        )
        let layout = reviewCardLayout(for: currentCard, face: .back, availableHeight: backAvailableHeight)
        let maxHeight = max(backAvailableHeight, 1)
        return Group {
            if layout.requiresScrollFallback {
                ScrollView(.vertical) { answerContent(currentCard, plan: plan, layout: layout) }
                    .frame(maxHeight: maxHeight)
            } else {
                ViewThatFits(in: .vertical) {
                    answerContent(currentCard, plan: plan, layout: layout)
                        .fixedSize(horizontal: false, vertical: true)
                    ScrollView(.vertical) { answerContent(currentCard, plan: plan, layout: layout) }
                }
                .frame(maxHeight: maxHeight)
            }
        }
    }

    @ViewBuilder
    private func answerContent(
        _ currentCard: ReviewCardContent,
        plan: ReviewCardRenderPlan,
        layout: ReviewCardLayoutSolver.Result
    ) -> some View {
        let card = currentCard.card
        // Same rule as the front face: draw the gap the solver charged.
        VStack(alignment: .leading, spacing: layout.sectionSpacing) {

            // 難度徽章畫在答案字**上方**、右對齊 —— 出貨版一直是這樣（見
            // a5885e228^ 的 combinedAnswerContent）。canonicalOrder 救不了這件事：
            // 它只排 field 彼此的先後，排不了 field 與 core 的先後。
            reviewBackFieldColumn(
                blockFields: plan.back.aboveCore,
                currentCard: currentCard,
                layout: layout
            )

            // Answer word + its section rule form ONE core section: the rule is the
            // core's own chrome (as on the shipped card), so it is measured with the
            // core rather than competing with the profile's fields for a slot.
            VStack(alignment: .leading, spacing: layout.sectionSpacing) {
                // 背面與正面對稱：inline 欄位貼著答案字，不自成一列。排除是
                // face-agnostic 的，只修正面會讓「背面開了詞性」這個組合直接掉字。
                HStack(alignment: .firstTextBaseline, spacing: AppSpacing.s2) {
                    Group {
                        if card.reviewMode == .production {
                            Text(card.word)
                        } else {
                            Text(card.translation)
                        }
                    }
                    .font(reviewAnswerWordFont(for: card.reviewMode == .production ? card.word : card.translation))
                    .foregroundStyle(appSkin.palette.primaryText)
                    .lineLimit(3)
                    .minimumScaleFactor(0.65)
                    .fixedSize(horizontal: false, vertical: true)

                    ForEach(plan.back.inlineFields, id: \.self) { field in
                        reviewOptionalField(
                            field,
                            currentCard: currentCard,
                            face: .back,
                            policy: layout.policy(for: .field(field))
                        )
                    }
                }

                // 這條線的規則是「答案底下還有東西才畫」。難度搬到上面之後，若使用者
                // 只開難度，底下已無內容 —— 再畫就是憑空多一條懸空分隔線。
                if ReviewCardLayoutSolver.drawsAnswerDivider(fields: plan.back.belowCore) {
                    CardSectionDivider(horizontalPadding: 0)
                }
            }
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                recordReviewSectionHeight(
                    height,
                    currentCard: currentCard,
                    face: .back,
                    section: .core,
                    level: .natural
                )
            }

            reviewBackFieldColumn(
                blockFields: plan.back.belowCore,
                currentCard: currentCard,
                layout: layout
            )
        }
        .reviewCardFaceChrome(.back)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(minHeight: layout.cardHeight, alignment: .topLeading)
    }

    /// 背面的一整欄 block 欄位。
    ///
    /// **body 只能是那個 ForEach**，不可包一層 VStack / Group-with-spacing：solver 收的是
    /// `max(sections.count - 1, 0)` 個 gap，而 ForEach 在 VStack 裡是攤平的（core + n 個
    /// 欄位 = n+1 個 sibling / n 個 gap）。包一層會讓外層只剩三個 sibling（兩個 gap）
    /// ＋內層自帶 spacing，畫出來的間距與 solver 記帳的間距當場分家；而且 aboveCore 為空
    /// 時 ForEach 貢獻 0 個 child，包 VStack 則多一個高度 0 卻仍吃一個 gap 的幽靈 child。
    @ViewBuilder
    private func reviewBackFieldColumn(
        blockFields: [ReviewCardField],
        currentCard: ReviewCardContent,
        layout: ReviewCardLayoutSolver.Result
    ) -> some View {
        // id: \.element 維持原本 id: \.self 的 view identity（不要換成 \.offset）。
        ForEach(Array(blockFields.enumerated()), id: \.element) { index, field in
            // rule 畫在欄位**前面**、當 VStack 的同層 sibling —— 不包進被量測的子樹，
            // 否則 natural 含線、隱藏 probe 量的另外兩階不含，階梯一壓縮就再度出現
            // 「solver 相信的高度 != 畫面畫的高度」。
            if ReviewCardLayoutSolver.drawsFieldDivider(face: .back, atIndex: index) {
                CardSectionDivider(horizontalPadding: 0)
            }

            reviewOptionalField(
                field,
                currentCard: currentCard,
                face: .back,
                policy: layout.policy(for: .field(field))
            )
                .background {
                    reviewMeasurementProbes(
                        field,
                        currentCard: currentCard,
                        face: .back
                    )
                }
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                    recordReviewSectionHeight(
                        height,
                        currentCard: currentCard,
                        face: .back,
                        section: .field(field),
                        level: layout.policy(for: .field(field)).measurementLevel
                    )
                }
        }
    }

    // MARK: Link Strip

    func reviewLinkStrip(
        _ groups: [ReviewCardLinkGroup],
        presentation: ReviewCardLayoutSolver.GraphLinkPresentation = .twoPerGroup
    ) -> some View {
        HStack(alignment: .top, spacing: appSkin.spacing.inlineGap) {
            Image(systemName: "paperclip")
                .font(appSkin.typography.iconTiny)
                .foregroundStyle(appSkin.palette.tertiaryText)
                .padding(.top, TodayReviewMetrics.answerHintTopPadding)

            VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
                ForEach(groups) { group in
                    HStack(spacing: AppSpacing.s1) {
                        Text(group.label.localized + "：")
                            .font(appSkin.typography.caption)
                            .foregroundStyle(appSkin.palette.tertiaryText)

                        let shownItems: [KGCardLinkSummary] = {
                            switch presentation {
                            case .twoPerGroup: Array(group.items.prefix(2))
                            case .onePerGroup: Array(group.items.prefix(1))
                            case .summary: []
                            }
                        }()
                        ForEach(Array(shownItems.enumerated()), id: \.element.id) { index, item in
                            Button { actions.linkTap?(item) } label: {
                                Text(item.word)
                                    .font(appSkin.typography.monoEmphasis)
                                    .foregroundStyle(appSkin.palette.primaryText)
                            }
                            .buttonStyle(.plain)

                            if index < shownItems.count - 1 {
                                Text("|")
                                    .font(appSkin.typography.caption)
                                    .foregroundStyle(appSkin.palette.quaternaryText)
                            }
                        }

                        let overflow = group.overflowCount + max(group.items.count - shownItems.count, 0)
                        if overflow > 0 {
                            Text("+\(overflow)")
                                .font(appSkin.typography.caption)
                                .foregroundStyle(appSkin.palette.quaternaryText)
                        }
                    }
                }
            }

            Spacer()

            Button(action: { actions.addLink?() }) {
                Image(systemName: "plus")
                    .font(appSkin.typography.iconSmall)
                    .foregroundStyle(appSkin.palette.secondaryText)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(L10n.string("vocab.card.addLink"))
            .accessibilityIdentifier("todayReview.card.addLink")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Shown by the graph-links section when the card has no links yet. It is the
    /// only place the review card can create its first link, which is why the
    /// section is always *available* even though its content is empty.
    private var addLinkPrompt: some View {
        Button(action: { actions.addLink?() }) {
            HStack(spacing: appSkin.spacing.inlineGap) {
                Image(systemName: "plus")
                    .font(appSkin.typography.iconTiny)
                Text("新增連結".localized)
                    .font(appSkin.typography.caption)
            }
            .foregroundStyle(appSkin.palette.tertiaryText)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("todayReview.card.addLink")
    }

    // MARK: - Render Plan / Adaptive Layout

    private func reviewCardRenderPlan(for currentCard: ReviewCardContent) -> ReviewCardRenderPlan {
        let card = currentCard.card
        return .make(
            profile: profile,
            mode: card.reviewMode,
            availability: .forReviewCard(
                partOfSpeech: card.partOfSpeech,
                difficultyTier: card.difficultyTier,
                exampleCount: card.examples.count,
                explanationParagraphCount: currentCard.backDocument.meaningParagraphs().count,
                collocationCount: card.collocations.count
            )
        )
    }

    private func reviewCardLayout(
        for currentCard: ReviewCardContent,
        face: ReviewCardFace,
        availableHeight: CGFloat
    ) -> ReviewCardLayoutSolver.Result {
        let plan = reviewCardRenderPlan(for: currentCard)
        // 只有 block 欄位向 solver 要一格預算。inline 欄位（詞性）畫在核心列裡，
        // 高度已經被 `.core` 的 onGeometryChange 量進去了。
        let fields = face == .front ? plan.front.blockFields : plan.back.blockFields
        // 同一組 blockFields 的兩欄分割（core 之上／之下）。hairline 逐欄記帳：
        // 一欄的第一格貼的是 core 不是另一格，接起來算 n-1 會多收一條。
        let columns = face == .front
            ? [plan.front.aboveCore, plan.front.belowCore]
            : [plan.back.aboveCore, plan.back.belowCore]
        let defaults: [ReviewCardLayoutSolver.Section: ReviewCardLayoutSolver.Measurement] = [
            .core: .init(naturalHeight: face == .front ? 112 : 132),
            .field(.partOfSpeech): .init(naturalHeight: 22),
            .field(.difficultyTier): .init(naturalHeight: 24),
            .field(.example): .init(naturalHeight: 88, compactHeight: 44),
            .field(.explanation): .init(naturalHeight: 66, intermediateHeight: 44, compactHeight: 22),
            .field(.collocations): .init(naturalHeight: 64, intermediateHeight: 48, compactHeight: 32),
            .field(.graphLinks): .init(naturalHeight: 72, intermediateHeight: 48, compactHeight: 20)
        ]
        let sections = [ReviewCardLayoutSolver.Section.core] + fields.map(ReviewCardLayoutSolver.Section.field)
        let measurements = Dictionary(uniqueKeysWithValues: sections.map { section in
            let key = reviewMeasurementKey(for: currentCard, face: face, section: section)
            let fallback = defaults[section] ?? .init(naturalHeight: 0)
            return (section, ReviewCardLayoutSolver.Measurement(
                naturalHeight: reviewNaturalSectionHeights[key] ?? fallback.naturalHeight,
                intermediateHeight: reviewIntermediateSectionHeights[key] ?? fallback.intermediateHeight,
                compactHeight: reviewCompactSectionHeights[key] ?? fallback.compactHeight
            ))
        })
        return ReviewCardLayoutSolver.solve(.init(
            face: face,
            fields: fields,
            measurements: measurements,
            viewportHeight: availableHeight,
            minimumHeight: face == .front ? 0 : answerCardHeight,
            columns: columns
        ))
    }

    private func reviewMeasurementKey(
        for currentCard: ReviewCardContent,
        face: ReviewCardFace,
        section: ReviewCardLayoutSolver.Section
    ) -> ReviewCardMeasurementKey {
        ReviewCardMeasurementKey(
            cardKey: "\(currentCard.card.dateAdded.timeIntervalSinceReferenceDate)-\(currentCard.card.word)",
            face: face,
            section: section,
            widthBucket: Int(containerWidth.rounded()),
            dynamicType: String(describing: dynamicTypeSize)
        )
    }

    private func recordReviewSectionHeight(
        _ height: CGFloat,
        currentCard: ReviewCardContent,
        face: ReviewCardFace,
        section: ReviewCardLayoutSolver.Section,
        level: ReviewCardLayoutSolver.MeasurementLevel
    ) {
        guard height > 0 else { return }
        let key = reviewMeasurementKey(for: currentCard, face: face, section: section)
        switch level {
        case .natural:
            guard abs((reviewNaturalSectionHeights[key] ?? 0) - height) > 0.5 else { return }
            reviewNaturalSectionHeights[key] = height
        case .intermediate:
            guard abs((reviewIntermediateSectionHeights[key] ?? 0) - height) > 0.5 else { return }
            reviewIntermediateSectionHeights[key] = height
        case .compact:
            guard abs((reviewCompactSectionHeights[key] ?? 0) - height) > 0.5 else { return }
            reviewCompactSectionHeights[key] = height
        }
    }

    @ViewBuilder
    private func reviewMeasurementProbes(
        _ field: ReviewCardField,
        currentCard: ReviewCardContent,
        face: ReviewCardFace
    ) -> some View {
        let key = reviewMeasurementKey(for: currentCard, face: face, section: .field(field))
        let levels = ReviewCardLayoutSolver.missingMeasurementLevels(
            hasNatural: reviewNaturalSectionHeights[key] != nil,
            hasIntermediate: reviewIntermediateSectionHeights[key] != nil,
            hasCompact: reviewCompactSectionHeights[key] != nil
        )
        ZStack(alignment: .topLeading) {
            ForEach(levels, id: \.self) { level in
                reviewOptionalField(
                    field,
                    currentCard: currentCard,
                    face: face,
                    policy: .measurementProbe(for: field, level: level)
                )
                .fixedSize(horizontal: false, vertical: true)
                .hidden()
                .allowsHitTesting(false)
                .accessibilityHidden(true)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                    recordReviewSectionHeight(
                        height,
                        currentCard: currentCard,
                        face: face,
                        section: .field(field),
                        level: level
                    )
                }
            }
        }
    }

    @ViewBuilder
    private func reviewOptionalField(
        _ field: ReviewCardField,
        currentCard: ReviewCardContent,
        face: ReviewCardFace,
        policy: ReviewCardLayoutSolver.Policy
    ) -> some View {
        let card = currentCard.card
        switch field {
        case .partOfSpeech:
            if let partOfSpeech = card.partOfSpeech {
                Text(partOfSpeech)
                    .font(appSkin.typography.body)
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }
        case .difficultyTier:
            // Trailing-aligned, as the tier pill has always hugged the card's edge.
            if let tier = card.difficultyTier {
                VocabTierLabel(tier: tier)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
        case .example:
            if let example = card.examples.first {
                CardRichTextRenderer.text(
                    example,
                    style: CardRichTextStyle(
                        font: appSkin.typography.example,
                        textColor: appSkin.palette.secondaryText,
                        highlightColor: appSkin.palette.highlightMark,
                        italic: true,
                        underlineHighlights: appSkin.highlight.showUnderline,
                        useBackgroundMark: appSkin.highlight.showBackground,
                        highlightWeight: appSkin.highlight.fontWeight,
                        backgroundOpacity: appSkin.highlight.backgroundOpacity,
                        underlineOpacity: appSkin.highlight.underlineOpacity
                    ),
                    mode: ReviewCardExampleRendering.mode(face: face, cardMode: card.reviewMode),
                    truncateAroundMarkedWordRadius: policy.exampleRadius
                        ?? ReviewCardLayoutSolver.naturalExampleRadius(
                            for: face,
                            staticRadius: appSkin.metrics.exampleTruncateRadius
                        ),
                    targetWord: card.word
                )
                .lineSpacing(appSkin.metrics.paragraphLineSpacing)
            }
        case .explanation:
            // One globally-limited rich text rather than per-paragraph clamps: the
            // solver budgets one section, so one clamp must own the whole block.
            // Natural is the shipped 3-line / 5pt compact meaning presentation.
            CardRichTextRenderer.text(
                ReviewCardExplanationContent.rawMarkdown(
                    from: currentCard.backDocument.meaningParagraphs()
                ),
                style: CardRichTextStyle(
                    font: appSkin.typography.body,
                    textColor: appSkin.palette.secondaryText,
                    highlightColor: appSkin.palette.highlightMark,
                    italic: false,
                    underlineHighlights: false,
                    useBackgroundMark: false,
                    highlightWeight: appSkin.highlight.fontWeight,
                    backgroundOpacity: appSkin.highlight.backgroundOpacity,
                    underlineOpacity: appSkin.highlight.underlineOpacity
                )
            )
            .lineSpacing(TodayReviewMetrics.foldMeaningLineSpacing)
            .lineLimit(ReviewCardLayoutSolver.explanationLineLimit(policyLineLimit: policy.lineLimit))
            .fixedSize(horizontal: false, vertical: true)
        case .collocations:
            let visible: [String] = if let limit = ReviewCardLayoutSolver.visibleCollocationLimit(
                lineLimit: policy.lineLimit
            ) {
                Array(card.collocations.prefix(limit))
            } else {
                card.collocations
            }
            VStack(alignment: .leading, spacing: appSkin.spacing.inlineGap) {
                CardDocumentCollocationsBlock(
                    items: visible,
                    compact: true,
                    maxRows: ReviewCardLayoutSolver.collocationRowLimit(lineLimit: policy.lineLimit),
                    explanations: collocationExplanations,
                    onExplain: actions.explainCollocation,
                    onView: actions.viewCollocationExplanation,
                    onDelete: actions.deleteCollocationExplanation
                )
                if policy.summarizesOverflow, card.collocations.count > visible.count {
                    Text("+\(card.collocations.count - visible.count)")
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                }
            }
        case .graphLinks:
            // No links yet → the add-link prompt, never nothing: this is the only
            // place the review card can start a link from.
            if currentCard.linkGroups.isEmpty {
                addLinkPrompt
            } else {
                reviewLinkStrip(currentCard.linkGroups, presentation: policy.graphLinkPresentation ?? .twoPerGroup)
            }
        }
    }

    // MARK: Fonts

    func reviewFrontWordFont(for text: String) -> Font {
        let count = text.count
        if count > 20 { return AppFonts.systemMono(size: TodayReviewMetrics.counterFontSizeCompact, weight: .semibold) }
        if count > 12 { return AppFonts.systemMono(size: TodayReviewMetrics.counterFontSizeMedium, weight: .semibold) }
        return AppFonts.systemMono(size: TodayReviewMetrics.counterFontSizeXLarge, weight: .semibold)
    }

    func reviewAnswerWordFont(for text: String) -> Font {
        let count = text.count
        if count > 20 { return appSkin.typography.translationTitle }
        if count > 12 { return AppFonts.systemMono(size: TodayReviewMetrics.counterFontSizeLarge, weight: .semibold) }
        return appSkin.typography.reviewWord
    }
}

// MARK: - Face Chrome

extension View {
    /// The only place a review card face pads its content. `ReviewCardChrome` hands
    /// the identical numbers to the solver as `chromeHeight`, so the budget and the
    /// drawn inset move together or not at all.
    func reviewCardFaceChrome(_ face: ReviewCardFace) -> some View {
        padding(ReviewCardChrome.padding)
            .padding(.top, ReviewCardChrome.extraTopInset(for: face))
    }
}
