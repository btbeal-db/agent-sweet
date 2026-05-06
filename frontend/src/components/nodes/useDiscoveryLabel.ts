import { useEffect, useState } from "react";
import { fetchDiscoveryOptions, getDiscoveryCache } from "../../api";

/** Resolve a stored ID to its friendly label using the discovery cache.
 *  Returns the value itself as a fallback while the cache is warming. */
export function useDiscoveryLabel(endpoint: string, value: string): string {
  const [label, setLabel] = useState<string>(() => {
    if (!value) return "";
    const cached = getDiscoveryCache(endpoint);
    return cached?.options.find((o) => o.value === value)?.label ?? value;
  });

  useEffect(() => {
    if (!value) {
      setLabel("");
      return;
    }
    let cancelled = false;
    const cached = getDiscoveryCache(endpoint);
    const cachedHit = cached?.options.find((o) => o.value === value)?.label;
    if (cachedHit) {
      setLabel(cachedHit);
      return;
    }
    setLabel(value);
    fetchDiscoveryOptions(endpoint).then((res) => {
      if (cancelled) return;
      const found = res.options.find((o) => o.value === value)?.label;
      if (found) setLabel(found);
    });
    return () => { cancelled = true; };
  }, [endpoint, value]);

  return label;
}
