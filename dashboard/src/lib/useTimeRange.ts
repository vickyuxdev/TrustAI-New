"use client";

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  parseTimeRangeSpec,
  timeRangeKey,
  writeTimeRangeSpec,
  type TimeRangeSpec,
} from "@/lib/timeRange";

/**
 * Reads and updates the global time range stored in the URL (?range= or ?from=&to=).
 * Components using this must render under a <Suspense> boundary (see app/layout.tsx).
 */
export function useTimeRange() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const spec = useMemo(() => parseTimeRangeSpec(searchParams), [searchParams]);
  const key = timeRangeKey(spec);

  const setSpec = useCallback(
    (next: TimeRangeSpec) => {
      const params = writeTimeRangeSpec(searchParams, next);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [searchParams, router, pathname],
  );

  return { spec, key, setSpec };
}
