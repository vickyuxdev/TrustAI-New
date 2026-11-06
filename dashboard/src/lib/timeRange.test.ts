import { describe, expect, it } from "vitest";
import {
  DAY,
  describeTimeRange,
  isWithinRange,
  parseTimeRangeSpec,
  periodDaysFor,
  rangePhrase,
  resolveTimeRange,
  timeRangeKey,
  timeRangeQuery,
  validateCustomRange,
  writeTimeRangeSpec,
} from "@/lib/timeRange";

const NOW = Date.parse("2026-10-30T12:00:00.000Z");
const params = (q: string) => new URLSearchParams(q);

describe("parseTimeRangeSpec", () => {
  it("defaults to the last 7 days", () => {
    expect(parseTimeRangeSpec(params(""))).toEqual({ kind: "preset", preset: "7d" });
  });

  it("reads a known preset", () => {
    expect(parseTimeRangeSpec(params("range=15m"))).toEqual({ kind: "preset", preset: "15m" });
  });

  it("falls back to the default for an unknown preset", () => {
    expect(parseTimeRangeSpec(params("range=2y"))).toEqual({ kind: "preset", preset: "7d" });
  });

  it("prefers a valid custom range over a preset", () => {
    const spec = parseTimeRangeSpec(params("range=24h&from=2026-09-01T00:00:00Z&to=2026-09-10T00:00:00Z"));
    expect(spec).toEqual({ kind: "custom", from: "2026-09-01T00:00:00.000Z", to: "2026-09-10T00:00:00.000Z" });
  });

  it("ignores reversed or malformed custom bounds", () => {
    expect(parseTimeRangeSpec(params("from=2026-09-10T00:00:00Z&to=2026-09-01T00:00:00Z&range=1h")))
      .toEqual({ kind: "preset", preset: "1h" });
    expect(parseTimeRangeSpec(params("from=nope&to=2026-09-01T00:00:00Z")).kind).toBe("preset");
  });
});

describe("writeTimeRangeSpec", () => {
  it("replaces range params and keeps unrelated ones", () => {
    const next = writeTimeRangeSpec(params("q=agent&from=a&to=b"), { kind: "preset", preset: "1h" });
    expect(next.get("q")).toBe("agent");
    expect(next.get("range")).toBe("1h");
    expect(next.has("from")).toBe(false);
  });

  it("round-trips a custom range through the URL", () => {
    const spec = { kind: "custom", from: "2026-09-01T00:00:00.000Z", to: "2026-09-02T00:00:00.000Z" } as const;
    expect(parseTimeRangeSpec(writeTimeRangeSpec(params(""), spec))).toEqual(spec);
  });
});

describe("resolveTimeRange / API params", () => {
  it("resolves presets relative to now", () => {
    const r = resolveTimeRange({ kind: "preset", preset: "1h" }, NOW);
    expect(r.to.getTime()).toBe(NOW);
    expect(NOW - r.from.getTime()).toBe(60 * 60 * 1000);
  });

  it("sends exact start/end plus a whole-day period_days fallback", () => {
    const q = timeRangeQuery({ kind: "preset", preset: "15m" }, NOW);
    expect(q.start).toBe("2026-10-30T11:45:00.000Z");
    expect(q.end).toBe("2026-10-30T12:00:00.000Z");
    expect(q.period_days).toBe("1");
  });

  it("rounds period_days up to cover a custom range's start and clamps to 90", () => {
    const from = new Date(NOW - 2.5 * DAY);
    expect(periodDaysFor({ from, to: new Date(NOW) }, NOW)).toBe(3);
    expect(periodDaysFor({ from: new Date(NOW - 400 * DAY), to: new Date(NOW) }, NOW)).toBe(90);
  });

  it("uses a stable key for presets so query caches don't churn as time passes", () => {
    expect(timeRangeKey({ kind: "preset", preset: "24h" })).toBe("24h");
  });
});

describe("isWithinRange", () => {
  const range = { from: new Date("2026-10-01T00:00:00Z"), to: new Date("2026-10-02T00:00:00Z") };
  it("includes both bounds and excludes outside times", () => {
    expect(isWithinRange("2026-10-01T00:00:00Z", range)).toBe(true);
    expect(isWithinRange("2026-10-02T00:00:00Z", range)).toBe(true);
    expect(isWithinRange("2026-10-02T00:00:01Z", range)).toBe(false);
    expect(isWithinRange(null, range)).toBe(false);
  });
});

describe("validateCustomRange", () => {
  it("accepts a valid past range", () => {
    const r = validateCustomRange("2026-10-01T09:00", "2026-10-02T17:00", NOW);
    expect(r.ok).toBe(true);
  });

  it("rejects empty, reversed, future and too-old ranges with a readable message", () => {
    expect(validateCustomRange("", "2026-10-02T17:00", NOW)).toMatchObject({ ok: false });
    expect(validateCustomRange("2026-10-02T17:00", "2026-10-01T09:00", NOW)).toMatchObject({ ok: false, error: "Start must be before end." });
    expect(validateCustomRange("2026-11-02T17:00", "2026-11-03T09:00", NOW)).toMatchObject({ ok: false });
    expect(validateCustomRange("2026-01-01T00:00", "2026-01-02T00:00", NOW)).toMatchObject({ ok: false });
  });
});

describe("labels", () => {
  it("names presets in plain language", () => {
    expect(describeTimeRange({ kind: "preset", preset: "24h" })).toBe("Last 24 hours");
    expect(rangePhrase({ kind: "preset", preset: "30d" })).toBe("last 30 days");
  });

  it("omits the year for custom ranges in the current year", () => {
    const from = new Date(2026, 9, 1).toISOString();   // local midnight
    const to = new Date(2026, 9, 15).toISOString();
    expect(describeTimeRange({ kind: "custom", from, to }, NOW)).toBe("Oct 1 – Oct 15");
    expect(rangePhrase({ kind: "custom", from, to })).toContain("selected period");
  });
});
