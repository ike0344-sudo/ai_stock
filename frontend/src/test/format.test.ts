import { describe, expect, it } from 'vitest'
import { basisLabel, DASH, fmtTs, retentionBadge } from '@/lib/format'

// 실제 datahub API 로 확인한 값들(2026-09-25): 카탈로그 원본 값이 그대로 오고, 일부 시각은 ISO 가 아닌 문장이었다.
describe('실제 API 값 대응', () => {
  it('fmtTs: ISO 는 포맷, null 은 대시, ISO 가 아닌 문장은 "Invalid Date" 대신 그대로', () => {
    expect(fmtTs('2026-09-25T20:15:00')).toBe('09-25 20:15')
    expect(fmtTs(null)).toBe(DASH)
    expect(fmtTs('2026-10-03 (토) 09:00 이후')).toBe('2026-10-03 (토) 09:00 이후')
    expect(fmtTs('토 09:00 이후')).not.toContain('Invalid')
  })

  it('retentionBadge: 카탈로그 5종을 사람 말로, 모르는 값은 그대로', () => {
    expect(retentionBadge('forever').text).toBe('영구 보관')
    expect(retentionBadge('forever_unrecoverable').text).toContain('재수집 불가')
    expect(retentionBadge('overwrite_20d').text).toContain('덮어씀')
    expect(retentionBadge('regenerable').text).toBe('재생성 가능')
    expect(retentionBadge('keep').text).toBe('보관')
    expect(retentionBadge('something_new').text).toBe('something_new')
  })

  it('basisLabel: derived·reference 를 사람 말로', () => {
    expect(basisLabel('derived')).toBe('파생')
    expect(basisLabel('reference')).toBe('참조')
    expect(basisLabel('AL')).toContain('통합')
    expect(basisLabel('KRX')).toBe('KRX')
    expect(basisLabel('other')).toBe('other')
  })
})
