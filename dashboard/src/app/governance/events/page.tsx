"use client";
import { useState } from "react";
import { ScrollText } from "lucide-react";
import { AgentLink, SeverityBadge } from "@/components/gov";
import { Card, CardHeader, ChipSelect, Drawer, Empty, ErrorState, PageHead, SkelRows } from "@/components/ui";
import { useAgentIndex, useEvents, type GovEvent } from "@/lib/governance";
import { ago, humanize, when } from "@/lib/format";

const SEVS = ["info", "low", "medium", "high", "critical"];

export default function EventsPage() {
  const [sev, setSev] = useState("");
  const [type, setType] = useState("");
  const [sel, setSel] = useState<GovEvent | null>(null);
  const events = useEvents({ severity: sev || undefined, event_type: type || undefined, limit: 200 });
  const all = useEvents({ limit: 200 });
  const index = useAgentIndex();
  const types = Array.from(new Set((all.data ?? []).map((e) => e.event_type))).sort();
  const items = events.data ?? [];

  return (
    <>
      <PageHead title="Audit events" sub="Append-only record of every governance action: onboarding, lifecycle changes, assessments, decisions, red-team runs, deployments and policy violations."
        actions={<>
          <ChipSelect label="Type" value={type} onChange={setType} options={[{ value: "", label: "All" }, ...types.map((t) => ({ value: t, label: humanize(t) }))]} />
          <ChipSelect label="Severity" value={sev} onChange={setSev} options={[{ value: "", label: "All" }, ...SEVS.map((s) => ({ value: s, label: humanize(s) }))]} />
        </>} />
      <Card labelledBy="t-evt">
        <CardHeader id="t-evt" title="Events" sub={`${items.length} shown · newest first · refreshes every 30s`} />
        <div style={{ marginTop: 12 }}>
          {events.isError ? <div className="card-b"><ErrorState error={events.error} onRetry={() => events.refetch()} /></div> : events.isLoading ? <SkelRows rows={8} /> : !items.length ? (
            <Empty icon={ScrollText} title="No events">{sev || type ? "Try clearing a filter." : "Events appear as agents are onboarded and governed."}</Empty>
          ) : (
            <div className="scroll-x"><table>
              <thead><tr><th>When</th><th>Event</th><th>Severity</th><th>Agent</th><th>Resource</th><th>Actor</th></tr></thead>
              <tbody>{items.map((e) => (
                <tr key={e.id} className="clickable" onClick={() => setSel(e)}>
                  <td className="muted" title={when(e.created_at)}>{ago(e.created_at)}</td>
                  <td className="strong">{humanize(e.event_type)}</td>
                  <td><SeverityBadge severity={e.severity} /></td>
                  <td onClick={(x) => x.stopPropagation()}><AgentLink agent={e.agent_id ? index[e.agent_id] : undefined} id={e.agent_id} /></td>
                  <td className="muted">{humanize(e.resource_type)}</td>
                  <td>{e.actor}</td>
                </tr>))}</tbody>
            </table></div>
          )}
        </div>
      </Card>
      <Drawer open={!!sel} onClose={() => setSel(null)} title={sel ? humanize(sel.event_type) : ""} sub={sel ? when(sel.created_at) : undefined}>
        {sel && (
          <div className="stack">
            <dl className="kv">
              <dt>Severity</dt><dd><SeverityBadge severity={sel.severity} /></dd>
              <dt>Actor</dt><dd>{sel.actor}</dd>
              <dt>Resource</dt><dd>{humanize(sel.resource_type)} · {sel.resource_id}</dd>
              <dt>Agent</dt><dd><AgentLink agent={sel.agent_id ? index[sel.agent_id] : undefined} id={sel.agent_id} /></dd>
            </dl>
            <section><h3 className="small strong" style={{ margin: "0 0 6px" }}>Details</h3><pre className="code">{JSON.stringify(sel.payload, null, 2)}</pre></section>
          </div>
        )}
      </Drawer>
    </>
  );
}
