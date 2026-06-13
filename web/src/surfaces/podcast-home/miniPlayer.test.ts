import { describe, expect, it } from 'vitest'
import { initialFlow, openEpisode, openSeries } from '../podcast/flowNav'
import { reopenPlayer, shouldShowMiniPlayer, type NowPlaying } from './miniPlayer'

const NP: NowPlaying = {
  seriesId: 'pride-and-prejudice',
  epNum: 1,
  seriesTitle: 'Pride and Prejudice',
  episodeTitle: 'Chapter 1',
}

describe('shouldShowMiniPlayer', () => {
  it('hides when nothing is loaded', () => {
    expect(shouldShowMiniPlayer(null, true, { route: 'home' })).toBe(false)
  })

  it('hides when an episode is loaded but playback was never engaged', () => {
    expect(shouldShowMiniPlayer(NP, false, { route: 'home' })).toBe(false)
  })

  it('shows on the home screen once playback is engaged', () => {
    expect(shouldShowMiniPlayer(NP, true, { route: 'home' })).toBe(true)
  })

  it('shows on the episode-list screen once playback is engaged', () => {
    expect(
      shouldShowMiniPlayer(NP, true, { route: 'episode-list', seriesId: 'pride-and-prejudice' }),
    ).toBe(true)
  })

  it('hides on the full player for the SAME episode (no double transport)', () => {
    expect(
      shouldShowMiniPlayer(NP, true, { route: 'player', seriesId: 'pride-and-prejudice', epNum: 1 }),
    ).toBe(false)
  })

  it('shows on a player for a DIFFERENT episode than the one loaded', () => {
    expect(
      shouldShowMiniPlayer(NP, true, { route: 'player', seriesId: 'pride-and-prejudice', epNum: 2 }),
    ).toBe(true)
  })
})

describe('reopenPlayer', () => {
  it('pushes the loaded episode player onto the stack', () => {
    const stack = openSeries(initialFlow(), 'pride-and-prejudice')
    const next = reopenPlayer(stack, NP)
    expect(next).toHaveLength(stack.length + 1)
    expect(next[next.length - 1]).toEqual({
      route: 'player',
      seriesId: 'pride-and-prejudice',
      epNum: 1,
    })
  })

  it('is a no-op when the loaded player is already the tail', () => {
    const stack = openEpisode(initialFlow(), 'pride-and-prejudice', 1)
    expect(reopenPlayer(stack, NP)).toBe(stack)
  })
})
