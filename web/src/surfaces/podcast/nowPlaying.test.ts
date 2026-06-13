import { describe, expect, it } from 'vitest'
import type { PodcastSeriesSummary } from '../../api/types'
import {
  applyPreviewCap,
  episodesOf,
  nextEpisode,
  nextPlayableEpisode,
  previewCapSec,
  sleepTick,
  SLEEP_OPTIONS,
  SUBTITLE_SIZES,
  cycleSubtitleSize,
  sleepLabel,
  FREE_PREVIEW_CAP_SEC,
} from './nowPlaying'

const SERIES: PodcastSeriesSummary = {
  id: 'pride-and-prejudice',
  title: 'Pride and Prejudice',
  episodes: [
    { ep_num: 1, title: 'Chapter 1', duration_sec: 1832 },
    { ep_num: 2, title: 'Chapter 2', duration_sec: 1700 },
    { ep_num: 3, title: 'Chapter 3', duration_sec: 1600 },
  ],
}

describe('episodesOf', () => {
  it('reads ordered episodes from an opaque series dict', () => {
    const eps = episodesOf(SERIES)
    expect(eps.map((e) => e.epNum)).toEqual([1, 2, 3])
    expect(eps[0].title).toBe('Chapter 1')
  })

  it('returns [] when episodes are missing or malformed', () => {
    expect(episodesOf(undefined)).toEqual([])
    expect(episodesOf({ id: 'x' })).toEqual([])
    expect(episodesOf({ episodes: 'nope' } as unknown as PodcastSeriesSummary)).toEqual([])
  })

  it('drops entries without a positive ep_num and sorts ascending', () => {
    const messy: PodcastSeriesSummary = {
      episodes: [
        { ep_num: 3, title: 'C' },
        { ep_num: 0, title: 'bad' },
        { ep_num: 1, title: 'A' },
      ],
    }
    expect(episodesOf(messy).map((e) => e.epNum)).toEqual([1, 3])
  })
})

describe('nextEpisode', () => {
  it('returns the next ep_num in order', () => {
    expect(nextEpisode(SERIES, 1)?.epNum).toBe(2)
    expect(nextEpisode(SERIES, 2)?.epNum).toBe(3)
  })

  it('returns null at the end of the series', () => {
    expect(nextEpisode(SERIES, 3)).toBeNull()
  })

  it('returns null for an unknown current episode', () => {
    expect(nextEpisode(SERIES, 99)).toBeNull()
  })
})

describe('nextPlayableEpisode (continuous playback gating)', () => {
  it('pro: advances to the very next episode', () => {
    expect(nextPlayableEpisode(SERIES, 1, 'pro')?.epNum).toBe(2)
  })

  it('free: stops after the ep1 preview (next is Pro-locked)', () => {
    // free can only play ep1 (preview); ep2 is locked → no auto-advance.
    expect(nextPlayableEpisode(SERIES, 1, 'free')).toBeNull()
  })

  it('guest: never auto-advances', () => {
    expect(nextPlayableEpisode(SERIES, 1, 'guest')).toBeNull()
  })
})

describe('previewCapSec (free preview time cap)', () => {
  it('caps free preview playback at FREE_PREVIEW_CAP_SEC for ep1', () => {
    expect(previewCapSec('free', 1, true)).toBe(FREE_PREVIEW_CAP_SEC)
  })

  it('no cap for pro', () => {
    expect(previewCapSec('pro', 1, true)).toBeNull()
  })

  it('no cap for guest (cannot play at all)', () => {
    expect(previewCapSec('guest', 1, true)).toBeNull()
  })

  it('no cap when not the preview episode', () => {
    expect(previewCapSec('free', 2, false)).toBeNull()
  })
})

describe('sleep timer options', () => {
  it('offers off + the standard durations', () => {
    expect(SLEEP_OPTIONS).toContain(0)
    expect(SLEEP_OPTIONS).toContain(5 * 60)
    expect(SLEEP_OPTIONS).toContain(15 * 60)
    expect(SLEEP_OPTIONS).toContain(30 * 60)
    expect(SLEEP_OPTIONS).toContain(60 * 60)
  })

  it('labels off and minute durations', () => {
    expect(sleepLabel(0)).toBe('關閉')
    expect(sleepLabel(5 * 60)).toBe('5 分鐘')
    expect(sleepLabel(60 * 60)).toBe('60 分鐘')
  })
})

describe('applyPreviewCap', () => {
  it('passes time through when under the cap', () => {
    expect(applyPreviewCap(120, 180)).toEqual({ time: 120, pause: false })
  })

  it('clamps + pauses at the cap', () => {
    expect(applyPreviewCap(200, 180)).toEqual({ time: 180, pause: true })
    expect(applyPreviewCap(180, 180)).toEqual({ time: 180, pause: true })
  })

  it('never caps when uncapped (pro)', () => {
    expect(applyPreviewCap(5000, null)).toEqual({ time: 5000, pause: false })
  })
})

describe('sleepTick', () => {
  it('decrements above zero', () => {
    expect(sleepTick(10)).toEqual({ remaining: 9, fired: false })
  })

  it('fires at zero', () => {
    expect(sleepTick(1)).toEqual({ remaining: 0, fired: true })
    expect(sleepTick(0)).toEqual({ remaining: 0, fired: true })
  })
})

describe('subtitle size cycling', () => {
  it('exposes the size ladder', () => {
    expect(SUBTITLE_SIZES).toEqual(['s', 'm', 'l', 'xl'])
  })

  it('cycles forward and wraps', () => {
    expect(cycleSubtitleSize('s')).toBe('m')
    expect(cycleSubtitleSize('m')).toBe('l')
    expect(cycleSubtitleSize('l')).toBe('xl')
    expect(cycleSubtitleSize('xl')).toBe('s')
  })
})
