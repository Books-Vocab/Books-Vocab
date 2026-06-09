//
//  JWTExpiry.swift
//  Books & Vocab
//
//  輕量 JWT exp 欄位解碼 — 不驗簽，僅讀取過期時間做預檢
//

import Foundation

enum JWTExpiry {

    /// 從 JWT token 字串解出 exp（Unix timestamp），解碼失敗回傳 nil
    static func expirationDate(from token: String) -> Date? {
        let segments = token.split(separator: ".")
        guard segments.count >= 2 else { return nil }

        var base64 = String(segments[1])
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")

        // Base64 需要 4 的倍數長度
        let remainder = base64.count % 4
        if remainder > 0 {
            base64.append(contentsOf: String(repeating: "=", count: 4 - remainder))
        }

        guard let data = Data(base64Encoded: base64),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let exp = json["exp"] as? TimeInterval
        else { return nil }

        return Date(timeIntervalSince1970: exp)
    }

    /// Token 是否已過期（含 margin 秒的安全邊界，預設 60 秒）
    static func isExpired(_ token: String, margin: TimeInterval = 60) -> Bool {
        guard let expDate = expirationDate(from: token) else {
            // 無法解析 → 不主動判斷過期，交給後端 401
            return false
        }
        return Date().addingTimeInterval(margin) >= expDate
    }
}
