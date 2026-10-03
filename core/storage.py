"""SQLite storage module for cases, timelines, events, and follow-up messages.

Enforces privacy rules:
- Data persistence is opt-in and structured.
- Delete my data completely removes all associated rows from disk.
"""

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cases.db")


def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create and return a SQLite database connection with row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialize SQLite database tables for cases, events, and messages."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                patient_info TEXT NOT NULL,
                doctor_dx TEXT,
                state_json TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                summary TEXT NOT NULL,
                details_json TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                msg_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                attachments_json TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()


def save_case(case_state: dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> str:
    """Insert or update a case in the database.

    Args:
        case_state: CaseState dict conforming to SPEC.md Section 4.6
        db_path: SQLite database file path

    Returns:
        The case_id string.
    """
    init_db(db_path)
    case_id = case_state.get("case_id") or str(uuid.uuid4())
    case_state["case_id"] = case_id
    now = datetime.now().isoformat()

    created_at = case_state.get("created") or now
    patient_info = json.dumps(case_state.get("patient", {}))
    doctor_dx = case_state.get("doctor_dx", "")
    state_json = json.dumps(case_state)

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO cases (case_id, created_at, updated_at, patient_info, doctor_dx, state_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                patient_info = excluded.patient_info,
                doctor_dx = excluded.doctor_dx,
                state_json = excluded.state_json
            """,
            (case_id, created_at, now, patient_info, doctor_dx, state_json),
        )
        conn.commit()

    return case_id


def get_case(case_id: str, db_path: str = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    """Retrieve full CaseState dictionary by case_id."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT state_json FROM cases WHERE case_id = ?", (case_id,))
        row = cursor.fetchone()
        if row:
            case_dict = json.loads(row["state_json"])
            # Attach events and messages
            case_dict["events"] = get_case_events(case_id, db_path)
            case_dict["messages"] = get_case_messages(case_id, limit=50, db_path=db_path)
            return case_dict
    return None


def list_cases(db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Return summary list of all saved cases with message counts."""
    init_db(db_path)
    cases = []
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.case_id, c.created_at, c.updated_at, c.patient_info, c.doctor_dx,
                   COUNT(m.msg_id) AS message_count
            FROM cases c
            LEFT JOIN messages m ON c.case_id = m.case_id
            GROUP BY c.case_id
            ORDER BY c.updated_at DESC
            """
        )
        for row in cursor.fetchall():
            cases.append({
                "case_id": row["case_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "patient": json.loads(row["patient_info"]) if row["patient_info"] else {},
                "doctor_dx": row["doctor_dx"],
                "message_count": row["message_count"],
            })
    return cases


def save_event(
    case_id: str,
    event_type: str,
    summary: str,
    details: dict[str, Any] | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """Record a clinical milestone or assessment event in the case timeline."""
    init_db(db_path)
    event_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    details_json = json.dumps(details or {})

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO events (event_id, case_id, event_type, timestamp, summary, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_id, case_id, event_type, now, summary, details_json),
        )
        # Update case updated_at
        cursor.execute("UPDATE cases SET updated_at = ? WHERE case_id = ?", (now, case_id))
        conn.commit()

    return event_id


def get_case_events(case_id: str, db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Retrieve chronologically ordered events for a case."""
    init_db(db_path)
    events = []
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT event_id, event_type, timestamp, summary, details_json FROM events WHERE case_id = ? ORDER BY timestamp ASC",
            (case_id,),
        )
        for row in cursor.fetchall():
            events.append({
                "event_id": row["event_id"],
                "type": row["event_type"],
                "date": row["timestamp"],
                "summary": row["summary"],
                "details": json.loads(row["details_json"]) if row["details_json"] else {},
            })
    return events


def save_message(
    case_id: str,
    role: str,
    content: str,
    attachments: list[dict[str, Any]] | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """Record a chat message in the case discussion."""
    init_db(db_path)
    msg_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    att_json = json.dumps(attachments or [])

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO messages (msg_id, case_id, role, content, attachments_json, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (msg_id, case_id, role, content, att_json, now),
        )
        conn.commit()

    return msg_id


def get_case_messages(case_id: str, limit: int = 6, db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Retrieve the most recent messages for a case (bounded to limit, default 6)."""
    init_db(db_path)
    messages = []
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT msg_id, role, content, attachments_json, timestamp
            FROM (
                SELECT * FROM messages WHERE case_id = ? ORDER BY timestamp DESC LIMIT ?
            ) ORDER BY timestamp ASC
            """,
            (case_id, limit),
        )
        for row in cursor.fetchall():
            messages.append({
                "msg_id": row["msg_id"],
                "role": row["role"],
                "content": row["content"],
                "attachments": json.loads(row["attachments_json"]) if row["attachments_json"] else [],
                "timestamp": row["timestamp"],
            })
    return messages


def delete_case_data(case_id: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Delete all records associated with a specific case."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE case_id = ?", (case_id,))
        cursor.execute("DELETE FROM events WHERE case_id = ?", (case_id,))
        cursor.execute("DELETE FROM cases WHERE case_id = ?", (case_id,))
        conn.commit()


def delete_all_data(db_path: str = DEFAULT_DB_PATH) -> None:
    """Complete privacy wipe: removes all stored cases, events, and messages."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages")
        cursor.execute("DELETE FROM events")
        cursor.execute("DELETE FROM cases")
        conn.commit()
