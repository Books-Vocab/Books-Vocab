import { createContext, useContext } from 'react'
import type { Appearance } from './scenarios'

/**
 * Live appearance control — lets an interactive surface (Settings 外觀 picker)
 * flip the phone-frame `data-theme` after the user acts. Parity capture never
 * touches this: the frame seeds its theme state from `config.appearance`, so the
 * INITIAL render is byte-identical to the static surface. Only a user gesture
 * mutates it (in-memory, no persistence).
 */
export interface AppearanceControl {
  appearance: Appearance
  setAppearance: (next: Appearance) => void
}

const noop: AppearanceControl = {
  appearance: 'light',
  setAppearance: () => {},
}

export const AppearanceContext = createContext<AppearanceControl>(noop)

export function useAppearance(): AppearanceControl {
  return useContext(AppearanceContext)
}
