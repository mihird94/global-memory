# Mbrain — Desktop Control Center (macOS)

An interactive, visual control deck for your Global Memory System (GMS), built with Electron and designed to seamlessly interface with your local GMS SQLite database (`~/memories/gms_trust.sqlite`), markdown episodic stores, schema contracts, and Apple Automation.

---

## 🌟 Key Features

1. **Multi-Tier Memory Exploration**:
   - Inspect semantic facts, episodic journal notes, operational runbooks, and procedural playbooks.
   - Filter by namespace (`infra.*`, `trading.*`, `alphaos.*`, `models.*`, `policies.*`) or search globally with `⌘K`.
2. **Steering & Human Verification**:
   - **Quarantine Review Inbox**: Inspect pending or conflicting claims and resolve them with one click (**Accept & Boost Trust** / **Reject & Penalize**).
   - **Inline Fact Editor**: Edit any existing fact with live Pydantic contract validation before persisting.
   - **Trust & Calibration Dashboard**: Real-time Bayesian reputation scores ($\alpha, \beta, \text{Trust} = \frac{\alpha}{\alpha + \beta}$) and Dawid-Skene calibration.
3. **Daily Notes & Autonomous Micro-Consolidation ("Agentic Sleep")**:
   - Built-in Markdown daily note editor with date switcher.
   - **"Suck into GMS"**: Triggers `harvest.py` micro-consolidation, extracting candidate facts, validating contracts, extracting bi-temporal knowledge graph triples, updating vector embeddings in `gms_embeddings`, and awarding agent trust.
4. **Bi-Temporal Knowledge Graph**:
   - Interactive force-directed network visualization (`vis-network`).
   - Point-in-time "As Of" time travel and active vs historical invalidation filtering.
5. **Concepts & Entity Extraction**:
   - Grouped catalog of extracted entities (Infrastructure, Tickers, Models, Agents, Policies).
   - Live Extraction Scratchpad to test entity extraction on arbitrary text.
6. **Apple Reminders Integration (Safe Mode)**:
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
