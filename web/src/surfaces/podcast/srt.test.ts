import { describe, expect, it } from 'vitest'
import { activeCueIndex, parseSrt, parseTimestamp } from './srt'

const SAMPLE = `1
00:00:00,000 --> 00:00:03,500
Welcome back to Deep Work, Decoded.

2
00:00:03,500 --> 00:00:06,000
Today we trace the comfort crisis.

3
00:00:06,000 --> 00:00:09,250
Easy distraction quietly erodes our focus.
`

describe('parseTimestamp', () => {
  it('decodes HH:MM:SS,mmm to seconds', () => {
    expect(parseTimestamp('00:00:06,090')).toBeCloseTo(6.09, 6)
    expect(parseTimestamp('01:02:03,500')).toBeCloseTo(3723.5, 6)
  })

  it('tolerates a dot millisecond separator and short ms', () => {
    expect(parseTimestamp('00:00:01.5')).toBeCloseTo(1.5, 6)
  })

  it('returns NaN on garbage', () => {
    expect(Number.isNaN(parseTimestamp('nope'))).toBe(true)
  })
})

describe('parseSrt', () => {
  it('parses ordered cues with start/end/text', () => {
    const cues = parseSrt(SAMPLE)
    expect(cues).toHaveLength(3)
    expect(cues[0]).toMatchObject({ index: 1, start: 0, end: 3.5, text: 'Welcome back to Deep Work, Decoded.' })
    expect(cues[2].text).toBe('Easy distraction quietly erodes our focus.')
  })

  it('tolerates CRLF, BOM, and missing trailing newline', () => {
    const crlf = '﻿1\r\n00:00:00,000 --> 00:00:02,000\r\nHello world'
    const cues = parseSrt(crlf)
    expect(cues).toHaveLength(1)
    expect(cues[0].text).toBe('Hello world')
  })

  it('joins multi-line cue text with a space', () => {
    const multi = `1
00:00:00,000 --> 00:00:02,000
line one
line two`
    expect(parseSrt(multi)[0].text).toBe('line one line two')
  })

  it('skips blocks with no valid timing instead of throwing', () => {
    const broken = `1
not a timing line
orphan text

2
00:00:01,000 --> 00:00:02,000
Good cue`
    const cues = parseSrt(broken)
    expect(cues).toHaveLength(1)
    expect(cues[0].text).toBe('Good cue')
  })

  it('infers an index when the numeric line is absent', () => {
    const noIndex = `00:00:00,000 --> 00:00:02,000
First`
    expect(parseSrt(noIndex)[0].index).toBe(1)
  })
})

describe('activeCueIndex', () => {
  const cues = parseSrt(SAMPLE)

  it('returns the half-open cue containing t', () => {
    expect(activeCueIndex(cues, 0)).toBe(0)
    expect(activeCueIndex(cues, 3.4)).toBe(0)
    expect(activeCueIndex(cues, 3.5)).toBe(1) // boundary belongs to next cue
    expect(activeCueIndex(cues, 6.09)).toBe(2) // catalog playhead → 3rd sentence
  })

  it('returns -1 before the first cue and after the last', () => {
    expect(activeCueIndex(cues, -1)).toBe(-1)
    expect(activeCueIndex(cues, 9.25)).toBe(-1)
    expect(activeCueIndex(cues, 999)).toBe(-1)
  })

  it('returns -1 for an empty cue list', () => {
    expect(activeCueIndex([], 5)).toBe(-1)
  })
})
