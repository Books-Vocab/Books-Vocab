import type { ComponentType } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { ExclamationTriangleIcon, RefreshIcon } from './icons'

type GlyphProps = { className?: string; size?: number; strokeWidth?: number }

export interface PdfErrorAction {
  title: string
  icon: ComponentType<GlyphProps>
}

export interface PdfErrorFixture {
  icon: ComponentType<GlyphProps>
  title: string
  description: string
  action: PdfErrorAction
}

/**
 * PDFReaderView.errorView 各 scenario 的 AppEmptyStateCard 內容。
 * 文案逐字對齊 PDFReaderView.swift：
 *   title       = "無法開啟 PDF"（固定）
 *   description = loadError（iCloud 占位符／未下載分支）
 *   action      = "重試載入" / arrow.clockwise（retryLoad）
 * catalog 唯一 scene = File unavailable（isReadableFile=false 分支）。
 */
export const PDF_READER_UNAVAILABLE_FIXTURES: Record<
  ScenarioId<'pdf-reader-unavailable'>,
  PdfErrorFixture
> = {
  // isReadableFile(atPath:)==false → iCloud 占位符 / 未下載 / 已移除
  'file-unavailable': {
    icon: ExclamationTriangleIcon,
    title: '無法開啟 PDF',
    description:
      'PDF 檔案尚未從 iCloud 下載完成或已被移除。請確認檔案可在「檔案」App 中開啟後再試一次。',
    action: { title: '重試載入', icon: RefreshIcon },
  },
}
