import type { ReactNode } from 'react'
import { Drawer } from 'vaul'
import './motion.css'

/**
 * Sheet — the app's shared iOS-style bottom sheet primitive (vaul-backed).
 *
 * One simple controlled API for every sheet in the functional shell (notebook
 * add/edit, word detail, login, account, …): `<Sheet open onClose>…</Sheet>`.
 * vaul provides the native-feeling drag-to-dismiss physics (velocity-aware
 * swipe-to-close), focus trapping, scroll locking and Esc handling; we layer on
 * the iOS chrome: dimmed backdrop, rounded top corners, and a grabber pill.
 *
 * Drag-to-dismiss: vaul's default `dismissible` is on, so dragging the sheet (or
 * the grabber) downward past the threshold, clicking the backdrop, or pressing
 * Esc all fire `onOpenChange(false)` → we forward to `onClose`.
 *
 * Reduced motion: vaul's open/close translate animation respects the platform;
 * we additionally avoid any custom spring here, deferring to vaul + the system
 * `prefers-reduced-motion` handling so motion-sensitive users get a calm swap.
 *
 * PARITY ISOLATION: this primitive is only mounted on the shell path. It is NOT
 * rendered by PhoneFrame shell={false} / SurfaceView, so the parity capture DOM
 * and screenshots are untouched. (The parity-side sheet *surfaces* — e.g.
 * notebook-edit as a static fixture — keep rendering verbatim for capture.)
 */
export function Sheet({
  open,
  onClose,
  children,
  ariaLabel,
}: {
  /** Controlled visibility. */
  open: boolean
  /** Called when the user dismisses (drag / backdrop / Esc). */
  onClose: () => void
  /** Sheet content (the migrated call-site renders inside the scroll body). */
  children: ReactNode
  /** Accessible label for the dialog (vaul Title; visually hidden). */
  ariaLabel?: string
}) {
  return (
    <Drawer.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <Drawer.Portal>
        <Drawer.Overlay className="kg-sheet-overlay" />
        <Drawer.Content className="kg-sheet-content" aria-label={ariaLabel}>
          <Drawer.Handle className="kg-sheet-grabber" />
          {ariaLabel ? (
            <Drawer.Title
              style={{
                position: 'absolute',
                width: 1,
                height: 1,
                padding: 0,
                margin: -1,
                overflow: 'hidden',
                clip: 'rect(0 0 0 0)',
                whiteSpace: 'nowrap',
                border: 0,
              }}
            >
              {ariaLabel}
            </Drawer.Title>
          ) : null}
          <div className="kg-sheet-body">{children}</div>
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  )
}
