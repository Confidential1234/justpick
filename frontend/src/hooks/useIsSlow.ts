import { useEffect, useState } from "react";

/**
 * True once `active` has been true for longer than `delayMs`.
 *
 * The API is on a free tier that sleeps after inactivity, so the first request of the
 * day can take the better part of a minute. Without an explanation, a spinner that long
 * reads as broken and the visitor leaves before it ever answers.
 */
export function useIsSlow(active: boolean, delayMs = 4000): boolean {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (!active) {
      setSlow(false);
      return;
    }
    const timer = setTimeout(() => setSlow(true), delayMs);
    return () => clearTimeout(timer);
  }, [active, delayMs]);

  return slow;
}
