#if os(iOS)
import Foundation
import Testing

/// Sheet / fullScreenCover 是**另一個 presentation host**。SwiftUI 只在「呈現的
/// 那一刻」把當下的 interface style 播種給它自己的 hosting controller；之後 root
/// （`BooksAndVocabApp` 那一句 `.preferredColorScheme`）再改，**已經在畫面上的
/// presentation 不會被重新播種**。
///
/// 後果是同一個 presentation 裡並存兩套配色：吃 SwiftUI 環境值畫的（`.tint`、
/// `appSkin` 色票、自繪卡片）當場換新，吃系統色畫的（原生 `Form` / `List` 的
/// 背景與標籤、nav bar）停在呈現當下那一套。APP-20260809-f1b8cb 就是這個：在
/// 閱讀設定頁選深色的當下，近白的 `tintDark` 畫在還是淺色的 `Form` 上直接消失。
///
/// 值得寫下來的是**它不是單向的**。判準是「離開這個 presentation 被呈現時的那個
/// 外觀」，不是往哪個方向切 —— 從深色開啟再切淺色一樣壞（深炭灰的 `tintLight`
/// 疊在還是深色的 `Form` 上）。也不是「退出子頁再進去」能救的：同一個 sheet 內
/// pop 再 push 依然壞，要整個 sheet 被關掉重開才會對。
///
/// 這條 fence 釘住修法的形狀：每一個**自己開 presentation** 的地方都要重新宣告
/// 一次 app 選定的外觀（`.appAppearanceScheme()`）—— 與 `settingsSheet` 早就在做的
/// 「`@EnvironmentObject` 不跨 sheet 邊界，所以在邊界 re-inject」是同一件事的兩半。
/// 走 `toastSheet` / `platformFullScreenCover` 這兩個 seam 的呼叫端不必自己寫，
/// seam 本身已經寫了；這裡只數**直接**呼叫 SwiftUI 原生 presentation API 的地方。
///
/// **它擋得住什麼、擋不住什麼**（別把它當比它更強的東西）：
///   擋得住  「新開了一個 presentation 卻沒重新播種」這個根因復發。
///   擋不住  像素本身 —— 顏色對不對只能肉眼驗（見票的 acceptance）。
///   擋不住  同檔內的錯配：比較是**整檔加總**，所以一個檔有兩個 sheet、其中一個
///           掛了兩次而另一個一次都沒掛，仍然會綠。要再進一步就得真的剖析語法樹，
///           那個成本不值得 —— 這條 fence 的目標是「別忘記」，不是「別寫錯」。
struct SheetAppearanceBoundaryTests {

    /// 直接呼叫的原生 presentation API。
    ///
    /// **大小寫敏感**是刻意的，而且是走 seam 的呼叫端不被重複計算的唯一原因：
    /// `toastSheet(` / `platformFullScreenCover(` / `settingsSheet(` / `loginSheet(`
    /// 這些包裝的 S / F 一律是大寫（camelCase 使然），只有 SwiftUI 原生 API 本身
    /// 是小寫開頭。
    /// `popover(` 今天在 production 是零個，收進來是為了讓這條線守的是**那一類**
    /// （另開 presentation host 的 API）而不是「我當時想到的那兩個」。popover 對
    /// 同一個根因完全一樣脆弱，卻對只認 sheet 的 fence 完全隱形。
    private static let presentationTokens = ["sheet(", "fullScreenCover(", "popover("]

    /// 左括號後**跳過空白換行**必須接上的參數標籤。SwiftUI 的 `sheet` /
    /// `fullScreenCover` 只有這兩種 overload。
    ///
    /// 這一關同時解掉兩個相反的錯誤，缺一不可：
    ///   · 少了「跳過空白換行」→ `.sheet(\n    isPresented: $x\n)` 一個都數不到，
    ///     而數不到的檔案會被 `guard sites > 0` 直接跳過，fence 安靜放行。
    ///   · 少了「必須接標籤」→ 連散文都會中。實例：
    ///     `AppCommandCoordinator.swift` 的註解寫著「app-level 設定 sheet(Catalyst-only)」，
    ///     曾被誤判成一個沒重新播種的 presentation。
    private static let presentationArgumentLabels = ["isPresented:", "item:"]

    /// 重新播種外觀的宣告。帶前導點，才不會數到 `func appAppearanceScheme()` 宣告
    /// 本身 —— 也因此**註解裡不要寫帶點的 `.appAppearanceScheme()`**，那會讓一個
    /// 其實沒掛上去的檔案數出綠燈。本檔與新增的兩處說明註解都刻意寫成不帶點的
    /// `appAppearanceScheme()`。
    private static let reseedToken = ".appAppearanceScheme()"

    private static var productionSources: [URL] {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab", isDirectory: true)
        guard let walker = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil) else {
            return []
        }
        return walker
            .compactMap { $0 as? URL }
            .filter { $0.pathExtension == "swift" }
            // Debug/ 是 catalog harness：那些 scenario 本來就在刻意指定外觀來拍
            // light / dark 對照圖，不受此契約管轄。
            .filter { !$0.path.contains("/BooksAndVocab/Debug/") }
            .sorted { $0.path < $1.path }
    }

    private static func occurrences(of token: String, in text: String) -> Int {
        guard !token.isEmpty else { return 0 }
        var count = 0
        var searchRange = text.startIndex..<text.endIndex
        while let found = text.range(of: token, range: searchRange) {
            count += 1
            searchRange = found.upperBound..<text.endIndex
        }
        return count
    }

    /// 一個檔案裡直接開的 presentation 數。
    ///
    /// 三道關，各擋一種錯：
    ///   1. 前一個字元不是識別字字元 —— 擋 `_sheet(` / `mysheet(` 這種自訂名字
    ///      （camelCase 包裝已經被大小寫擋掉了，這道擋的是剩下的）。
    ///   2. 左括號後跳過空白換行 —— 讓多行寫法逃不掉。
    ///   3. 跳完必須接 `isPresented:` 或 `item:` —— 擋散文（見
    ///      `presentationArgumentLabels`）。
    private static func presentationSites(in text: String) -> Int {
        var count = 0
        for token in presentationTokens {
            var searchRange = text.startIndex..<text.endIndex
            while let found = text.range(of: token, range: searchRange) {
                searchRange = found.upperBound..<text.endIndex

                if found.lowerBound > text.startIndex {
                    let previous = text[text.index(before: found.lowerBound)]
                    if previous.isLetter || previous.isNumber || previous == "_" { continue }
                }

                var cursor = found.upperBound
                while cursor < text.endIndex, text[cursor].isWhitespace {
                    cursor = text.index(after: cursor)
                }
                let rest = text[cursor...]
                if presentationArgumentLabels.contains(where: { rest.hasPrefix($0) }) {
                    count += 1
                }
            }
        }
        return count
    }

    /// 重新播種的宣告數。每行**截到第一個 `//`** 再數 —— 否則一句
    /// `// 記得加 .appAppearanceScheme()`（或行尾的同一句）就能讓一個其實沒掛
    /// 上去的檔案數出綠燈。
    ///
    /// 它不是 lexer：字串字面裡的 `//`（例如網址）也會被當成註解起點。那個誤差
    /// 只會讓 reseed **少算**，也就是讓 fence 更嚴，不會放行 —— 往安全的方向壞。
    /// 區塊註解沒有處理，今天 production 也沒有這種寫法。
    private static func reseedDeclarations(in text: String) -> Int {
        text.split(separator: "\n", omittingEmptySubsequences: false)
            .map { line -> String in
                guard let comment = line.range(of: "//") else { return String(line) }
                return String(line[line.startIndex..<comment.lowerBound])
            }
            .reduce(0) { $0 + occurrences(of: reseedToken, in: $1) }
    }

    /// 掃描本身要先被證明會抓到東西 —— 否則「全部通過」可能只是它什麼都沒讀到。
    @Test func theScanActuallyReachesTheKnownPresentationSites() throws {
        let sources = Self.productionSources
        #expect(sources.count > 100, "掃描沒讀到 production 原始碼，後面那條斷言就是空的")

        let sitesByFile = try sources.reduce(into: [String: Int]()) { result, url in
            let text = try String(contentsOf: url, encoding: .utf8)
            let count = Self.presentationSites(in: text)
            if count > 0 { result[url.lastPathComponent] = count }
        }

        // 兩個 seam 一定要在名單裡：它們是全 app 絕大多數 presentation 的實際開口。
        #expect(sitesByFile["View+ToastSheet.swift"] == 2)
        #expect(sitesByFile["PlatformCompatibility.swift"] == 2)
        // 缺陷現場：閱讀設定頁的閱讀器入口是自己開的 sheet，不走 seam。
        #expect(sitesByFile["ReaderView.swift"] == 1)

        // 負控：這個檔只有一句**註解**提到「設定 sheet(Catalyst-only)」，
        // 沒有任何 presentation。放寬 token 去接多行寫法時它曾被誤判成缺口，
        // 害 fence 對一個完全正常的檔案報紅。誤報和漏報一樣會讓人不再信這條線。
        //
        // 但 `== nil` 自己**不可證偽** —— 它把「掃過且為零」和「根本沒掃到」
        // 混為一談。所以先斷言那個檔真的在語料裡：少了這行，掃描整個壞掉回傳空、
        // 或這個檔被改名 / 刪除 / 移進 Debug/，負控都會安靜地繼續「通過」。
        #expect(
            Self.productionSources.contains { $0.lastPathComponent == "AppCommandCoordinator.swift" },
            "負控的樣本不在語料裡了 —— 下一行的 == nil 已經不再證明任何事"
        )
        #expect(sitesByFile["AppCommandCoordinator.swift"] == nil)
    }

    /// 三道關各自的**正控**。沒有這些，只要掃描退化成「永遠回 0」，上面每一條
    /// 斷言都會繼續通過 —— 而那正是這條 fence 失效時最可能的樣子。
    ///
    /// 用合成字串而不是真檔案：正控需要「必定該被拒」與「必定該被接受」兩種樣本，
    /// 而為了測試往 production 塞一個假的 `_sheet(` 是本末倒置。
    @Test func theThreeGatesAcceptAndRejectTheRightShapes() {
        // 接受：一般寫法、多行寫法、item: overload、popover。
        #expect(Self.presentationSites(in: "        .sheet(isPresented: $x) {") == 1)
        #expect(Self.presentationSites(in: ".sheet(\n            isPresented: $x\n        ) {") == 1)
        #expect(Self.presentationSites(in: ".fullScreenCover(item: $x) {") == 1)
        #expect(Self.presentationSites(in: ".popover(isPresented: $x) {") == 1)
        // 隱含 self 的呼叫（seam 內部就是這樣寫的）也要接受。
        #expect(Self.presentationSites(in: "        sheet(isPresented: isPresented) {") == 1)

        // gate 1 拒絕：前面接著識別字字元。
        #expect(Self.presentationSites(in: "_sheet(isPresented: $x)") == 0)
        #expect(Self.presentationSites(in: "mysheet(item: $x)") == 0)
        // 大小寫拒絕：走 seam 的包裝不重複計算。
        #expect(Self.presentationSites(in: ".toastSheet(isPresented: $x) {") == 0)
        #expect(Self.presentationSites(in: ".platformFullScreenCover(item: $x) {") == 0)
        // gate 3 拒絕：散文。這是 AppCommandCoordinator.swift:19 的真實形狀。
        #expect(Self.presentationSites(in: "/// app-level 設定 sheet(Catalyst-only)。") == 0)

        // reseed 計數：整行註解與行尾註解都不算，程式碼才算。
        #expect(Self.reseedDeclarations(in: "        // 記得加 .appAppearanceScheme()") == 0)
        #expect(Self.reseedDeclarations(in: "        foo() // .appAppearanceScheme()") == 0)
        #expect(Self.reseedDeclarations(in: "        content.appAppearanceScheme()") == 1)
    }

    /// 每個自己開 presentation 的檔案，重新播種的次數不得少於它開的 presentation 數。
    @Test func everyPresentationBoundaryReseedsTheChosenAppearance() throws {
        var offenders: [String] = []

        for url in Self.productionSources {
            let text = try String(contentsOf: url, encoding: .utf8)
            let sites = Self.presentationSites(in: text)
            guard sites > 0 else { continue }
            let reseeds = Self.reseedDeclarations(in: text)
            if reseeds < sites {
                offenders.append("\(url.lastPathComponent)：\(sites) 個 presentation，只有 \(reseeds) 個 \(Self.reseedToken)")
            }
        }

        #expect(
            offenders.isEmpty,
            """
            下列 presentation 邊界沒有重新宣告 app 選定的外觀，切主題時會留下
            半新半舊的配色（APP-20260809-f1b8cb）：
            \(offenders.joined(separator: "\n"))
            """
        )
    }
}
#endif
