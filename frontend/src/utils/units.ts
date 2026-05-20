import type { UnitSystem } from '../types'

export const CM_PER_INCH = 2.54

export function cmToIn(cm: number): number {
  return cm / CM_PER_INCH
}

export function inToCm(inches: number): number {
  return inches * CM_PER_INCH
}

/** Convert a cm value to the display unit, rounded to 2 decimal places. */
export function toDisplay(cm: number, unit: UnitSystem): number {
  const v = unit === 'imperial' ? cmToIn(cm) : cm
  return Math.round(v * 100) / 100
}

/** Convert a display value (in the given unit) back to cm for storage. */
export function fromDisplay(v: number, unit: UnitSystem): number {
  return unit === 'imperial' ? inToCm(v) : v
}

/** Label string for the active unit ("cm" or "in"). */
export function unitLabel(unit: UnitSystem): string {
  return unit === 'imperial' ? 'in' : 'cm'
}

/** Sensible min/max bounds for a measurement field in the given unit. */
export function convertBounds(
  minCm: number,
  maxCm: number,
  unit: UnitSystem,
): { min: number; max: number } {
  if (unit === 'imperial') {
    return {
      min: Math.round(cmToIn(minCm) * 100) / 100,
      max: Math.round(cmToIn(maxCm) * 100) / 100,
    }
  }
  return { min: minCm, max: maxCm }
}
