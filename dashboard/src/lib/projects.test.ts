import { describe, expect, it } from "vitest";
import { projectLabels } from "./projects";

describe("projectLabels", () => {
  it("uses the plain name when it is unique", () => {
    expect(projectLabels([{ id: "1", name: "Expense Checker", slug: "expense-checker" }])).toEqual({ "1": "Expense Checker" });
  });

  it("adds the slug when two projects share a name", () => {
    const labels = projectLabels([
      { id: "1", name: "AP Agent", slug: "ap-agent" },
      { id: "2", name: "AP Agent", slug: "ap-agent-eu" },
      { id: "3", name: "Other", slug: "other" },
    ]);
    expect(labels).toEqual({ "1": "AP Agent (ap-agent)", "2": "AP Agent (ap-agent-eu)", "3": "Other" });
  });

  it("falls back to the name when a repeated project has no slug", () => {
    expect(projectLabels([{ id: "1", name: "Same" }, { id: "2", name: "Same", slug: null }])).toEqual({ "1": "Same", "2": "Same" });
  });

  it("handles an empty list", () => {
    expect(projectLabels([])).toEqual({});
  });
});
