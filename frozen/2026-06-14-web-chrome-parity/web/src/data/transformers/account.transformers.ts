// Pure transformers: account/notebook seed → API-response shapes.
// No I/O, no mutation — given the same seed they return the same value.

import type {
  DeleteAccountResponse,
  NotebookResponse,
  UserProfileResponse,
} from '../../api/types'
import type { AccountSeed, NotebookSeed } from '../seeds/account.seed'

export function toNotebookResponse(n: NotebookSeed, nowIso: string): NotebookResponse {
  return {
    id: n.id,
    name: n.name,
    color: n.color,
    coverPattern: n.coverPattern,
    sortOrder: n.sortOrder,
    isDefault: n.isDefault,
    isDeleted: false,
    cardCount: n.cardCount,
    updatedAt: nowIso,
  }
}

export function toNotebookResponses(seeds: NotebookSeed[], nowIso: string): NotebookResponse[] {
  return seeds.map((n) => toNotebookResponse(n, nowIso))
}

export function toUserProfileResponse(a: AccountSeed): UserProfileResponse {
  return {
    user_id: a.userId,
    email: a.email,
    display_name: a.displayName,
  }
}

export function toDeleteAccountResponse(a: AccountSeed): DeleteAccountResponse {
  return {
    deleted_user_id: a.userId,
    linked_ids: a.linkedIds,
    deleted_dirs: a.deletedDirs,
  }
}
