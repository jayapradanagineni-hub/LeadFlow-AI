#!/usr/bin/env python3
"""LeadFlow: a dependency-free lead qualification and follow-up proof of concept."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("LEADFLOW_DB", ROOT / "leadflow.db"))
OUTBOX_PATH = Path(os.environ.get("LEADFLOW_OUTBOX", ROOT / "outbox.jsonl"))
SERVICES = [
    "AI Lead Qualification & Follow-up Automation",
    "Customer Support Chatbot",
    "Workflow Automation",
    "Data Analytics Dashboard",
]
INTENT_WORDS = ("need", "looking for", "implement", "buy", "urgent", "quote", "deploy", "automate", "interested", "require")
INDUSTRIES = {"healthcare", "finance", "retail", "education", "technology", "manufacturing"}
VALID_EMAIL = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)
VALID_PHONE = re.compile(r"^\+?[0-9][0-9 ()-]{7,18}[0-9]$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_phone(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            company TEXT,
            requirement TEXT NOT NULL,
            budget_inr REAL,
            industry TEXT,
            source TEXT,
            score INTEGER,
            priority TEXT,
            status TEXT NOT NULL,
            reasons_json TEXT NOT NULL DEFAULT '[]',
            pain_point TEXT,
            recommended_service TEXT,
            follow_up TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            event_type TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(lead_id) REFERENCES leads(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            UNIQUE(lead_id)
        )
    """)
    conn.commit()
    return conn


def add_event(conn: sqlite3.Connection, lead_id: int | None, event_type: str, details: str) -> None:
    conn.execute("INSERT INTO events(lead_id,event_type,details,created_at) VALUES(?,?,?,?)",
                 (lead_id, event_type, details, now_iso()))


def validate_lead(lead: dict[str, Any]) -> list[str]:
    reasons = []
    if not str(lead.get("name", "")).strip():
        reasons.append("name is required")
    if not str(lead.get("requirement", "")).strip():
        reasons.append("requirement is required")
    email = normalize_email(lead.get("email"))
    phone = str(lead.get("phone") or "").strip()
    email_ok = bool(email and VALID_EMAIL.match(email))
    phone_ok = bool(phone and VALID_PHONE.match(phone))
    if not email_ok and not phone_ok:
        reasons.append("provide at least one valid email or phone")
    return reasons


def find_duplicate(conn: sqlite3.Connection, lead: dict[str, Any]) -> sqlite3.Row | None:
    email = normalize_email(lead.get("email"))
    phone = normalize_phone(lead.get("phone"))
    company = str(lead.get("company") or "").strip().casefold()
    if email:
        row = conn.execute("SELECT * FROM leads WHERE lower(email)=? AND status='qualified' ORDER BY id LIMIT 1",
                           (email,)).fetchone()
        if row:
            return row
    if phone and company:
        rows = conn.execute("SELECT * FROM leads WHERE status='qualified' AND phone IS NOT NULL").fetchall()
        for row in rows:
            if normalize_phone(row["phone"]) == phone and str(row["company"] or "").strip().casefold() == company:
                return row
    return None


def score_lead(lead: dict[str, Any]) -> tuple[int, str, list[str]]:
    score = 0
    reasons = []
    budget = lead.get("budget_inr")
    try:
        budget = float(budget or 0)
    except (TypeError, ValueError):
        budget = 0
    if budget >= 100000:
        score += 30; reasons.append("Budget ₹100,000 or more (+30)")
    elif budget >= 50000:
        score += 20; reasons.append("Budget ₹50,000–₹99,999 (+20)")
    elif budget >= 20000:
        score += 10; reasons.append("Budget ₹20,000–₹49,999 (+10)")
    else:
        reasons.append("Budget below ₹20,000 or unspecified (+0)")

    requirement = str(lead.get("requirement") or "").casefold()
    matches = [word for word in INTENT_WORDS if word in requirement]
    intent_points = min(30, len(matches) * 5)
    score += intent_points
    reasons.append(f"Purchase-intent wording: {', '.join(matches) if matches else 'none'} (+{intent_points})")

    industry = str(lead.get("industry") or "").strip().casefold()
    if industry in INDUSTRIES:
        score += 15; reasons.append(f"Target industry: {industry} (+15)")
    else:
        reasons.append("Industry not in target list (+0)")

    source = str(lead.get("source") or "").strip().casefold()
    source_points = 10 if source in {"referral", "website demo", "sales enquiry"} else 5 if source else 0
    score += source_points
    reasons.append(f"Lead source: {source or 'unknown'} (+{source_points})")

    contact_points = 0
    if normalize_email(lead.get("email")) and VALID_EMAIL.match(normalize_email(lead.get("email"))):
        contact_points += 5
    if str(lead.get("phone") or "").strip() and VALID_PHONE.match(str(lead.get("phone") or "").strip()):
        contact_points += 5
    if str(lead.get("company") or "").strip():
        contact_points += 5
    score += contact_points
    reasons.append(f"Contact completeness (+{contact_points})")
    score = min(100, max(0, int(score)))
    priority = "Hot" if score >= 70 else "Warm" if score >= 40 else "Cold"
    return score, priority, reasons


def fallback_content(lead: dict[str, Any]) -> dict[str, str]:
    requirement = str(lead.get("requirement") or "").strip()
    lower = requirement.casefold()
    if any(word in lower for word in ("chatbot", "customer support", "support bot")):
        service = "Customer Support Chatbot"
    elif any(word in lower for word in ("dashboard", "analytics", "report")):
        service = "Data Analytics Dashboard"
    elif any(word in lower for word in ("workflow", "automate", "automation")):
        service = "Workflow Automation"
    else:
        service = SERVICES[0]
    name = str(lead.get("name") or "there").strip().split()[0]
    pain = f"Needs help with {requirement.rstrip('.')}."
    message = (f"Hi {name}, thanks for sharing your requirement. We can discuss how "
               f"{service.lower()} could help. Would you be available for a short call this week?")
    return {"pain_point": pain, "recommended_service": service, "follow_up": message}


def claude_content(lead: dict[str, Any]) -> dict[str, str]:
    """Try Claude Messages API twice; return fallback content if unavailable or malformed."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return fallback_content(lead)
    prompt = (
        "Return only valid JSON with keys pain_point, recommended_service, follow_up. "
        f"recommended_service must be exactly one of: {', '.join(SERVICES)}. "
        "Be concise, professional, and do not invent customer facts. Lead: "
        + json.dumps({k: lead.get(k) for k in ("name", "requirement", "industry", "budget_inr")}, ensure_ascii=False)
    )
    payload = json.dumps({
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
        "max_tokens": 350,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        method="POST",
    )
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = json.loads(response.read().decode("utf-8"))
            text = "".join(part.get("text", "") for part in body.get("content", []) if part.get("type") == "text")
            match = re.search(r"\{.*\}", text, re.S)
            result = json.loads(match.group(0)) if match else {}
            if all(isinstance(result.get(k), str) and result[k].strip()
                   for k in ("pain_point", "recommended_service", "follow_up")):
                if result["recommended_service"] not in SERVICES:
                    result["recommended_service"] = SERVICES[0]
                return {k: result[k].strip() for k in ("pain_point", "recommended_service", "follow_up")}
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError):
            if attempt == 0:
                time.sleep(0.3)
    return fallback_content(lead)


def notify_hot_lead(conn: sqlite3.Connection, lead_id: int, name: str, score: int) -> None:
    message = f"HOT LEAD: {name} (score {score}/100; lead ID {lead_id})"
    conn.execute("INSERT OR IGNORE INTO alerts(lead_id,message,status,attempts,created_at) VALUES(?,?, 'pending',0,?)",
                 (lead_id, message, now_iso()))
    conn.commit()
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if webhook:
        send_pending_alerts(conn, webhook=webhook, only_lead_id=lead_id)
    else:
        print(f"[ALERT] {message}")
        with OUTBOX_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"lead_id": lead_id, "message": message, "status": "pending", "created_at": now_iso()}) + "\n")


def send_pending_alerts(conn: sqlite3.Connection, webhook: str | None = None, only_lead_id: int | None = None) -> int:
    webhook = webhook or os.environ.get("SLACK_WEBHOOK_URL")
    rows = conn.execute("SELECT * FROM alerts WHERE status='pending' " +
                        ("AND lead_id=? " if only_lead_id is not None else "") + "ORDER BY id",
                        ((only_lead_id,) if only_lead_id is not None else ())).fetchall()
    sent = 0
    for row in rows:
        conn.execute("UPDATE alerts SET attempts=attempts+1 WHERE id=?", (row["id"],))
        if webhook:
            try:
                req = urllib.request.Request(webhook, data=json.dumps({"text": row["message"]}).encode(),
                                             headers={"content-type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=10) as response:
                    if 200 <= response.status < 300:
                        conn.execute("UPDATE alerts SET status='sent',sent_at=? WHERE id=?", (now_iso(), row["id"]))
                        sent += 1
            except (urllib.error.URLError, TimeoutError, ValueError):
                pass
        conn.commit()
    return sent


def process_one(conn: sqlite3.Connection, lead: dict[str, Any]) -> dict[str, Any]:
    errors = validate_lead(lead)
    if errors:
        details = "; ".join(errors)
        conn.execute("""
            INSERT INTO leads(name,email,phone,company,requirement,budget_inr,industry,source,status,reasons_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (str(lead.get("name") or ""), normalize_email(lead.get("email")) or None,
              str(lead.get("phone") or "") or None, str(lead.get("company") or "") or None,
              str(lead.get("requirement") or ""), lead.get("budget_inr"), lead.get("industry"), lead.get("source"),
              "rejected", json.dumps(errors), now_iso(), now_iso()))
        lead_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        add_event(conn, lead_id, "rejected", details)
        conn.commit()
        print(f"[REJECTED] {lead.get('name') or '(no name)'}: {details}")
        return {"status": "rejected", "id": lead_id, "reasons": errors}

    duplicate = find_duplicate(conn, lead)
    if duplicate:
        add_event(conn, duplicate["id"], "duplicate_ignored",
                  f"Incoming lead matched existing lead ID {duplicate['id']}")
        conn.commit()
        print(f"[DUPLICATE] {lead.get('name')} matches existing lead ID {duplicate['id']}; no new record or alert.")
        return {"status": "duplicate", "id": duplicate["id"]}

    score, priority, reasons = score_lead(lead)
    content = claude_content(lead)
    conn.execute("""
        INSERT INTO leads(name,email,phone,company,requirement,budget_inr,industry,source,score,priority,status,
                          reasons_json,pain_point,recommended_service,follow_up,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (str(lead.get("name") or "").strip(), normalize_email(lead.get("email")) or None,
          str(lead.get("phone") or "").strip() or None, str(lead.get("company") or "").strip() or None,
          str(lead.get("requirement") or "").strip(), lead.get("budget_inr"), lead.get("industry"), lead.get("source"),
          score, priority, "qualified", json.dumps(reasons), content["pain_point"], content["recommended_service"],
          content["follow_up"], now_iso(), now_iso()))
    lead_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    add_event(conn, lead_id, "qualified", f"Score {score}; priority {priority}")
    conn.commit()
    print(f"[{priority.upper()}] {lead.get('name')} | score={score}/100 | service={content['recommended_service']}")
    print(f"  Follow-up: {content['follow_up']}")
    if priority == "Hot":
        notify_hot_lead(conn, lead_id, str(lead.get("name")), score)
    return {"status": "qualified", "id": lead_id, "score": score, "priority": priority}


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Sample/input JSON must contain a list of lead objects.")
    return data


def process_file(path: Path) -> None:
    leads = load_json(path)
    counts = {"qualified": 0, "rejected": 0, "duplicate": 0}
    conn = connect_db()
    try:
        print(f"Processing {len(leads)} input lead(s) from {path.name}...")
        for lead in leads:
            result = process_one(conn, lead)
            counts[result["status"]] += 1
        print("\nSUMMARY")
        print(f"Input leads: {len(leads)}")
        print(f"Qualified/new records: {counts['qualified']}")
        print(f"Rejected: {counts['rejected']}")
        print(f"Duplicates ignored: {counts['duplicate']}")
        print(f"Database: {DB_PATH}")
        print(f"Outbox: {OUTBOX_PATH}")
    finally:
        conn.close()


def inspect_lead(identifier: str) -> None:
    conn = connect_db()
    try:
        if identifier.isdigit():
            row = conn.execute("SELECT * FROM leads WHERE id=?", (int(identifier),)).fetchone()
        else:
            row = conn.execute("SELECT * FROM leads WHERE lower(email)=? ORDER BY id DESC LIMIT 1",
                               (normalize_email(identifier),)).fetchone()
        if not row:
            print(f"No lead found for {identifier!r}. Run the sample workflow first.")
            return
        print(json.dumps(dict(row), indent=2, ensure_ascii=False))
        print("\nEVENT HISTORY")
        for event in conn.execute("SELECT event_type,details,created_at FROM events WHERE lead_id=? ORDER BY id",
                                  (row["id"],)):
            print(f"- {event['created_at']} | {event['event_type']}: {event['details']}")
    finally:
        conn.close()


def list_leads() -> None:
    conn = connect_db()
    try:
        rows = conn.execute("SELECT id,name,email,score,priority,status FROM leads ORDER BY id").fetchall()
        if not rows:
            print("No leads yet. Run: python leadflow.py process sample_leads.json")
            return
        print(f"{'ID':<4} {'NAME':<22} {'SCORE':<7} {'PRIORITY':<9} {'STATUS':<10} EMAIL")
        for row in rows:
            print(f"{row['id']:<4} {row['name'][:21]:<22} {str(row['score'] if row['score'] is not None else '-'): <7} "
                  f"{(row['priority'] or '-'): <9} {row['status']:<10} {row['email'] or '-'}")
    finally:
        conn.close()


def export_csv(path: Path) -> None:
    conn = connect_db()
    try:
        rows = conn.execute("SELECT * FROM leads ORDER BY id").fetchall()
        if not rows:
            print("No leads to export yet.")
            return
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows([dict(row) for row in rows])
        print(f"Exported {len(rows)} lead record(s) to {path}")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LeadFlow: lead qualification and follow-up automation")
    sub = parser.add_subparsers(dest="command", required=True)
    p_process = sub.add_parser("process", help="Process leads from a JSON file")
    p_process.add_argument("file", nargs="?", default="sample_leads.json")
    p_inspect = sub.add_parser("inspect", help="Inspect a lead by numeric ID or email")
    p_inspect.add_argument("identifier")
    sub.add_parser("list", help="List stored leads")
    p_export = sub.add_parser("export", help="Export lead records to CSV")
    p_export.add_argument("file", nargs="?", default="leadflow_export.csv")
    sub.add_parser("retry-alerts", help="Retry pending Slack alerts (requires webhook)")
    args = parser.parse_args(argv)
    try:
        if args.command == "process":
            process_file(Path(args.file)); return 0
        if args.command == "inspect":
            inspect_lead(args.identifier); return 0
        if args.command == "list":
            list_leads(); return 0
        if args.command == "export":
            export_csv(Path(args.file)); return 0
        if args.command == "retry-alerts":
            conn = connect_db()
            try:
                sent = send_pending_alerts(conn)
                print(f"Alerts sent: {sent}; pending alerts remain pending if no webhook or a send failed.")
            finally:
                conn.close()
            return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
