import { describe, expect, it } from 'vitest'
import {
  currentFlowScreen,
  flowDepth,
  initialFlow,
  openEpisode,
  openSeries,
  popFlow,
} from './flowNav'

describe('podcast flow nav', () => {
  it('starts at home, depth 1', () => {
    const s = initialFlow()
    expect(currentFlowScreen(s)).toEqual({ route: 'home' })
    expect(flowDepth(s)).toBe(1)
  })

  it('home → episode-list → player carries params', () => {
    let s = initialFlow()
    s = openSeries(s, 'atomic')
    expect(currentFlowScreen(s)).toEqual({ route: 'episode-list', seriesId: 'atomic' })
    s = openEpisode(s, 'atomic', 2)
    expect(currentFlowScreen(s)).toEqual({ route: 'player', seriesId: 'atomic', epNum: 2 })
    expect(flowDepth(s)).toBe(3)
  })

  it('pop unwinds one level and is a no-op at root', () => {
    let s = openEpisode(openSeries(initialFlow(), 'atomic'), 'atomic', 1)
    s = popFlow(s)
    expect(currentFlowScreen(s)).toEqual({ route: 'episode-list', seriesId: 'atomic' })
    s = popFlow(s)
    expect(currentFlowScreen(s)).toEqual({ route: 'home' })
    const atRoot = popFlow(s)
    expect(atRoot).toBe(s) // no-op preserves identity
  })

  it('continue-shelf can jump straight to a player from home', () => {
    const s = openEpisode(initialFlow(), 'flow', 1)
    // openEpisode pushes directly onto home (rail card → player), depth 2
    expect(flowDepth(s)).toBe(2)
    expect(currentFlowScreen(s)).toEqual({ route: 'player', seriesId: 'flow', epNum: 1 })
  })
})
