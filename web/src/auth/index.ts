export { AuthProvider, useAuth, type AuthContextValue, type AuthSession } from './AuthContext'
export { LoginGate } from './LoginGate'
// 殼層提供給下游 surface 的 auth 感知資料分流契約（guest 空態 vs 真錯誤）。
export { classifyDataState, resolveShellAccess, type DataState, type ShellAccess } from './devSession'
