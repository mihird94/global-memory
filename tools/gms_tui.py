#!/usr/bin/env python3
from __future__ import annotations

import curses
import json
import os
import sqlite3
import sys
from pathlib import Path


MEM_ROOT = Path(os.environ.get("MEMORY_ROOT", "/home/mihir/memories"))
DB_PATH = MEM_ROOT / "gms_trust.sqlite"
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import gms_inspect
import memory_mcp_server


def _safe_json(text: str) -> list | dict:
    try:
        return json.loads(text)
    except Exception:
        return []


def load_dashboard_data(claim_limit: int = 50) -> dict:
    old_inspect_root = gms_inspect.MEM_ROOT
    old_inspect_db = gms_inspect.DB_PATH
    try:
        gms_inspect.MEM_ROOT = MEM_ROOT
        gms_inspect.DB_PATH = DB_PATH
        snapshot = gms_inspect.build_snapshot()
    finally:
        gms_inspect.MEM_ROOT = old_inspect_root
        gms_inspect.DB_PATH = old_inspect_db

    quarantines = _safe_json(memory_mcp_server.tool_mem_get_quarantine({}))
    if isinstance(quarantines, list):
        for q in quarantines:
            if "key" in q and "fact_key" not in q:
                q["fact_key"] = q["key"]
    else:
        quarantines = []

    reputations = _safe_json(memory_mcp_server.tool_mem_get_reputations({}))
    retention = _safe_json(memory_mcp_server.tool_mem_retention_report({}))
    calibration = _safe_json(memory_mcp_server.tool_mem_calibration_report({}))

    claims = []
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT claim_id, memory_kind, memory_key, value, agent_id, branch, status, confidence, contradiction_type, created_at
                FROM gms_claims
                ORDER BY claim_id DESC
                LIMIT ?
                """,
                (claim_limit,),
            )
            rows = cursor.fetchall()
            claims = [
                {
                    "claim_id": row[0],
                    "memory_kind": row[1],
                    "memory_key": row[2],
                    "value": row[3],
                    "agent_id": row[4],
                    "branch": row[5],
                    "status": row[6],
                    "confidence": row[7],
                    "contradiction_type": row[8],
                    "created_at": row[9],
                }
                for row in rows
            ]
        except sqlite3.OperationalError:
            claims = []
        conn.close()

    return {
        "snapshot": snapshot,
        "quarantines": quarantines,
        "reputations": reputations if isinstance(reputations, list) else [],
        "retention": retention if isinstance(retention, dict) else {},
        "calibration": calibration if isinstance(calibration, dict) else {},
        "claims": claims,
    }


def resolve_quarantine_item(item: dict, action: str, resolver: str = "TUI") -> str:
    return memory_mcp_server.tool_mem_resolve_quarantine({
        "key": item["fact_key"],
        "agent_id": item["agent_id"],
        "action": action,
        "agent": resolver,
    })


def review_quarantine_item(item: dict, rating: str, reviewer: str = "TUI", rationale: str = "") -> str:
    return memory_mcp_server.tool_mem_record_review({
        "key": item["fact_key"],
        "agent_id": item["agent_id"],
        "reviewer_id": reviewer,
        "rating": rating,
        "rationale": rationale,
    })


def filter_items(items: list[dict], query: str) -> list[dict]:
    if not query:
        return items
    query_lower = query.lower()
    
    if ":" in query_lower:
        parts = query_lower.split(":", 1)
        prefix = parts[0].strip()
        val = parts[1].strip()
        if prefix == "agent":
            return [item for item in items if val in str(item.get("agent_id", "")).lower()]
        elif prefix == "branch":
            return [item for item in items if val in str(item.get("branch", "")).lower()]
        elif prefix in ("key", "project"):
            return [
                item for item in items 
                if val in str(item.get("fact_key", item.get("key", item.get("memory_key", "")))).lower()
            ]
        elif prefix == "kind":
            return [item for item in items if val in str(item.get("memory_kind", "")).lower()]
        elif prefix == "status":
            return [item for item in items if val in str(item.get("status", "")).lower()]
            
    results = []
    for item in items:
        fields = [
            str(item.get("agent_id", "")),
            str(item.get("branch", "")),
            str(item.get("fact_key", item.get("key", item.get("memory_key", "")))),
            str(item.get("value", "")),
            str(item.get("memory_kind", "")),
            str(item.get("status", ""))
        ]
        if any(query_lower in f.lower() for f in fields):
            results.append(item)
    return results


def get_quarantine_detail(item: dict) -> dict:
    key = item.get("fact_key") or item.get("key") or ""
    agent_id = item.get("agent_id", "")
    kind, real_key = memory_mcp_server.parse_prov_key(key)
    
    try:
        proposing_agent_trust = memory_mcp_server.get_agent_trust(agent_id)
    except Exception:
        proposing_agent_trust = 0.5
        
    try:
        rec_summary = _safe_json(memory_mcp_server.tool_mem_get_recommendation_summary({
            "key": key,
            "agent_id": agent_id,
        }))
    except Exception:
        rec_summary = {}
        
    try:
        reviews = memory_mcp_server.get_quarantine_reviews(key, agent_id)
    except Exception:
        reviews = []
        
    conflicting_claim = None
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT claim_id, value, agent_id, branch, confidence, created_at
                FROM gms_claims
                WHERE memory_kind = ? AND memory_key = ? AND status = 'active'
                ORDER BY claim_id DESC
                LIMIT 1
                """,
                (kind, real_key),
            )
            row = cursor.fetchone()
            if row:
                conflicting_claim = {
                    "claim_id": row[0],
                    "value": row[1],
                    "agent_id": row[2],
                    "branch": row[3],
                    "confidence": row[4],
                    "created_at": row[5],
                }
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
            
    return {
        "item": item,
        "proposing_agent_trust": proposing_agent_trust,
        "recommendation": rec_summary,
        "reviews": reviews,
        "conflicting_claim": conflicting_claim,
    }


def get_claim_detail(claim: dict) -> dict:
    kind = claim.get("memory_kind", "")
    key = claim.get("memory_key", "")
    claim_id = claim.get("claim_id")
    
    history = []
    if DB_PATH.exists() and kind and key:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT claim_id, value, agent_id, branch, status, confidence, contradiction_type, created_at
                FROM gms_claims
                WHERE memory_kind = ? AND memory_key = ? AND claim_id != ?
                ORDER BY claim_id DESC
                """,
                (kind, key, claim_id),
            )
            rows = cursor.fetchall()
            history = [
                {
                    "claim_id": row[0],
                    "value": row[1],
                    "agent_id": row[2],
                    "branch": row[3],
                    "status": row[4],
                    "confidence": row[5],
                    "contradiction_type": row[6],
                    "created_at": row[7],
                }
                for row in rows
            ]
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()
            
    return {
        "claim": claim,
        "history": history,
    }


def format_quarantine_detail_lines(detail: dict, width: int) -> list[str]:
    item = detail["item"]
    key = item.get("fact_key") or item.get("key") or ""
    val = item.get("value", "")
    agent = item.get("agent_id", "")
    branch = item.get("branch", "")
    ts = item.get("timestamp", "")
    trust = detail["proposing_agent_trust"]
    rec = detail["recommendation"]
    reviews = detail["reviews"]
    conflict = detail["conflicting_claim"]
    
    lines = [
        "=== QUARANTINE DETAIL VIEW ===",
        f"Key:        {key}",
        f"Value:      {val}",
        f"Agent ID:   {agent} (Trust: {trust:.3f})",
        f"Branch:     {branch}",
        f"Timestamp:  {ts}",
        "",
        "--- Recommendation ---",
        f"Outcome:    {rec.get('recommendation', 'neutral')} (Score: {rec.get('score', 0.5)})",
        f"Weights:    endorse={rec.get('endorse_weight', 0.0)} reject={rec.get('reject_weight', 0.0)} abstain={rec.get('abstain_weight', 0.0)}",
        "",
    ]
    
    if conflict:
        lines.extend([
            "--- Conflicting Active Fact ---",
            f"Active Val: {conflict['value']}",
            f"Set by:     {conflict['agent_id']} (Confidence: {conflict['confidence']:.2f}) on branch '{conflict['branch']}'",
            f"Created:    {conflict['created_at']}",
            "",
        ])
    else:
        lines.extend([
            "--- Conflicting Active Fact ---",
            "No active fact exists with this key.",
            "",
        ])
        
    lines.append("--- Reviews ---")
    if not reviews:
        lines.append("No reviews recorded yet.")
    for idx, rev in enumerate(reviews):
        lines.append(f"[{idx+1}] Reviewer: {rev['reviewer_id']} ({rev['rating'].upper()}) - trust={rev['trust']:.3f} @ {rev['timestamp']}")
        if rev.get("rationale"):
            lines.append(f"    Rationale: {rev['rationale']}")
            
    return lines


def format_claim_detail_lines(detail: dict, width: int) -> list[str]:
    claim = detail["claim"]
    history = detail["history"]
    
    conf = "n/a" if claim["confidence"] is None else f"{claim['confidence']:.2f}"
    lines = [
        "=== CLAIM DETAIL VIEW ===",
        f"Claim ID:      #{claim['claim_id']}",
        f"Key:           {claim['memory_kind']}:{claim['memory_key']}",
        f"Value:         {claim['value']}",
        f"Agent ID:      {claim['agent_id']}",
        f"Status:        {claim['status'].upper()}",
        f"Confidence:    {conf}",
        f"Contradiction: {claim['contradiction_type'] or 'none'}",
        f"Created At:    {claim['created_at']}",
        "",
        "--- Key History (Other Claims) ---",
    ]
    
    if not history:
        lines.append("No other claims found for this key.")
    for idx, hist in enumerate(history):
        h_conf = "n/a" if hist["confidence"] is None else f"{hist['confidence']:.2f}"
        lines.append(
            f"#{hist['claim_id']} [{hist['status']}] val={hist['value']} by {hist['agent_id']} "
            f"conf={h_conf} contra={hist['contradiction_type'] or 'none'} @ {hist['created_at']}"
        )
        
    return lines


def format_selected_claim_detail(claim: dict, width: int) -> list[str]:
    if not claim:
        return ["No claim selected."]
    conf = "n/a" if claim.get("confidence") is None else f"{claim['confidence']:.2f}"
    lines = [
        "--- Selected Claim Detail ---",
        f"ID:          #{claim.get('claim_id')}",
        f"Key:         {claim.get('memory_kind')}:{claim.get('memory_key')}",
        f"Value:       {claim.get('value')}",
        f"Agent:       {claim.get('agent_id')} (Branch: {claim.get('branch')})",
        f"Status:      {str(claim.get('status')).upper()}",
        f"Confidence:  {conf}",
        f"Conflict:    {claim.get('contradiction_type') or 'none'}",
        f"Created:     {claim.get('created_at')}",
    ]
    return lines


def compute_tab_regions(tab_names: tuple[str, ...] | list[str]) -> list[dict]:
    regions = []
    x = len("GMS TUI  ")
    for idx, name in enumerate(tab_names):
        label = f"[{name}]"
        regions.append({
            "index": idx,
            "name": name,
            "x_start": x,
            "x_end": x + len(label) - 1,
        })
        x += len(label)
        if idx < len(tab_names) - 1:
            x += len(" | ")
    return regions


def find_tab_index_at_x(x: int, tab_regions: list[dict]) -> int | None:
    for region in tab_regions:
        if region["x_start"] <= x <= region["x_end"]:
            return int(region["index"])
    return None


def find_list_index_at_y(y: int, row_start: int, visible_count: int, start_idx: int = 0) -> int | None:
    if y < row_start or y >= row_start + visible_count:
        return None
    return start_idx + (y - row_start)



class GMSTui:
    TABS = ("Summary", "Quarantine", "Trust", "Claims")

    def __init__(self):
        self.tab_index = 0
        self.selection = 0
        self.detail_mode = False
        self.detail_scroll = 0
        self.filter_query = ""
        self.status = "r refresh | tab switch | q quit | f filter | c clear"
        self.data = load_dashboard_data()
        self.tab_regions: list[dict] = []
        self.list_row_start = 0
        self.list_visible_count = 0
        self.list_start_idx = 0

    def refresh(self):
        self.data = load_dashboard_data()
        self.selection = 0
        self.detail_mode = False
        self.detail_scroll = 0
        self.status = "Data refreshed."

    def run(self, stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        try:
            curses.mousemask(curses.BUTTON1_CLICKED)
            curses.mouseinterval(0)
        except curses.error:
            pass
        while True:
            self._draw(stdscr)
            key = stdscr.getch()
            
            # Handle quit or exit detail view
            if key == ord("q"):
                if self.detail_mode:
                    self.detail_mode = False
                    self.detail_scroll = 0
                    self.status = "Returned to list."
                else:
                    break
            elif key == 27:  # Esc
                if self.detail_mode:
                    self.detail_mode = False
                    self.detail_scroll = 0
                    self.status = "Returned to list."
                else:
                    break
            elif key in (ord("\t"), curses.KEY_RIGHT, ord("l")) and not self.detail_mode:
                self.tab_index = (self.tab_index + 1) % len(self.TABS)
                self.selection = 0
                self.detail_mode = False
                self.detail_scroll = 0
            elif key in (curses.KEY_LEFT, ord("h")) and not self.detail_mode:
                self.tab_index = (self.tab_index - 1) % len(self.TABS)
                self.selection = 0
                self.detail_mode = False
                self.detail_scroll = 0
            elif key in (curses.KEY_DOWN, ord("j")):
                if self.detail_mode:
                    self.detail_scroll += 1
                else:
                    self.selection += 1
            elif key in (curses.KEY_UP, ord("k")):
                if self.detail_mode:
                    self.detail_scroll = max(0, self.detail_scroll - 1)
                else:
                    self.selection = max(0, self.selection - 1)
            elif key == ord("r") and not self.detail_mode:
                self.refresh()
            elif key == ord("f") and not self.detail_mode:
                self.filter_query = self._prompt(stdscr, "Filter (e.g. agent:name, branch:name, key:kw, or query): ")
                self.selection = 0
                self.status = f"Filter applied: '{self.filter_query}'"
            elif key == ord("c") and not self.detail_mode:
                self.filter_query = ""
                self.selection = 0
                self.status = "Filter cleared."
            elif key in (10, 13, curses.KEY_ENTER):
                tab = self.TABS[self.tab_index]
                if tab in ("Quarantine", "Claims"):
                    self.detail_mode = not self.detail_mode
                    self.detail_scroll = 0
                    self.status = "Detail view opened." if self.detail_mode else "Returned to list."
            elif key == curses.KEY_MOUSE:
                self._handle_mouse()
            elif self.TABS[self.tab_index] == "Quarantine":
                if key == ord("p"):
                    self._act_on_quarantine("promote")
                elif key == ord("d"):
                    self._act_on_quarantine("discard")
                elif key == ord("e"):
                    self._review_quarantine("endorse", stdscr)
                elif key == ord("x"):
                    self._review_quarantine("reject", stdscr)
                elif key == ord("a"):
                    self._review_quarantine("abstain", stdscr)

    def _current_quarantine(self) -> dict | None:
        items = filter_items(self.data["quarantines"], self.filter_query)
        if not items:
            return None
        self.selection = max(0, min(self.selection, len(items) - 1))
        return items[self.selection]

    def _current_claim(self) -> dict | None:
        claims = filter_items(self.data["claims"], self.filter_query)
        if not claims:
            return None
        self.selection = max(0, min(self.selection, len(claims) - 1))
        return claims[self.selection]

    def _act_on_quarantine(self, action: str):
        item = self._current_quarantine()
        if item is None:
            self.status = "No quarantine item selected."
            return
        res = resolve_quarantine_item(item, action)
        self.status = res.splitlines()[0]
        self.detail_mode = False
        self.refresh()

    def _review_quarantine(self, rating: str, stdscr):
        item = self._current_quarantine()
        if item is None:
            self.status = "No quarantine item selected."
            return
        rationale = self._prompt(stdscr, f"{rating} rationale (optional): ")
        res = review_quarantine_item(item, rating, rationale=rationale)
        self.status = res.splitlines()[0]
        self.detail_mode = False
        self.refresh()

    def _prompt(self, stdscr, label: str) -> str:
        height, width = stdscr.getmaxyx()
        curses.echo()
        curses.curs_set(1)
        stdscr.move(height - 1, 0)
        stdscr.clrtoeol()
        stdscr.addnstr(height - 1, 0, label, width - 1)
        stdscr.refresh()
        raw = stdscr.getstr(height - 1, min(len(label), max(0, width - 1)), max(1, width - len(label) - 1))
        curses.noecho()
        curses.curs_set(0)
        return raw.decode("utf-8", "replace").strip()

    def _handle_mouse(self):
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return
        if not (bstate & curses.BUTTON1_CLICKED):
            return

        if my == 0:
            tab_index = find_tab_index_at_x(mx, self.tab_regions)
            if tab_index is not None:
                self.tab_index = tab_index
                self.selection = 0
                self.detail_mode = False
                self.detail_scroll = 0
                self.status = f"Switched to {self.TABS[self.tab_index]}."
            return

        if self.detail_mode:
            self.detail_mode = False
            self.detail_scroll = 0
            self.status = "Returned to list."
            return

        if self.TABS[self.tab_index] not in ("Quarantine", "Claims"):
            return

        selected_index = find_list_index_at_y(
            my,
            self.list_row_start,
            self.list_visible_count,
            self.list_start_idx,
        )
        if selected_index is None:
            return
        self.selection = selected_index
        self.status = "Selection updated."

    def _draw(self, stdscr):
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        self.tab_regions = compute_tab_regions(self.TABS)
        tab_line = " | ".join(
            f"[{name}]" if idx == self.tab_index else name
            for idx, name in enumerate(self.TABS)
        )
        stdscr.addnstr(0, 0, f"GMS TUI  {tab_line}", width - 1, curses.A_BOLD)
        stdscr.hline(1, 0, "-", max(0, width - 1))
        
        tab = self.TABS[self.tab_index]
        if self.detail_mode:
            self._draw_detail(stdscr, 2, width, height)
        else:
            if tab == "Summary":
                self._draw_summary(stdscr, 2, width, height)
            elif tab == "Quarantine":
                self._draw_quarantine(stdscr, 2, width, height)
            elif tab == "Trust":
                self._draw_trust(stdscr, 2, width, height)
            else:
                self._draw_claims(stdscr, 2, width, height)
                
        stdscr.hline(height - 2, 0, "-", max(0, width - 1))
        stdscr.addnstr(height - 1, 0, self.status, width - 1)
        stdscr.refresh()

    def _draw_detail(self, stdscr, row: int, width: int, height: int):
        tab = self.TABS[self.tab_index]
        lines = []
        if tab == "Quarantine":
            selected = self._current_quarantine()
            if selected:
                detail = get_quarantine_detail(selected)
                lines = format_quarantine_detail_lines(detail, width)
            else:
                lines = ["No quarantine item selected."]
        elif tab == "Claims":
            selected = self._current_claim()
            if selected:
                detail = get_claim_detail(selected)
                lines = format_claim_detail_lines(detail, width)
            else:
                lines = ["No claim selected."]
        else:
            lines = ["Detail view not supported for this tab."]
            
        max_lines = max(0, height - row - 2)
        self.detail_scroll = max(0, min(self.detail_scroll, max(0, len(lines) - max_lines)))
        visible_lines = lines[self.detail_scroll : self.detail_scroll + max_lines]
        for idx, line in enumerate(visible_lines):
            stdscr.addnstr(row + idx, 0, line, width - 1)

    def _draw_summary(self, stdscr, row: int, width: int, height: int):
        self.list_row_start = 0
        self.list_visible_count = 0
        self.list_start_idx = 0
        snap = self.data["snapshot"]
        db = snap["db"]
        retention = self.data["retention"].get("summary", {})
        calibration = self.data["calibration"]
        lines = [
            f"Memory root: {snap['memory_root']}",
            f"Facts: semantic={snap['facts']['semantic']} operational={snap['facts']['operational']} procedural={snap['facts']['procedural']}",
            f"Episodes: count={snap['episodes']['count']}",
            f"Claims by status: {db['claims_by_status']}",
            f"Quarantine: facts={db['quarantined_facts']} reviews={db['quarantine_reviews']}",
            f"Graph: entities={db['entities']} relationships={db['relationships']} procedures={db['procedures']}",
            f"Retention candidates: active={retention.get('active_claim_candidates', 0)} quarantine={retention.get('quarantine_candidates', 0)}",
            f"Calibration: model={calibration.get('model', 'n/a')} overlap={calibration.get('overlapping_keys_count', 0)} converged={calibration.get('converged', False)}",
            "",
            "Recent quarantine items:",
        ]
        for item in snap.get("quarantine", {}).get("recent", []):
            lines.append(f"- {item['fact_key']} by {item['agent_id']} @ {item['timestamp']}")
        self._draw_lines(stdscr, row, width, height, lines)

    def _draw_quarantine(self, stdscr, row: int, width: int, height: int):
        items = filter_items(self.data["quarantines"], self.filter_query)
        header = "Quarantine: j/k move | Enter view | p promote | d discard | e endorse | x reject | a abstain | f filter | c clear"
        stdscr.addnstr(row, 0, header, width - 1, curses.A_BOLD)
        if self.filter_query:
            stdscr.addnstr(row + 1, 0, f"Filter active: '{self.filter_query}'", width - 1, curses.A_REVERSE)
            row_offset = 3
        else:
            row_offset = 2
            
        if not items:
            self.list_row_start = 0
            self.list_visible_count = 0
            self.list_start_idx = 0
            stdscr.addnstr(row + row_offset, 0, "No quarantined facts.", width - 1)
            return
            
        self.selection = max(0, min(self.selection, len(items) - 1))
        visible_count = max(1, height - row - row_offset - 4)
        start_idx = 0
        if self.selection >= visible_count:
            start_idx = self.selection - visible_count + 1
        visible = items[start_idx : start_idx + visible_count]
        self.list_row_start = row + row_offset
        self.list_visible_count = len(visible)
        self.list_start_idx = start_idx
        for idx, item in enumerate(visible):
            actual_idx = start_idx + idx
            marker = ">" if actual_idx == self.selection else " "
            key = item.get("fact_key") or item.get("key") or ""
            line = f"{marker} {key} | {item['agent_id']} | {item['branch']} | {item['timestamp']}"
            attr = curses.A_REVERSE if actual_idx == self.selection else curses.A_NORMAL
            stdscr.addnstr(row + row_offset + idx, 0, line, width - 1, attr)
            
        selected = self._current_quarantine()
        if selected:
            summary = _safe_json(memory_mcp_server.tool_mem_get_recommendation_summary({
                "key": selected.get("fact_key") or selected.get("key") or "",
                "agent_id": selected["agent_id"],
            }))
            detail = (
                f"Recommendation={summary.get('recommendation', 'n/a')} "
                f"score={summary.get('score', 'n/a')} "
                f"endorse={summary.get('endorse_weight', 'n/a')} "
                f"reject={summary.get('reject_weight', 'n/a')}"
            )
            stdscr.addnstr(height - 4, 0, detail, width - 1)

    def _draw_trust(self, stdscr, row: int, width: int, height: int):
        self.list_row_start = 0
        self.list_visible_count = 0
        self.list_start_idx = 0
        reps = sorted(self.data["reputations"], key=lambda item: item.get("trust_score", 0.0), reverse=True)
        lines = ["Agent trust state:"]
        for rep in reps[: max(1, height - row - 3)]:
            lines.append(
                f"{rep['agent_id']:<24} trust={rep['trust_score']:.3f} alpha={rep['alpha']:.2f} beta={rep['beta']:.2f}"
            )
        self._draw_lines(stdscr, row, width, height, lines)

    def _draw_claims(self, stdscr, row: int, width: int, height: int):
        claims = filter_items(self.data["claims"], self.filter_query)
        header = "Claims: j/k move | Enter view | f filter | c clear"
        stdscr.addnstr(row, 0, header, width - 1, curses.A_BOLD)
        if self.filter_query:
            stdscr.addnstr(row + 1, 0, f"Filter active: '{self.filter_query}'", width - 1, curses.A_REVERSE)
            row_offset = 3
        else:
            row_offset = 2
            
        if not claims:
            self.list_row_start = 0
            self.list_visible_count = 0
            self.list_start_idx = 0
            stdscr.addnstr(row + row_offset, 0, "No claims matched.", width - 1)
            return
            
        self.selection = max(0, min(self.selection, len(claims) - 1))
        
        selected = self._current_claim()
        detail_lines = format_selected_claim_detail(selected, width) if selected else []
        
        if height > row + row_offset + len(detail_lines) + 2:
            list_height = height - row - row_offset - len(detail_lines) - 2
            list_height = max(1, list_height)
        else:
            list_height = max(1, height - row - row_offset - 2)
            detail_lines = []
            
        start_idx = 0
        if self.selection >= list_height:
            start_idx = self.selection - list_height + 1
        visible = claims[start_idx : start_idx + list_height]
        self.list_row_start = row + row_offset
        self.list_visible_count = len(visible)
        self.list_start_idx = start_idx
        
        for idx, claim in enumerate(visible):
            actual_idx = start_idx + idx
            marker = ">" if actual_idx == self.selection else " "
            conf = "n/a" if claim["confidence"] is None else f"{claim['confidence']:.2f}"
            line = f"{marker} #{claim['claim_id']} {claim['memory_kind']}:{claim['memory_key']} [{claim['status']}] {claim['agent_id']} conf={conf}"
            attr = curses.A_REVERSE if actual_idx == self.selection else curses.A_NORMAL
            stdscr.addnstr(row + row_offset + idx, 0, line, width - 1, attr)
            
        if detail_lines:
            detail_start_row = height - len(detail_lines) - 2
            for idx, line in enumerate(detail_lines):
                stdscr.addnstr(detail_start_row + idx, 0, line, width - 1)


    @staticmethod
    def _draw_lines(stdscr, row: int, width: int, height: int, lines: list[str]):
        max_lines = max(0, height - row - 2)
        for idx, line in enumerate(lines[:max_lines]):
            stdscr.addnstr(row + idx, 0, line, width - 1)


def main() -> int:
    app = GMSTui()
    curses.wrapper(app.run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
