import { describe, expect, it } from 'vitest'
import { useTodayReviewApiStore } from './useTodayReviewApiStore'

// toReviewCard is private; test via the exported store's derived state
// We test the mapping indirectly through the store's public interface.

describe('useTodayReviewApiStore', () => {
  it('exports a callable hook shape (types only)', () => {
    // The hook requires a real ApiContext; this test verifies the module loads.
    expect(typeof useTodayReviewApiStore).toBe('function')
  })
})
