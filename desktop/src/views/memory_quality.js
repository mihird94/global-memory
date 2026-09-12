window.MemoryQualityView = {
  data: null,
  migration: null,
  filter: 'all',
  esc(value) { const d=document.createElement('div'); d.textContent=String(value ?? ''); return d.innerHTML; },
  async render(container) {
    container.innerHTML = `<div class="mq-shell"><div class="view-header"><div><div class="eyebrow">CONTEXT ENGINEERING</div><h1>Memory Quality</h1><p>Inspect lifecycle readiness, evidence, provenance, and migration blockers. Counts are objective—there is no synthetic health score.</p></div><button class="btn-secondary" id="mq-refresh">Refresh</button></div><div class="mq-loading">Auditing memory conventions…</div></div>`;
    document.getElementById('mq-refresh').onclick=()=>this.render(container);
    try {
      [this.data,this.migration]=await Promise.all([window.gms.getMemoryQuality(),window.gms.getMigrationInventory()]);
      this.draw(container);
    } catch(e) { container.querySelector('.mq-loading').textContent=`Unable to load audit: ${e.message}`; }
  },
  draw(container) {
    const q=this.data, m=this.migration;
    const metrics=[
      ['Structured active',q.structured_active_records],['Legacy flat',q.legacy_flat_records],
      ['Pending AI candidates',q.pending_ai_candidates],['Fixture warnings',q.suspected_fixture_count],
      ['Invalid evidence',q.invalid_or_missing_evidence],['Unresolved conflicts',q.unresolved_contradictions],
      ['Key collisions',q.key_collision_count],['Needs context',(q.status_only_facts||[]).length]
    ];
    const rows=(m.rows||[]).filter(r=>this.filter==='all'||r.risk===this.filter||r.readiness===this.filter);
    container.innerHTML=`<div class="mq-shell">
      <div class="view-header"><div><div class="eyebrow">CONTEXT ENGINEERING</div><h1>Memory Quality</h1><p>Review evidence and lifecycle readiness without changing live memory.</p></div><button class="btn-secondary" id="mq-refresh">Refresh</button></div>
      <div class="mq-metrics">${metrics.map(x=>`<div class="mq-metric"><span>${this.esc(x[0])}</span><strong>${this.esc(x[1])}</strong></div>`).join('')}</div>
      <div class="mq-section"><div class="mq-section-head"><div><h2>Legacy migration workbench</h2><p>${m.total} untouched records · preview only · legacy sources remain readable</p></div><select id="mq-filter" class="form-control mq-filter"><option value="all">All records</option><option value="high">High risk</option><option value="medium">Medium risk</option><option value="low">Low risk</option><option value="blocked">Blocked</option><option value="ready">Ready</option></select></div>
      <div class="mq-table" role="table"><div class="mq-row mq-header" role="row"><span>Memory</span><span>Curation</span><span>Readiness</span><span>Recommended operation</span></div>${rows.map(r=>this.row(r)).join('')}</div></div>
      <div class="mq-grid"><section class="mq-section"><h2>Canonical-key collisions</h2>${(q.key_collisions||[]).map(c=>`<article class="mq-alert"><strong>${this.esc(c.canonical_key)}</strong><div>${c.records.map(x=>this.esc(x.key)).join(' ↔ ')}</div><small>${this.esc(c.proposal)} proposal · unresolved · review required</small></article>`).join('')||'<p class="empty-state">No collisions.</p>'}</section>
      <section class="mq-section"><h2>Records needing context</h2>${(q.status_only_facts||[]).map(k=>`<article class="mq-alert"><strong>${this.esc(k)}</strong><div class="mq-chips"><span>Rationale</span><span>Scope</span><span>Implication</span><span>Source</span><span>Effective time</span><span>Next review</span></div><small>Value preserved; no context invented.</small></article>`).join('')||'<p class="empty-state">No opaque status records.</p>'}</section></div>
      <details class="mq-section"><summary>Suspected fixture evidence (${q.suspected_fixture_count})</summary>${(q.suspected_fixtures||[]).map(x=>`<div class="mq-fixture"><strong>#${x.claim_id} ${this.esc(x.key)}</strong><span>${x.signals.map(this.esc.bind(this)).join(' · ')}</span><em>${x.eligible_for_cleanup?'eligible for exact-ID preview':'warning only'}</em></div>`).join('')}</details>
    </div>`;
    document.getElementById('mq-refresh').onclick=()=>this.render(container);
    const f=document.getElementById('mq-filter'); f.value=this.filter; f.onchange=()=>{this.filter=f.value;this.draw(container);};
  },
  row(r) {
    const auth='Legacy imported';
    return `<div class="mq-row" role="row" tabindex="0"><span><strong>${this.esc(r.legacy_key)}</strong><small>${this.esc(r.proposed_key)}</small></span><span><b class="authority-badge legacy">${auth}</b><small>${this.esc(r.classification)}</small></span><span><b class="risk ${r.risk}">${this.esc(r.risk)}</b><small>${this.esc(r.readiness)}</small></span><span><strong>${this.esc(r.recommended_operation)}</strong><small>${this.esc((r.blockers||[]).join('; ')||'Deterministically ready')}</small></span></div>`;
  }
};
