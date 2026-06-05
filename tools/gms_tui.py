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
                SELECT claim_id, memory_kind, memory_key, value, agent_id, status, confidence, contradiction_type, created_at
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
                    "status": row[5],
                    "confidence": row[6],
                    "contradiction_type": row[7],
                    "created_at": row[8],
                }
                for row in rows
            ]
        except sqlite3.OperationalError:
            claims = []
        conn.close()

    return {
        "snapshot": snapshot,
        "quarantines": quarantines if isinstance(quarantines, list) else [],
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


class GMSTui:
    TABS = ("Summary", "Quarantine", "Trust", "Claims")

    def __init__(self):
        self.tab_index = 0
        self.selection = 0
        self.status = "r refresh | tab switch | q quit"
        self.data = load_dashboard_data()

    def refresh(self):
        self.data = load_dashboard_data()
        self.selection = 0
        self.status = "Data refreshed."

    def run(self, stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        while True:
            self._draw(stdscr)
            key = stdscr.getch()
            if key in (ord("q"), 27):
                break
            if key in (ord("\t"), curses.KEY_RIGHT, ord("l")):
                self.tab_index = (self.tab_index + 1) % len(self.TABS)
                self.selection = 0
            elif key in (curses.KEY_LEFT, ord("h")):
                self.tab_index = (self.tab_index - 1) % len(self.TABS)
                self.selection = 0
            elif key in (curses.KEY_DOWN, ord("j")):
                self.selection += 1
            elif key in (curses.KEY_UP, ord("k")):
                self.selection = max(0, self.selection - 1)
            elif key == ord("r"):
                self.refresh()
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
        items = self.data["quarantines"]
        if not items:
            return None
        self.selection = max(0, min(self.selection, len(items) - 1))
        return items[self.selection]

    def _act_on_quarantine(self, action: str):
        item = self._current_quarantine()
        if item is None:
            self.status = "No quarantine item selected."
            return
        res = resolve_quarantine_item(item, action)
        self.status = res.splitlines()[0]
        self.refresh()

    def _review_quarantine(self, rating: str, stdscr):
        item = self._current_quarantine()
        if item is None:
            self.status = "No quarantine item selected."
            return
        rationale = self._prompt(stdscr, f"{rating} rationale (optional): ")
        res = review_quarantine_item(item, rating, rationale=rationale)
        self.status = res.splitlines()[0]
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

    def _draw(self, stdscr):
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        tab_line = " | ".join(
            f"[{name}]" if idx == self.tab_index else name
            for idx, name in enumerate(self.TABS)
        )
        stdscr.addnstr(0, 0, f"GMS TUI  {tab_line}", width - 1, curses.A_BOLD)
        stdscr.hline(1, 0, "-", max(0, width - 1))
        tab = self.TABS[self.tab_index]
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

    def _draw_summary(self, stdscr, row: int, width: int, height: int):
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
        items = self.data["quarantines"]
        header = "Quarantine: j/k move | p promote | d discard | e endorse | x reject | a abstain"
        stdscr.addnstr(row, 0, header, width - 1, curses.A_BOLD)
        if not items:
            stdscr.addnstr(row + 2, 0, "No quarantined facts.", width - 1)
            return
        self.selection = max(0, min(self.selection, len(items) - 1))
        visible = items[: max(1, height - row - 4)]
        for idx, item in enumerate(visible):
            marker = ">" if idx == self.selection else " "
            line = f"{marker} {item['fact_key']} | {item['agent_id']} | {item['branch']} | {item['timestamp']}"
            attr = curses.A_REVERSE if idx == self.selection else curses.A_NORMAL
            stdscr.addnstr(row + 2 + idx, 0, line, width - 1, attr)
        selected = self._current_quarantine()
        if selected:
            summary = _safe_json(memory_mcp_server.tool_mem_get_recommendation_summary({
                "key": selected["fact_key"],
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
        reps = sorted(self.data["reputations"], key=lambda item: item.get("trust_score", 0.0), reverse=True)
        lines = ["Agent trust state:"]
        for rep in reps[: max(1, height - row - 3)]:
            lines.append(
                f"{rep['agent_id']:<24} trust={rep['trust_score']:.3f} alpha={rep['alpha']:.2f} beta={rep['beta']:.2f}"
            )
        self._draw_lines(stdscr, row, width, height, lines)

    def _draw_claims(self, stdscr, row: int, width: int, height: int):
        claims = self.data["claims"]
        lines = ["Recent claims:"]
        for claim in claims[: max(1, height - row - 3)]:
            conf = "n/a" if claim["confidence"] is None else f"{claim['confidence']:.2f}"
            lines.append(
                f"#{claim['claim_id']} {claim['memory_kind']}:{claim['memory_key']} "
                f"[{claim['status']}] {claim['agent_id']} conf={conf}"
            )
        self._draw_lines(stdscr, row, width, height, lines)

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
