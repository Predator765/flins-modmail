import os
import re
from datetime import datetime, timezone

from flask import Flask, render_template, abort
from pymongo import MongoClient

app = Flask(__name__)

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is not None:
        return _db
    uri = os.environ.get("CONNECTION_URI") or os.environ.get("MONGO_URI")
    if not uri:
        raise RuntimeError("CONNECTION_URI environment variable is not set.")
    db_name = os.environ.get("MONGO_DB_NAME", "modmail_bot")
    _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    _db = _client[db_name]
    return _db


def _fmt_ts(iso: str) -> str:
    """Return a human-readable timestamp from an ISO string."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%b %d, %Y at %I:%M %p UTC")
    except Exception:
        return iso


def _fmt_msg_ts(iso: str) -> str:
    """Short HH:MM timestamp for message rows."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%I:%M %p")
    except Exception:
        return ""


def _fmt_msg_date(iso: str) -> str:
    """Date label used for day separators."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%B %d, %Y")
    except Exception:
        return ""


def _initials(name: str) -> str:
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper() if name else "??"


def _avatar_color(name: str) -> str:
    colors = ["#5865F2", "#57F287", "#FEE75C", "#EB459E", "#ED4245",
              "#3BA55C", "#FAA61A", "#9B59B6", "#2980B9", "#E91E63"]
    idx = sum(ord(c) for c in name) % len(colors)
    return colors[idx]


def _process_messages(raw_messages: list) -> list:
    """
    Group consecutive messages by the same author into message groups,
    and inject day-separator markers.
    """
    groups = []
    last_author_id = None
    last_date = None

    for msg in raw_messages:
        author = msg.get("author", {})
        author_id = author.get("id", "")
        content = msg.get("content", "")
        attachments = msg.get("attachments", [])
        ts_iso = msg.get("timestamp", "")
        msg_date = _fmt_msg_date(ts_iso)

        if not content and not attachments:
            continue

        if msg_date and msg_date != last_date:
            groups.append({"type": "separator", "date": msg_date})
            last_date = msg_date
            last_author_id = None

        if author_id != last_author_id:
            groups.append({
                "type": "group",
                "author_id": author_id,
                "author_name": author.get("name", "Unknown"),
                "author_avatar": author.get("avatar_url"),
                "is_staff": bool(author.get("mod")),
                "initials": _initials(author.get("name", "??")),
                "color": _avatar_color(author.get("name", "??")),
                "messages": [],
            })
            last_author_id = author_id

        groups[-1]["messages"].append({
            "content": content,
            "attachments": attachments,
            "timestamp": _fmt_msg_ts(ts_iso),
            "full_timestamp": _fmt_ts(ts_iso),
        })

    return groups


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/<path:key>")
def view_log(key: str):
    key = key.strip("/")
    try:
        db = get_db()
    except RuntimeError as e:
        abort(503, description=str(e))

    doc = db.logs.find_one({"key": key})
    if doc is None:
        abort(404)

    if doc.get("type") != "ticket":
        abort(404, description="This key does not belong to a ticket log.")

    recipient = doc.get("recipient") or {}
    closer = doc.get("closer") or {}
    message_groups = _process_messages(doc.get("messages") or [])

    context = {
        "key": key,
        "channel_name": doc.get("channel_name", "unknown-channel"),
        "created_at": _fmt_ts(doc.get("created_at", "")),
        "closed_at": _fmt_ts(doc.get("closed_at", "")),
        "recipient_name": recipient.get("name", "Unknown"),
        "recipient_id": recipient.get("id", ""),
        "recipient_avatar": recipient.get("avatar_url"),
        "recipient_initials": _initials(recipient.get("name", "??")),
        "recipient_color": _avatar_color(recipient.get("name", "??")),
        "closer_name": closer.get("name", "Unknown"),
        "closer_id": closer.get("id", ""),
        "closer_avatar": closer.get("avatar_url"),
        "closer_initials": _initials(closer.get("name", "??")),
        "closer_color": _avatar_color(closer.get("name", "??")),
        "message_groups": message_groups,
        "total_messages": len(doc.get("messages") or []),
    }
    return render_template("log.html", **context)


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404,
                           message=getattr(e, "description", "Transcript not found.")), 404


@app.errorhandler(503)
def unavailable(e):
    return render_template("error.html", code=503,
                           message=getattr(e, "description", "Service unavailable.")), 503
