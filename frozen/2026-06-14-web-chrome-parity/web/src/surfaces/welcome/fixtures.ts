import type { ScenarioId } from '../../harness/scenarios'
import {
  TextViewfinderIcon,
  ConnectedTrianglePathIcon,
  CheckCircleFillIcon,
} from './icons'

/**
 * Welcome onboarding fixtures — 鏡像 ios WelcomeView.swift 的 `pages` 三步陣列
 *（中文文案逐字取自 WelcomeView.swift；iOS 端改文案時此處須同步）。
 * 每個 catalog scenario 對應 TabView 的初始頁（initialPage）。
 * Step 3 / Review 與 Step 3 / Dark 在 catalog harness 皆渲染 light 第 3 頁
 *（preferredColorScheme .dark 在離線快照不生效），故兩者 fixture 同為 page index 2。
 */

export type WelcomePage = {
  icon: typeof TextViewfinderIcon
  step: number
  title: string
  subtitle: string
}

export const WELCOME_PAGES: WelcomePage[] = [
  {
    icon: TextViewfinderIcon,
    step: 1,
    title: '捕捉詞彙',
    subtitle: '閱讀中長按生詞，AI 依語境即時翻譯並收進筆記',
  },
  {
    icon: ConnectedTrianglePathIcon,
    step: 2,
    title: '自動連結',
    subtitle: '同義、混淆、衍生自動成圖，把孤點串成知識網絡',
  },
  {
    icon: CheckCircleFillIcon,
    step: 3,
    title: '每日複習',
    subtitle: '間隔重複演算法挑選到期卡片，每日 5 分鐘穩定累積',
  },
]

export const WELCOME_FIXTURES: Record<ScenarioId<'welcome'>, { activePage: number }> = {
  'step-1-capture': { activePage: 0 },
  'step-2-link': { activePage: 1 },
  'step-3-review': { activePage: 2 },
  'step-3-dark': { activePage: 2 },
}
