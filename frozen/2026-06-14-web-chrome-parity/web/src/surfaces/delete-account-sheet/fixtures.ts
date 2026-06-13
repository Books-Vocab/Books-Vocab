import type { ScenarioId } from '../../harness/scenarios'

/**
 * SettingsDeleteAccountSheet 的合成資料 — 逐字對齊 iOS
 * `SettingsDeleteAccountCopy`（中文含標點照抄）。
 *
 * 兩個 scenario（idle / deleting）共用同一份文案；唯一差別是 delete 按鈕的內容：
 *   idle      → trash.fill + 「永久刪除帳號」（init countdownRemaining=5、未就緒 → 顯永久刪除字）
 *   deleting  → ProgressView(small) + 「刪除中…」
 * 兩態的可見內容（hero / consequences / acknowledgements / confirm）完全相同，
 * 差異在 action stack（多落於折疊線下）。
 */

export interface ConsequenceRow {
  icon:
    | 'person.crop.circle'
    | 'books.vertical'
    | 'point.3.connected.trianglepath.dotted'
    | 'book.closed'
    | 'checkmark.seal'
  text: string
}

export const DELETE_ACCOUNT_COPY = {
  navigationTitle: '確認刪除帳號',
  heroTitle: '此操作不可復原',
  heroDescription:
    '刪除後將立即移除你的帳號、雲端生詞、閱讀進度、訂閱記錄。請仔細確認下列項目後才能繼續。',
  consequencesTitle: '將被永久刪除的資料',
  acknowledgementsTitle: '請確認你已知悉',
  confirmationTitle: '輸入確認字串',
  // confirmationPrompt(phrase: "DELETE") = "為避免誤觸，請輸入 DELETE 後繼續："
  confirmationPrompt: '為避免誤觸，請輸入 DELETE 後繼續：',
  confirmationPhrase: 'DELETE',
  deleteTitle: '永久刪除帳號',
  deletingTitle: '刪除中…',
  cancelTitle: '取消',
} as const

export const CONSEQUENCE_ROWS: ConsequenceRow[] = [
  { icon: 'person.crop.circle', text: '帳號資訊與登入記錄' },
  { icon: 'books.vertical', text: '雲端生詞與筆記本' },
  { icon: 'point.3.connected.trianglepath.dotted', text: '知識圖譜與關聯' },
  { icon: 'book.closed', text: '閱讀進度與書架' },
  { icon: 'checkmark.seal', text: '訂閱記錄（App Store 訂閱請另行至設定取消）' },
]

export const ACKNOWLEDGEMENT_ROWS: string[] = [
  '我了解所有資料將被永久刪除',
  '我了解此操作無法復原',
  '我了解資料一旦刪除即無法經由客服救回',
]

interface DeleteAccountFixture {
  isDeleting: boolean
}

export const DELETE_ACCOUNT_FIXTURES: Record<
  ScenarioId<'delete-account-sheet'>,
  DeleteAccountFixture
> = {
  idle: { isDeleting: false },
  deleting: { isDeleting: true },
}
