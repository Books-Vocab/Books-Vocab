//
//  Notebook.swift
//  Books & Vocab
//
//  單字本 — 用於分組管理單字

import Foundation
import SwiftData

@Model
final class Notebook {
    // 所有 stored property 都帶 default：對齊 Book / Podcast* 的 CloudKit 慣例。
    // 目前 Notebook 在 local-only store，但補 default 是 behavior-preserving（init 仍覆寫），
    // 並移除「未來若把 Notebook 移入 CloudKit store 會立刻違反『屬性需 optional 或有 default』
    // → ModelContainer init throw → store reset 刪本地資料」的地雷。
    var id: UUID = UUID()
    var remoteId: String = ""
    var name: String = ""
    var color: String?
    var coverPattern: String?
    var coverImagePath: String?
    var sortOrder: Int = 0
    var isDefault: Bool = false
    var createdAt: Date = Date()
    var updatedAt: Date = Date()
    @Attribute(originalName: "isDeleted")
    var isSoftDeleted: Bool = false
    var syncStatus: Int = 0  // 0=pending, 1=synced

    var isSynced: Bool { syncStatus == 1 }

    init(
        remoteId: String,
        name: String,
        color: String? = nil,
        isDefault: Bool = false
    ) {
        self.id = UUID()
        self.remoteId = remoteId
        self.name = name
        self.color = color
        self.isDefault = isDefault
        self.createdAt = Date()
        self.updatedAt = Date()
    }
}
