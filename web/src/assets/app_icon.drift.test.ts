import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// app_icon drift guard
// ------------------------------------------------------------------
// web/src/assets/app_icon.png 是 iOS AppIconImage.imageset/app_icon.png 的
// byte-identical 副本（SoT = iOS asset catalog）。iOS icon 更新時 web 端會
// 無聲漂移，這支測試把它釘成跨平台 drift guard：兩檔 byte 不一致即紅。
// 修復 = 重新從 iOS SoT 拷貝（失敗訊息會印出確切的 cp 指令）。

const here = dirname(fileURLToPath(import.meta.url))
const webIcon = resolve(here, 'app_icon.png')
const iosIcon = resolve(
  here,
  '../../../ios/BooksAndVocab/Assets.xcassets/AppIconImage.imageset/app_icon.png',
)

const sha256 = (path: string) =>
  createHash('sha256').update(readFileSync(path)).digest('hex')

describe('app_icon drift guard', () => {
  it('web/src/assets/app_icon.png is byte-identical to the iOS SoT', () => {
    const iosHash = sha256(iosIcon)
    const webHash = sha256(webIcon)
    expect(
      webHash,
      `web app_icon.png drifted from iOS SoT.\n` +
        `  iOS  ${iosHash}\n` +
        `  web  ${webHash}\n` +
        `fix: cp ios/BooksAndVocab/Assets.xcassets/AppIconImage.imageset/app_icon.png web/src/assets/app_icon.png`,
    ).toBe(iosHash)
  })
})
