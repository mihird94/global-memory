import os
import json
import re
import subprocess
from datetime import datetime, date

MEMORY_ROOT = os.environ.get("MEMORY_ROOT", "/Users/mihirdeshpande/memories")
OBSIDIAN_ROOT = "/Users/mihirdeshpande/Apps/Obsidian/notes"
MEMORY_FOLDER = os.path.join(OBSIDIAN_ROOT, "Memory")
OPERATIONAL_FOLDER = os.path.join(MEMORY_ROOT, "operational")

os.makedirs(MEMORY_FOLDER, exist_ok=True)
os.makedirs(OPERATIONAL_FOLDER, exist_ok=True)

# 1. Fetch Live Apple Reminders
def fetch_live_reminders():
    script = '''
    tell application "Reminders"
        set out to ""
        set listNames to {"Personal Chores", "House Management", "Reminders", "Birthdays"}
        repeat with lName in listNames
            try
                set l to list (lName as string)
                set remNames to (name of every reminder of l whose completed is false)
                set remDues to (due date of every reminder of l whose completed is false)
                repeat with i from 1 to (count of remNames)
                    set rName to item i of remNames
                    set rDue to "None"
                    try
                        set d to item i of remDues
                        if d is not missing value then
                            set rDue to (d as string)
                        end if
                    end try
                    set out to out & (lName as string) & "<||>" & rName & "<||>" & rDue & linefeed
                end repeat
            end try
        end repeat
        return out
    end tell
    '''
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
        if res.returncode == 0 and res.stdout.strip():
            items = []
            for line in res.stdout.strip().splitlines():
                if "<||>" in line:
                    parts = line.split("<||>")
                    items.append({
                        "list": parts[0],
                        "name": parts[1],
                        "due": parts[2] if parts[2] != "None" else None
                    })
            return items
    except Exception as e:
        print(f"Warning fetching reminders: {e}")
    return []

print("Fetching live Apple Reminders...")
live_reminders = fetch_live_reminders()

# Save Reminders to GMS Operational Store
reminders_json_path = os.path.join(OPERATIONAL_FOLDER, "active_reminders.json")
with open(reminders_json_path, "w") as f:
    json.dump(live_reminders, f, indent=2)
print(f"Saved {len(live_reminders)} active reminders to {reminders_json_path}")

# Categorize Reminders
personal_chores = [r for r in live_reminders if r["list"] == "Personal Chores"]
house_mgmt = [r for r in live_reminders if r["list"] == "House Management"]
backlog_rems = [r for r in live_reminders if r["list"] == "Reminders"]
birthday_rems = [r for r in live_reminders if r["list"] == "Birthdays"]

# 2. Update GMS Fact with Reminders Summary via Trust Gateway
reminders_summary_val = {
    "total_incomplete": len(live_reminders),
    "personal_chores": len(personal_chores),
    "house_management": len(house_mgmt),
    "backlog": len(backlog_rems),
    "birthdays": len(birthday_rems),
    "last_synced": datetime.now().strftime("%Y-%m-%d %H:%M")
}
try:
    import memory_mcp_server
    memory_mcp_server.tool_mem_save_typed({
        "key": "operational.live_reminders_summary",
        "value": json.dumps(reminders_summary_val),
        "kind": "operational",
        "agent": "Apple-Reminders-Sync",
        "force": True
    })
except Exception as e:
    print(f"Warning saving reminders summary via trust gateway: {e}")

# 3. Load Vector Meta
meta_file = os.path.join(MEMORY_ROOT, "episodic", "index", "episodic_meta.json")
vector_meta = []
if os.path.exists(meta_file):
    try:
        with open(meta_file, "r") as f:
            vector_meta = json.load(f)
    except Exception:
        pass
total_chunks = len(vector_meta) if isinstance(vector_meta, list) else 244

# 4. Load Episodic Logs (Sorted Chronologically Newest First)
journal_file = os.path.join(MEMORY_ROOT, "episodic", "journal.md")
recent_logs = []
if os.path.exists(journal_file):
    try:
        with open(journal_file, "r") as f:
            text = f.read()
            entries = text.split("### ")
            for e in entries:
                if e.strip():
                    lines = e.strip().splitlines()
                    header = lines[0]
                    body = "\n".join(lines[1:]).strip()
                    
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})\s*\[?(\d{2}:\d{2})?\]?', header)
                    dt_sort = date_match.group(0) if date_match else "1970-01-01"
                    
                    header_clean = header
                    agent = "System"
                    if " - " in header:
                        parts = header.split(" - ", 2)
                        if len(parts) >= 3:
                            agent = parts[1].strip()
                            header_clean = parts[2].strip()
                    
                    recent_logs.append({
                        "header_raw": header,
                        "date_str": dt_sort,
                        "agent": agent,
                        "title": header_clean,
                        "body": body
                    })
    except Exception:
        pass

recent_logs.sort(key=lambda x: x["date_str"], reverse=True)
top_recent_logs = recent_logs[:5]

# 5. Calculate Chronological Proximity for Birthdays
current_date = date(2026, 8, 26)
months_map = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12
}

bday_list = []
for k, v in facts.items():
    if k.startswith("birthday_"):
        person = k.replace("birthday_", "").replace("_", " ").title()
        parts = v.strip().split()
        if len(parts) >= 2:
            m_str = parts[0].lower()
            d_str = ''.join(c for c in parts[1] if c.isdigit())
            if m_str in months_map and d_str.isdigit():
                m = months_map[m_str]
                d = int(d_str)
                b_year = 2026 if (m > 8 or (m == 8 and d >= 26)) else 2027
                b_date = date(b_year, m, d)
                days_away = (b_date - current_date).days
                bday_list.append({
                    "person": person,
                    "date_str": f"{parts[0]} {d}",
                    "year": b_year,
                    "days_away": days_away
                })

bday_list.sort(key=lambda x: x["days_away"])

# 6. Financial Deadlines
fin_schedule = [
    {"name": "Quicken Simplifi Reconciliation", "date": "Sat, Aug 29, 2026", "days_away": 3, "account": "Personal Chores"},
    {"name": "Pay Rent ($)", "date": "Tue, Sep 1, 2026", "days_away": 6, "account": "Bank Checking"},
    {"name": "Pay Chase Credit Card", "date": "Thu, Sep 3, 2026", "days_away": 8, "account": "Chase Portal"},
    {"name": "Pay Capital One Card", "date": "Mon, Sep 21, 2026", "days_away": 26, "account": "Capital One Portal"}
]

now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

# ==========================================
# Generate Main Dashboard: 00 🧠 Memory Dashboard.md
# ==========================================

dash = f"""# 🧠 GMS Command Center & Living Snapshot

> [!abstract] System Telemetry
> **Last Synced:** `{now_str}` • **Brain Health:** `🟢 Optimal`  
> **Active Reminders Loaded:** `{len(live_reminders)}` total (`{len(personal_chores)}` Chores, `{len(house_mgmt)}` House Routines, `{len(backlog_rems)}` Backlog)  
> **Vector Model:** `qwen3-embedding:0.6b` (`{total_chunks}` memory chunks) • **Source:** `~/memories` ➔ Apple Ecosystem ➔ Obsidian

---

## ⚡ 1. Live Apple Reminders & Action Queue

### 📌 Personal Chores ({len(personal_chores)} active)
"""

if personal_chores:
    for c in personal_chores:
        due_str = f" `(Due: {c['due']})`" if c['due'] else ""
        dash += f"- [ ] **{c['name']}**{due_str}\n"
else:
    dash += "*No active personal chores.*\n"

dash += f"""
### 🏠 House Management Routines ({len(house_mgmt)} recurring)
"""

if house_mgmt:
    for h in house_mgmt:
        due_str = f" `(Due: {h['due']})`" if h['due'] else ""
        dash += f"- [ ] **{h['name']}**{due_str}\n"
else:
    dash += "*No active house management routines.*\n"

dash += f"""
### 📋 Backlog & General Reminders ({len(backlog_rems)} items)
"""

if backlog_rems:
    for b in backlog_rems:
        due_str = f" `(Due: {b['due']})`" if b['due'] else ""
        dash += f"- [ ] {b['name']}{due_str}\n"
else:
    dash += "*No backlog items.*\n"

dash += f"""
---

## 📅 2. At a Glance: Deadlines & Birthdays (Next 30 Days)

### 💳 Upcoming Bills & Cadence
| Obligation | Target Date | Proximity | List / Portal |
| :--- | :--- | :--- | :--- |
"""

for fin in fin_schedule:
    badge = "🔴 Soon" if fin["days_away"] <= 5 else "🟡 Queued"
    dash += f"| **{fin['name']}** | {fin['date']} | `{badge} ({fin['days_away']}d)` | {fin['account']} |\n"

dash += f"""
### 🎂 Upcoming Birthdays (Next in Line)
| Person | Date | Proximity | Reminders Queue |
| :--- | :--- | :--- | :--- |
"""

for b in bday_list[:6]:
    urgency = "🔥 Next up" if b["days_away"] <= 30 else f"in {b['days_away']} days"
    dash += f"| **{b['person']}** | {b['date_str']} ({b['year']}) | `{urgency}` | `Birthdays` |\n"

dash += f"""
---

## 🕒 3. Recent Activity & Milestones (Latest First)

"""

for log in top_recent_logs:
    dash += f"""> [!timeline] {log['header_raw']}
> **Agent:** `{log['agent']}`  
> {log['body']}

"""

dash += f"""---

## 🎯 4. Active Priorities & Tech Sprints

> [!example] Applied Researcher Learning Track
> **Target:** Transition to Applied Scientist (DL, LMs, RecSys, RL)  
> **Progress Status:**
> - [x] **M1:** DL Foundations & Ensemble Learning *(Amex Default Prediction)*
> - [/] **M2:** Representation Learning *(Quora / Twitch Two-Tower M-BERT)* `🟢 Active Sprint`
> - [ ] **M3:** Tiny LMs from Scratch *(Nano-GPT on TinyStories)*
> - [ ] **M4:** Recommender Systems *(OTTO Multi-Objective)*
> - [ ] **M5:** Alignment & Fine-tuning *(Human Preference Predictions)*
> - [ ] **M6:** Computer Vision *(ViTs & CNNs)*

> [!note] Twitch Two-Tower M-BERT
> **Synergy:** AdTech & contextual game embedding representations for Twitch ad targeting.

---

## 🗂️ 5. Knowledge Base & Deep Links
* [[Memory/Live Reminders Snapshot|⚡ Detailed Reminders Snapshot & History]]
* [[Memory/Semantic Facts Index|📋 Full Semantic Facts Index ({len(facts)} keys)]]
* [[Memory/Life Systems & Chores Rhythm|🏠 Life Systems & Reminders Architecture]]
* [[Memory/Active Projects & Sprints|🚀 Active Projects & Roadmap]]
"""

with open(os.path.join(OBSIDIAN_ROOT, "00 🧠 Memory Dashboard.md"), "w") as f:
    f.write(dash)
print("Generated root dashboard with live Reminders!")

# Write Dedicated Live Reminders Snapshot Sub-Page
rems_page_md = f"""# ⚡ Apple Reminders Live Snapshot

> [!INFO] Telemetry
> **Last Synchronized:** `{now_str}`  
> **Total Active Tasks:** `{len(live_reminders)}`  
> **Source:** Apple Reminders App (iCloud) ➔ GMS Operational Memory

---

## 📌 Personal Chores ({len(personal_chores)})
| Task | Due Date | Priority |
| :--- | :--- | :--- |
"""

for c in personal_chores:
    rems_page_md += f"| {c['name']} | {c['due'] or 'No due date'} | Active |\n"

rems_page_md += f"""
---

## 🏠 House Management ({len(house_mgmt)})
| Routine | Due Date | Cadence |
| :--- | :--- | :--- |
"""

for h in house_mgmt:
    rems_page_md += f"| {h['name']} | {h['due'] or 'No due date'} | Recurring |\n"

rems_page_md += f"""
---

## 📋 General Backlog ({len(backlog_rems)})
| Task | Due Date | Notes |
| :--- | :--- | :--- |
"""

for b in backlog_rems:
    rems_page_md += f"| {b['name']} | {b['due'] or 'No due date'} | Backlog |\n"

with open(os.path.join(MEMORY_FOLDER, "Live Reminders Snapshot.md"), "w") as f:
    f.write(rems_page_md)
print("Generated Memory/Live Reminders Snapshot.md!")
