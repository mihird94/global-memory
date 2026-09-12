# Mbrain — Desktop Control Center (macOS)

An interactive, visual control deck for your Global Memory System (GMS), built with Electron and designed to seamlessly interface with your local GMS SQLite database (`~/memories/gms_trust.sqlite`), markdown episodic stores, schema contracts, and Apple Automation.

---

## 🌟 Key Features

1. **Multi-Tier Memory Exploration**:
   - Inspect semantic facts, episodic journal notes, operational runbooks, and procedural playbooks.
   - Filter by namespace (`infra.*`, `trading.*`, `alphaos.*`, `models.*`, `policies.*`) or search globally with `⌘K`.
   - Clickable memory rows opening a deep inspector drawer with provenance, entity relationships, and instant "View in Graph" actions.
2. **Obsidian-Style Knowledge Graph & Subgraph Filtering (UX Pass 2)**:
   - **Collapsible Filter Panel**: Segmented minimum connections selector (`0`, `1+`, `2+` default, `3+`, `5+`, `10+`), multi-select entity types (`CONCEPT`, `INFRA`, `AGENT`, `TICKER`, `POLICY`), predicate filters, and literal node toggle.
   - **Search Reveal**: Searching for an isolated or filtered node gracefully reveals it with an accent indicator rather than showing a blank canvas.
   - **Physics & Layout Controls**: ForceAtlas2 presets (*Balanced*, *Loose*, *Compact*, *Hierarchical*, *Manual*) with auto-stabilization freeze to ensure calm layout and eliminate CPU drift.
   - **Saved Views**: Persistent local presets (*Default Overview*, *Core Infrastructure*, *High Degree Hubs*, *Custom*).
   - **Evidence Inspector**: Click any node or edge to inspect the underlying claims, valid-time windows, and raw supporting text.
3. **Concepts & Entity Intelligence (UX Pass 2)**:
   - **Entity Review Queue**: Surfaces candidate duplicates, missing summaries, isolated entities, and unclassified concepts for quick curation.
   - **Relationship Timelines**: Track bi-temporal relationship lifecycles across active and historical states.
   - **Extraction Scratchpad**: Test deterministic and neural entity extraction on arbitrary text in real time.
4. **Triage & Trust Cockpit (Replacing Steer & Verify)**:
   - **Linear-Style Triage Deck**: Side-by-side visual diffs comparing *Current Truth in Memory* against *Proposed Mutation*, conflict & schema drift badges, and keyboard shortcuts (`A` to Approve & Ledger, `E` to Edit & Merge, `R` to Reject & Dismiss).
   - **Inline Edit & Validation**: Edit quarantined payloads with real-time Pydantic contract validation before approving.
   - **Apple Health-Style Fleet Reliability**: Modular Agent Health Cards with animated SVG circular progress rings, Bayesian confidence tiers (`👑 Verified Core`, `🟢 Autonomous Trusted`, `🟡 Supervised`, `🔴 Degraded`), evidence breakdowns (`+α Verified`, `-β Contested`), and domain specialties.
   - **Resolution Audit Trail**: Live log of recent promotions, supersessions, and retractions across the agent mesh.
5. **Daily Notes & Autonomous Micro-Consolidation**:
   - Built-in Markdown daily note editor with date switcher.
   - **"Process into Memory"**: Triggers `harvest.py` micro-consolidation, extracting candidate facts, validating contracts, extracting bi-temporal knowledge graph triples, updating vector embeddings in `gms_embeddings`, and awarding agent trust.
6. **Nightly Concept Intelligence (Two-Speed Architecture)**:
   - Zero daytime LLM footprint: desktop browsing never loads models into GPU/RAM.
   - Nightly bounded batch enrichment via Dream Cycle (`tools/concept_enrichment.py`, scheduled via `deploy/com.user.gms-dream-cycle.plist` at 03:10) with automatic model eviction (`keep_alive: 0`).
7. **Apple Reminders Integration (Safe Mode)**:
   - Queries incomplete macOS reminders using targeted AppleScript one-liners.
   - Convert tasks into GMS memories with one click.

---

## 🚀 Running the App (macOS)

### 1. Install Dependencies (First Time Only)
```bash
cd desktop
npm install
```

### 2. Launch
```bash
npm start
# OR from repo root:
memoryctl ui
```

---

## 🐧 Linux / Mini PC Compatibility (Opt-In)

The `desktop/` directory is **strictly opt-in**:
- Mini PC Linux and headless servers **never** need to install `node_modules` or launch Electron.
- The core GMS platform (`tools/memoryctl`, `tools/memory_mcp_server.py`, SQLite databases, background launchd/systemd timers) runs entirely in Python with zero Node.js requirements.
- On Linux, if `memoryctl ui` is invoked, it gracefully detects the headless/Linux environment and informs the user.
