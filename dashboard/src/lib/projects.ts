/**
 * Project display labels. Projects are the top level of the dashboard, and two projects can share a name (the same
 * application set up twice), so a repeated name is shown with its slug to tell the entries apart.
 */

export interface ProjectRef {
  id: string;
  name: string;
  slug?: string | null;
}

/** id -> label: the project name, or "Name (slug)" when another project has the same name. */
export function projectLabels(projects: readonly ProjectRef[]): Record<string, string> {
  const seen = new Map<string, number>();
  projects.forEach((p) => seen.set(p.name, (seen.get(p.name) ?? 0) + 1));
  const labels: Record<string, string> = {};
  projects.forEach((p) => {
    labels[p.id] = (seen.get(p.name) ?? 0) > 1 && p.slug ? `${p.name} (${p.slug})` : p.name;
  });
  return labels;
}
