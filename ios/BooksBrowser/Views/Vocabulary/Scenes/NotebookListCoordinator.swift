//
//  NotebookListCoordinator.swift
//  BooksBrowser
//
//  單字本列表的 DB + API 操作封裝

import Foundation
import SwiftData

@MainActor protocol NotebookListCoordinating: AnyObject, Observable {
    func ensureDefaultNotebook(
        authManager: any AuthManaging,
        currentNotebooks: [Notebook],
        modelContext: ModelContext,
        kgService: any KGServing
    ) async
    func createNotebook(
        name: String,
        color: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async
    func updateNotebook(
        _ notebook: Notebook,
        name: String,
        color: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async
    func deleteNotebook(
        _ notebook: Notebook,
        isActive: Bool,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator,
        setActiveNotebook: (String) -> Void
    ) async
}

@Observable @MainActor
final class NotebookListCoordinator: NotebookListCoordinating {

    func ensureDefaultNotebook(
        authManager: any AuthManaging,
        currentNotebooks: [Notebook],
        modelContext: ModelContext,
        kgService: any KGServing
    ) async {
        guard authManager.isLoggedIn else { return }
        guard currentNotebooks.isEmpty else { return }

        do {
            let remoteNotebooks = try await kgService.fetchNotebooks()
            for remote in remoteNotebooks where !remote.isDeleted {
                let nb = Notebook(
                    remoteId: remote.id,
                    name: remote.name,
                    color: remote.color,
                    isDefault: remote.isDefault
                )
                nb.sortOrder = remote.sortOrder
                nb.syncStatus = 1
                modelContext.insert(nb)
            }
            modelContext.safeSave()
        } catch {
            if currentNotebooks.isEmpty {
                let nb = Notebook(remoteId: "default", name: "我的單字本", isDefault: true)
                nb.syncStatus = 1
                modelContext.insert(nb)
                modelContext.safeSave()
            }
        }
    }

    func createNotebook(
        name: String,
        color: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async {
        do {
            let remote = try await kgService.createNotebook(name: name, color: color)
            let nb = Notebook(remoteId: remote.id, name: remote.name, color: remote.color)
            nb.syncStatus = 1
            modelContext.insert(nb)
            if modelContext.safeSaveWithToast(toastCoordinator) {
                toastCoordinator.success("已建立")
            }
        } catch {
            toastCoordinator.error("建立失敗")
            AppLog.kg.error("createNotebook failed: \(error.localizedDescription)")
        }
    }

    func updateNotebook(
        _ notebook: Notebook,
        name: String,
        color: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async {
        do {
            let remote = try await kgService.updateNotebook(id: notebook.remoteId, name: name, color: color)
            notebook.name = remote.name
            notebook.color = remote.color
            notebook.updatedAt = Date()
            if modelContext.safeSaveWithToast(toastCoordinator) {
                toastCoordinator.success("已更新")
            }
        } catch {
            toastCoordinator.error("更新失敗")
            AppLog.kg.error("updateNotebook failed: \(error.localizedDescription)")
        }
    }

    func deleteNotebook(
        _ notebook: Notebook,
        isActive: Bool,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator,
        setActiveNotebook: (String) -> Void
    ) async {
        do {
            try await kgService.deleteNotebook(id: notebook.remoteId)
            if isActive {
                setActiveNotebook("default")
            }
            notebook.isDeleted = true
            notebook.updatedAt = Date()
            if modelContext.safeSaveWithToast(toastCoordinator) {
                toastCoordinator.success("已刪除")
            }
        } catch {
            toastCoordinator.error("刪除失敗")
            AppLog.kg.error("deleteNotebook failed: \(error.localizedDescription)")
        }
    }
}
