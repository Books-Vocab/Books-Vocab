//
//  BundleVersionConsistencyTests.swift
//  Books & Vocab Tests
//
//  版號單一事實的機器守衛。
//
//  MARKETING_VERSION / CURRENT_PROJECT_VERSION 只該有一份，住在 project-level
//  build settings，三個 target 全部繼承。測試 bundle 一旦帶上自己的一份，那份
//  值沒有任何讀者、也沒有任何流程會更新它，必然腐爛成與 app 矛盾的第二個版號
//  （2026-08 前它停在 1.2.0，app 已是 2.0.0），並誤導所有 grep MARKETING_VERSION
//  的人與工具（`ops/ios_release.sh` 的 guard_build_number 就因此被迫改用
//  `-target` 而非 `-scheme`）。
//
//  現實的復發路徑：在 Xcode 的 target General 分頁編輯 Version/Build，Xcode 會
//  把值寫回 target-level，覆寫掉繼承。這條測試就是攔那次寫回。
//

import Foundation
import Testing

/// `Bundle(for:)` 需要一個位於測試 bundle 內的 class 當定位錨。
private final class TestBundleMarker {}

struct BundleVersionConsistencyTests {

    private var testBundle: Bundle { Bundle(for: TestBundleMarker.self) }

    private func version(_ bundle: Bundle, _ key: String) -> String? {
        bundle.infoDictionary?[key] as? String
    }

    // MARK: - 正控：先證明兩邊都真的讀得到值

    /// 沒有這條，下面兩條的 nil == nil 會靜靜地通過。
    @Test func hostAndTestBundleBothCarryReadableVersions() {
        for key in ["CFBundleShortVersionString", "CFBundleVersion"] {
            let host = version(.main, key)
            let tests = version(testBundle, key)
            #expect(host?.isEmpty == false, "host app 讀不到 \(key)：\(String(describing: host))")
            #expect(tests?.isEmpty == false, "測試 bundle 讀不到 \(key)：\(String(describing: tests))")
        }
    }

    // MARK: - 不變式：測試 bundle 沒有自己的版號，只有繼承來的

    @Test func testBundleMarketingVersionIsInheritedFromHostApp() {
        let key = "CFBundleShortVersionString"
        #expect(
            version(testBundle, key) == version(.main, key),
            """
            測試 bundle 的 MARKETING_VERSION 與 app 分岔了 \
            (tests=\(String(describing: version(testBundle, key))), \
            app=\(String(describing: version(.main, key))))。
            版號屬於 project-level build settings；請刪掉 target-level 的覆寫，別把它改成一樣的字面值。
            """
        )
    }

    @Test func testBundleBuildNumberIsInheritedFromHostApp() {
        let key = "CFBundleVersion"
        #expect(
            version(testBundle, key) == version(.main, key),
            """
            測試 bundle 的 CURRENT_PROJECT_VERSION 與 app 分岔了 \
            (tests=\(String(describing: version(testBundle, key))), \
            app=\(String(describing: version(.main, key))))。
            版號屬於 project-level build settings；請刪掉 target-level 的覆寫，別把它改成一樣的字面值。
            """
        )
    }
}
