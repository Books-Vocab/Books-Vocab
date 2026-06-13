import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabForecast scenario fixtures — 對齊 VocabForecastScenarios.swift
 * 「Vocab Forecast」4 態（StatsPresentation.ForecastBucket：id / label / count）。
 *
 * iOS fixture：
 *   buckets(counts:) → counts.enumerated().map { ForecastBucket(id:"d\(i)", label:"+\(i)d", count:) }
 *   7-day  : [12, 5, 8, 3, 6, 9, 4]
 *   14-day : [12, 5, 8, 3, 6, 9, 4, 2, 7, 1, 5, 3, 6, 2]
 *   Compact: (0..<30).map { ($0*7+3) % 13 }
 *   Sparse : [18, 0, 0, 0, 0, 0, 0]
 *
 * label = "+{i}d"（i=0 → "+0d"）。date label 渲染規則見 Screen（今天 / 1週 / 末位 label）。
 */

export type ForecastBucket = {
  /** "+{i}d" */
  label: string
  count: number
}

export type ForecastScenario = {
  buckets: ForecastBucket[]
}

function makeBuckets(counts: number[]): ForecastBucket[] {
  return counts.map((count, i) => ({ label: `+${i}d`, count }))
}

const compactCounts: number[] = Array.from({ length: 30 }, (_, i) => (i * 7 + 3) % 13)

export const VOCAB_FORECAST_FIXTURES: Record<
  ScenarioId<'vocab-forecast'>,
  ForecastScenario
> = {
  '7-day': { buckets: makeBuckets([12, 5, 8, 3, 6, 9, 4]) },
  '14-day': { buckets: makeBuckets([12, 5, 8, 3, 6, 9, 4, 2, 7, 1, 5, 3, 6, 2]) },
  compact: { buckets: makeBuckets(compactCounts) },
  sparse: { buckets: makeBuckets([18, 0, 0, 0, 0, 0, 0]) },
}
