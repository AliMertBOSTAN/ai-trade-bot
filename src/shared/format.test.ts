import { describe, expect, it } from 'vitest'
import { compact, pct, toConfPct, usd } from './format'

describe('usd', () => {
  it('büyük değerde 2 ondalık', () => {
    expect(usd(1234.5)).toBe('$1,234.50')
  })
  it('küçük değerde 4 ondalık', () => {
    expect(usd(0.12345)).toBe('$0.1235')
  })
  it('geçersiz değerde tire', () => {
    expect(usd(null)).toBe('—')
    expect(usd(undefined)).toBe('—')
    expect(usd(NaN)).toBe('—')
  })
})

describe('compact', () => {
  it('milyar/milyon/bin kısaltır', () => {
    expect(compact(2_300_000_000)).toBe('$2.3B')
    expect(compact(4_500_000)).toBe('$4.5M')
    expect(compact(6_700)).toBe('$6.7K')
    expect(compact(789)).toBe('$789')
  })
  it('negatifte işaret korunur', () => {
    expect(compact(-1_000_000)).toBe('-$1.0M')
  })
})

describe('pct', () => {
  it('işaretli yüzde', () => {
    expect(pct(2.5)).toBe('+2.50%')
    expect(pct(-1.3)).toBe('-1.30%')
  })
})

describe('toConfPct', () => {
  it('finalConfidence varsa onu kullanır', () => {
    expect(toConfPct(0.5, 0.812)).toBe(81)
  })
  it('yoksa confidence kullanır', () => {
    expect(toConfPct(0.75)).toBe(75)
  })
})
