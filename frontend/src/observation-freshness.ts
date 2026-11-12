// Presentation/control observation age, not vehicle SOC or plan provenance.
export const OBSERVATION_MAX_AGE_MS = 90_000;
export const OBSERVATION_CLOCK_SKEW_MS = 5_000;

export function observationFreshness(timestamp: number | null, now: number, failed = false, maxAge = OBSERVATION_MAX_AGE_MS): 'fresh' | 'failed' | 'invalid' | 'future' | 'old' {
  if (failed) return 'failed';
  if (timestamp === null || !Number.isFinite(timestamp) || !Number.isFinite(now)) return 'invalid';
  if (timestamp > now + OBSERVATION_CLOCK_SKEW_MS) return 'future';
  if (now - timestamp > maxAge) return 'old';
  return 'fresh';
}
