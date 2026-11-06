/** Picks a domain icon for a project from its name (then description). */
import { createElement } from "react";
import { BookOpen, FileText, FolderKanban, Headset, Receipt, ScanSearch, ShieldCheck, Stethoscope, TrendingUp, Users, type LucideIcon } from "lucide-react";

const ICONS: [RegExp, LucideIcon][] = [
  [/clinic|health|patient|medic|note/i, Stethoscope], [/support|ticket|help|service/i, Headset], [/invoice|billing|payment|finance/i, Receipt],
  [/policy|q&a|faq|knowledge|docs?/i, BookOpen], [/sales|pipeline|forecast|insight/i, TrendingUp], [/hr|people|employee/i, Users],
  [/claim|insur/i, ShieldCheck], [/search|discover/i, ScanSearch], [/contract|legal/i, FileText],
];

export const projectIcon = (name: string, desc = "", className = "ic") =>
  createElement(ICONS.find(([r]) => r.test(name))?.[1] ?? ICONS.find(([r]) => r.test(desc))?.[1] ?? FolderKanban, { className });
