import React from "react";

import {
  DataComponent, DataTable, EvidenceChart, MetricCard, ReportSection,
  RichNarrative, useDataApp,
} from "../../data-app-public.jsx";

const inventorySpec = { type: "horizontalBar", x: "records", y: "layer", colors: { records: "var(--chart-1)" }, valueDecimals: 0 };
const factShapeSpec = { type: "horizontalBar", x: "facts", y: "shape", colors: { facts: "var(--chart-2)" }, valueDecimals: 0 };
const candidateSpec = { type: "bar", x: "recordType", y: "candidates", colors: { candidates: "var(--chart-3)" }, valueDecimals: 0 };
const graphSpec = { type: "horizontalBar", x: "value", y: "measure", colors: { value: "var(--chart-4)" }, valueDecimals: 0 };

export function ReportContent() {
  const { reviewedRows, visible, canEdit, mode, appTitle, setAppTitle } = useDataApp();
  const inventory = reviewedRows("inventory");
  const facts = reviewedRows("fact_structure");
  const candidates = reviewedRows("candidate_queue");
  const graph = reviewedRows("graph_quality");
  const findings = reviewedRows("quality_findings");
  const embeddings = reviewedRows("embedding_coverage");

  return <article className="report-content" aria-label="Brain memory quality report">
    <header className="report-hero">
      <p className="report-kicker">Brain memory audit · live local store · September 10, 2026</p>
      <h1 data-data-app-title contentEditable={canEdit && mode === "edit"} suppressContentEditableWarning
        onBlur={canEdit && mode === "edit" ? (event) => setAppTitle(event.currentTarget.textContent.trim() || appTitle) : undefined}>
        {appTitle}
      </h1>
      <RichNarrative id="report:description" className="report-deck"
        value="The system is technically capable—versioned claims, a review queue, project continuity, graph traversal, and vector search all exist. The bottleneck is knowledge quality: most facts still lack the structured rationale and scope that make memory dependable across agents." />
    </header>

    {visible("executive-summary") && <ReportSection id="executive-summary" title="Executive summary"
      queryId="quality_findings" sourceRows={findings} showHeading={false}>
      <RichNarrative id="executive-summary:body" className="report-summary-lead" value={`## Executive summary

- **Operational foundation is real.** Brain contains 113 ledger claims, 297 indexed chunks, 266 graph entities, 78 dated history entries, and a working reviewed-candidate lifecycle.
- **The semantic layer is the weak point.** 85 of 90 facts are flat values, and the convention audit found zero accepted records conforming to the new structured context schema.
- **Safety controls are behaving correctly.** All 11 AI-curated candidates remain proposed with valid payloads and source evidence; none was silently promoted. The pollution audit found zero confirmed pollutants.
- **The next useful pass is curation, not more surfaces.** Remove high-signal fixture artifacts, review the seven decision/policy candidates, resolve one key collision, repair one opaque status, and deepen graph predicates from accepted structured records.`} />
    </ReportSection>}

    <div className="report-facts" aria-label="Key memory quality measures">
      <MetricCard id="metric-flat" title="Flat semantic facts" queryId="fact_structure" sourceRows={facts}
        value="85 / 90" description="Values without a structured context envelope." />
      <MetricCard id="metric-candidates" title="Awaiting human review" queryId="candidate_queue" sourceRows={candidates}
        value="11" description="Schema-valid AI proposals; all remain outside current truth." />
      <MetricCard id="metric-fixtures" title="Fixture-like claims" queryId="quality_findings" sourceRows={findings}
        value="18" description="Warning-only suspects; nine meet cleanup eligibility rules." />
      <MetricCard id="metric-graph" title="Specific graph edges" queryId="graph_quality" sourceRows={graph}
        value="9 / 143" description="Relationships using predicates richer than configured_as." />
    </div>

    <section className="report-section">
      <ReportSection id="composition-analysis" title="Storage breadth is ahead of semantic maturity"
        queryId="inventory" queryIds={["inventory", "fact_structure"]}
        sourceRowsByQuery={{ inventory, fact_structure: facts }} showHeading={false}>
        <RichNarrative id="composition-analysis:body" className="report-analysis" value={`## Storage breadth is ahead of semantic maturity

Brain stores the same working context in several useful forms, so the layer counts should not be added together. The 297-vector index and 266-entity graph make retrieval broad, but neither compensates for weak source records. Only five semantic values are object-shaped at all, and shape alone does not prove they carry complete rationale, implications, scope, provenance, or review conditions.`} />
      </ReportSection>
      <div className="report-chart-grid">
        <EvidenceChart id="inventory-chart" queryId="inventory" title="Physical records by memory layer"
          spec={inventorySpec} rows={inventory} sourceRows={inventory} height={360} />
        <EvidenceChart id="fact-shape-chart" queryId="fact_structure" title="Almost all semantic facts remain flat"
          spec={factShapeSpec} rows={facts} sourceRows={facts} height={260} />
      </div>
    </section>

    <section className="report-section">
      <ReportSection id="curation-analysis" title="The queue is safe, but useful knowledge is waiting"
        queryId="candidate_queue" sourceRows={candidates} showHeading={false}>
        <RichNarrative id="curation-analysis:body" className="report-analysis" value={`## The queue is safe, but useful knowledge is waiting

The 11 proposals are not random text: every payload is valid JSON and every candidate carries one evidence item. Seven are decisions or policies—the records most likely to improve future agent behavior—but they remain unavailable to ordinary current-truth retrieval until reviewed. This is the right safety posture, but it creates a clear curation backlog.`} />
      </ReportSection>
      <EvidenceChart id="candidate-chart" queryId="candidate_queue" title="Proposed records awaiting review"
        spec={candidateSpec} rows={candidates} sourceRows={candidates} height={300} />
    </section>

    <section className="report-section">
      <ReportSection id="graph-analysis" title="The graph is connected, not yet explanatory"
        queryId="graph_quality" sourceRows={graph} showHeading={false}>
        <RichNarrative id="graph-analysis:body" className="report-analysis" value={`## The graph is connected, not yet explanatory

Only one of 266 entities is unlinked, which is good structural coverage. But 134 of 143 edges use the generic predicate **configured_as**. The graph therefore looks dense while encoding little about causality, ownership, dependencies, decisions, or temporal change. Typed relationships should be harvested from reviewed structured records—not inferred indiscriminately from raw journal text.`} />
      </ReportSection>
      <EvidenceChart id="graph-chart" queryId="graph_quality" title="Graph coverage versus semantic depth"
        spec={graphSpec} rows={graph} sourceRows={graph} height={340} />
    </section>

    <section className="report-section">
      <ReportSection id="priority-analysis" title="A focused curation pass would add more value than another feature pass"
        queryId="quality_findings" sourceRows={findings} showHeading={false}>
        <RichNarrative id="priority-analysis:body" className="report-analysis" value={`## A focused curation pass would add more value than another feature pass

The first four actions below directly improve what another agent can safely retrieve. The remaining items improve precision and product honesty. None requires accepting AI decisions automatically or deleting ambiguous records without review.`} />
      </ReportSection>
      <DataComponent id="quality-table" title="Prioritized memory-quality findings" queryId="quality_findings"
        kind="table" displayRows={findings} sourceRows={findings}>
        <DataTable rows={findings} rowKey="priority" searchable={false} caption="Prioritized memory-quality findings"
          columns={[
            { key: "priority", label: "#" },
            { key: "severity", label: "Severity", presentation: "status" },
            { key: "finding", label: "Finding" },
            { key: "evidence", label: "Evidence" },
            { key: "recommendedAction", label: "Recommended action" },
          ]} />
      </DataComponent>
    </section>

    <ReportSection id="methods" title="Scope and limitations" queryId="embedding_coverage"
      queryIds={["embedding_coverage", "claim_status"]}
      sourceRowsByQuery={{ embedding_coverage: embeddings, claim_status: reviewedRows("claim_status") }} showHeading={false}>
      <RichNarrative id="methods:body" className="report-disclosure" value={`## Scope and limitations

This is a point-in-time audit of the local Brain store. Counts describe physical representations and overlap by design. “Structured” describes value shape; the stricter convention audit controls whether a record satisfies the full context contract. Suspected fixtures are warnings, not confirmed pollution. No candidates were accepted, no facts migrated, and no cleanup was performed for this report.`} />
    </ReportSection>
  </article>;
}
