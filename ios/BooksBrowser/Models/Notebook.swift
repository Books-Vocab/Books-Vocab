//
//  Notebook.swift
//  BooksBrowser
//
//  單字本 — 用於分組管理單字

import Foundation
import SwiftData

@Model
final class Notebook {
    var id: UUID
    var remoteId: String
    var name: String
    var color: String?
    var sortOrder: Int = 0
    var isDefault: Bool = false
    var createdAt: Date
    var updatedAt: Date
    var isDeleted: Bool = false
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
