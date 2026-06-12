/**
 * Sync 場景 fixtures — 逐字取自
 * ios/BooksAndVocab/Debug/Scenarios/SyncScenarios.swift（合成 SyncPresenterState）。
 * iOS 改 scenario 文案/狀態時此處須同步。
 */

export type SyncPhase = 'ready' | 'running' | 'completed' | 'failed'
export type SyncFailureKind = 'partial' | 'full' | null
export type StepStatus = 'waiting' | 'running' | 'done' | 'error' | 'retry' | 'skipped'

export type PendingAction = 'add' | 'delete'

export type PendingRow = {
  word: string
  pos: string
  translation: string
  action: PendingAction
}

export type PipelineStep = {
  id: string
  label: string
  status: StepStatus
  current: number
  total: number
  detail: string
}

export type SyncState = {
  phase: SyncPhase
  failureKind: SyncFailureKind
  pendingCount: number
  addCount: number
  deleteCount: number
  steps: PipelineStep[]
  summaryText: string
  pendingRows: PendingRow[]
}

const step = (
  id: string,
  label: string,
  status: StepStatus,
  current = 0,
  total = 0,
  detail = '',
): PipelineStep => ({ id, label, status, current, total, detail })

export const SYNC_FIXTURES: Record<string, SyncState> = {
  ready: {
    phase: 'ready',
    failureKind: null,
    pendingCount: 3,
    addCount: 2,
    deleteCount: 1,
    steps: [],
    summaryText: '',
    pendingRows: [
      { word: 'ineffable', pos: 'adj.', translation: '難以言喻的', action: 'add' },
      { word: 'ephemeral', pos: 'adj.', translation: '短暫的', action: 'add' },
      { word: 'obsolete', pos: 'adj.', translation: '過時的', action: 'delete' },
    ],
  },
  running: {
    phase: 'running',
    failureKind: null,
    pendingCount: 3,
    addCount: 2,
    deleteCount: 1,
    steps: [
      step('upload_delete', '刪除 Books & Vocab 單字', 'done', 1, 1, '已刪除 1 個單字'),
      step('upload_add', '上傳新單字', 'running', 1, 2),
      step('trigger', '觸發背景 AI 處理', 'waiting'),
      step('push_review', '上傳複習進度', 'waiting'),
      step('pull', '下載單字至本地', 'waiting'),
    ],
    summaryText: '',
    pendingRows: [],
  },
  completed: {
    phase: 'completed',
    failureKind: null,
    pendingCount: 0,
    addCount: 2,
    deleteCount: 1,
    steps: [
      step('upload_delete', '刪除 Books & Vocab 單字', 'done', 1, 1, '已刪除 1 個單字'),
      step('upload_add', '上傳新單字', 'done', 2, 2, '2 新增, 0 已存在'),
      step('trigger', '觸發背景 AI 處理', 'done', 0, 0, '已交由伺服器背景處理'),
      step('push_review', '上傳複習進度', 'done', 0, 0, '已同步 5 筆複習紀錄'),
      step('pull', '下載單字至本地', 'done', 1, 1, '本地單字已建立完成'),
    ],
    summaryText: '',
    pendingRows: [],
  },
  partial: {
    phase: 'failed',
    failureKind: 'partial',
    pendingCount: 1,
    addCount: 2,
    deleteCount: 1,
    steps: [
      step('upload_delete', '刪除 Books & Vocab 單字', 'done', 1, 1, '已刪除 1 個單字'),
      step('upload_add', '上傳新單字', 'error', 1, 2, '部分上傳失敗（1 筆）'),
      step('trigger', '觸發背景 AI 處理', 'done', 0, 0, '已交由伺服器背景處理'),
      step('push_review', '上傳複習進度', 'done', 0, 0, '已同步 5 筆複習紀錄'),
      step('pull', '下載單字至本地', 'done', 1, 1, '本地單字已建立完成'),
    ],
    summaryText: '部分項目未成功同步，可直接再次重試。',
    pendingRows: [],
  },
  full: {
    phase: 'failed',
    failureKind: 'full',
    pendingCount: 3,
    addCount: 2,
    deleteCount: 1,
    steps: [
      step('upload_delete', '刪除 Books & Vocab 單字', 'running', 0, 1),
      step('upload_add', '上傳新單字', 'waiting'),
      step('trigger', '觸發背景 AI 處理', 'waiting'),
      step('push_review', '上傳複習進度', 'waiting'),
      step('pull', '下載單字至本地', 'waiting'),
    ],
    summaryText: '網路連線中斷，請稍後再試。',
    pendingRows: [],
  },
}
