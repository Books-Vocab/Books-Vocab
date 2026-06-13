import { describe, expect, it } from 'vitest'
import {
  forceConfigToAutoLink,
  autoLinkToForceConfig,
  sliderFill,
  formatForceValue,
} from './store'
import { DEFAULT_FORCES, FORCE_BOUNDS } from './forceGraph'

describe('forceConfigToAutoLink', () => {
  it('serializes a force config into a flat auto_link config bag', () => {
    const bag = forceConfigToAutoLink(DEFAULT_FORCES)
    expect(bag).toMatchObject({
      center_force: 0.24,
      repel_force: 0.76,
      link_force: 0.32,
      link_distance: 120,
      node_size: 4.2,
      link_thickness: 1.1,
    })
  })
})

describe('autoLinkToForceConfig', () => {
  it('round-trips through serialization', () => {
    const bag = forceConfigToAutoLink(DEFAULT_FORCES)
    expect(autoLinkToForceConfig(bag)).toEqual(DEFAULT_FORCES)
  })

  it('falls back to defaults for a null / empty bag', () => {
    expect(autoLinkToForceConfig(null)).toEqual(DEFAULT_FORCES)
    expect(autoLinkToForceConfig({})).toEqual(DEFAULT_FORCES)
  })

  it('clamps stored out-of-range values into GraphForces bounds', () => {
    const c = autoLinkToForceConfig({ node_size: 99, link_distance: -5 })
    expect(c.nodeSize).toBe(FORCE_BOUNDS.nodeSize[1])
    expect(c.linkDistance).toBe(FORCE_BOUNDS.linkDistance[0])
  })

  it('ignores non-numeric stored values', () => {
    const c = autoLinkToForceConfig({ center_force: 'nope' as unknown as number })
    expect(c.centerForce).toBe(DEFAULT_FORCES.centerForce)
  })
})

describe('sliderFill', () => {
  it('maps a value to its 0..1 fill fraction within bounds', () => {
    expect(sliderFill('centerForce', 0.5)).toBeCloseTo(0.5)
    expect(sliderFill('linkDistance', 20)).toBe(0)
    expect(sliderFill('linkDistance', 300)).toBe(1)
    expect(sliderFill('linkDistance', 120)).toBeCloseTo((120 - 20) / (300 - 20))
  })
})

describe('formatForceValue', () => {
  it('matches iOS slider value formatting precision', () => {
    expect(formatForceValue('centerForce', 0.24)).toBe('0.24') // %.2f
    expect(formatForceValue('linkDistance', 120)).toBe('120') // %.0f
    expect(formatForceValue('nodeSize', 4.2)).toBe('4.2') // %.1f
    expect(formatForceValue('linkThickness', 1.1)).toBe('1.1') // %.1f
  })
})
