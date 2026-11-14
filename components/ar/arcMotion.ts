/** Peak speed at 20% of the duration, followed by 80% deceleration. No overshoot. */
export function arcSnapEasing(time: number) {
  const t = Math.max(0, Math.min(1, time));
  return t < 0.2 ? t * t / 0.2 : 1 - (1 - t) * (1 - t) / 0.8;
}
