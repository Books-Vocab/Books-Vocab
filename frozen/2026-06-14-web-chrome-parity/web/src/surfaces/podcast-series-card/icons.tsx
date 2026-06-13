import { makeFilledGlyph } from '../../shared/glyph'

/**
 * SF `waveform` — PodcastSeriesCard 封面右上角 badge 圖示。
 *
 * iOS：`Image(systemName: "waveform")` · caption2(bold, 11pt) · primaryText。
 * SF waveform 是「等化器豎條 + 高度起伏」的聲波字符（非 shell tab 的 5 等高豎條
 * 簡化版）。此處用 filled glyph 還原其 9 條變高條形（短-高-短-最高-短-高 起伏），
 * 條形以 currentColor 實心矩形，圓角端點對齊 SF 的 round cap 觀感。
 */
export const WaveformBadgeIcon = makeFilledGlyph(
  // 9 條豎條，x 等距，高度起伏對稱（中央最高），rx=0.55 模擬 round cap
  '<rect x="2.0"  y="10.5" width="1.1" height="3"   rx="0.55"/>' +
    '<rect x="4.7"  y="8"    width="1.1" height="8"   rx="0.55"/>' +
    '<rect x="7.4"  y="5"    width="1.1" height="14"  rx="0.55"/>' +
    '<rect x="10.1" y="9.5"  width="1.1" height="5"   rx="0.55"/>' +
    '<rect x="12.8" y="3"    width="1.1" height="18"  rx="0.55"/>' +
    '<rect x="15.5" y="7"    width="1.1" height="10"  rx="0.55"/>' +
    '<rect x="18.2" y="9"    width="1.1" height="6"   rx="0.55"/>' +
    '<rect x="20.9" y="10.5" width="1.1" height="3"   rx="0.55"/>',
)
