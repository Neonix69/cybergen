"""CYBERGEN registration: receives the form and posts it to a Discord channel."""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))

# Set this as an environment variable (see README steps in the chat), or paste it between the quotes.
WEBHOOK_URL = "https://discord.com/api/webhooks/1557631556951089212/D7YrTl4TKuJL56ZAcXWrMrvEa6uMKW60YNkbJupBiI1qHvmOcLpZbJ7aPj8u0YUuDYeh"
DEPARTMENTS = {"B.Sc. ISDF", "B.Sc. AIDS", "M.Sc. ISDF", "M.Sc. AIDS"}
YEARS = {"I", "II", "III"}
ROLES = ["Team Leader", "Member 1", "Member 2", "Member 3"]

app = Flask(__name__, static_folder=None)


def clean(value):
    return " ".join(str(value or "").split())


def bad(message, status=400):
    return jsonify(ok=False, error=message), status


def send_to_discord(payload):
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            # Discord can reject Python's default User-Agent, so send our own.
            "User-Agent": "CYBERGEN-Registration/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10):
        pass


@app.get("/")
def index():
    return send_from_directory(os.path.join(BASE, "static"), "index.html")


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}

    leader = data.get("leader") or {}
    members = data.get("members") or []
    if not isinstance(members, list) or len(members) != 3:
        return bad("A team needs exactly 3 members besides the leader.")

    people = []
    for role, p in zip(ROLES, [leader] + members):
        if not isinstance(p, dict):
            return bad(f"Details missing for {role}.")
        name, reg = clean(p.get("name")), clean(p.get("reg")).upper()
        if not name or len(name) > 80:
            return bad(f"Enter a valid full name for {role}.")
        if not reg or len(reg) > 30:
            return bad(f"Enter a valid register number for {role}.")
        people.append((role, name, reg))

    regs = [reg for _, _, reg in people]
    if len(set(regs)) != len(regs):
        return bad("Each person needs their own register number.")

    phone = re.sub(r"\D", "", str(data.get("phone") or ""))
    if not re.fullmatch(r"\d{10}", phone):
        return bad("Enter a 10-digit phone number.")
    dept = clean(data.get("dept"))
    if dept not in DEPARTMENTS:
        return bad("Select a valid department.")
    year = clean(data.get("year")).upper()
    if year not in YEARS:
        return bad("Select a valid year.")
    txn = clean(data.get("txn")).upper().replace("`", "")
    if not 6 <= len(txn) <= 40:
        return bad("Enter the UPI transaction ID from your payment app.")

    if not WEBHOOK_URL:
        app.logger.error("DISCORD_WEBHOOK_URL is not set")
        return bad("Registration isn't set up yet. Please tell the organisers.", 500)

    leader_name, leader_reg = people[0][1], people[0][2]
    member_lines = "\n".join(
        f"{i}. {name} \u2014 `{reg}`" for i, (_, name, reg) in enumerate(people[1:], 1)
    )
    payload = {
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": "New Team Registration",
            "description": f"Team size: **{len(people)}**",
            "color": 0xC81D3A,
            "fields": [
                {"name": "Team Leader", "value": leader_name, "inline": True},
                {"name": "Register Number", "value": f"`{leader_reg}`", "inline": True},
                {"name": "Phone", "value": phone, "inline": True},
                {"name": "Department", "value": dept, "inline": True},
                {"name": "Year", "value": year, "inline": True},
                {"name": "UPI Transaction ID", "value": f"`{txn}`", "inline": True},
                {"name": "Team Members", "value": member_lines, "inline": False},
            ],
            "footer": {"text": "CYBERGEN \u2022 Registration"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }

    try:
        send_to_discord(payload)
    except urllib.error.HTTPError as e:
        app.logger.error("Discord rejected the message: %s %s", e.code, e.read()[:300])
        return bad("Couldn't send your registration. Please try again.", 502)
    except Exception as e:  # network errors, timeouts
        app.logger.error("Could not reach Discord: %s", e)
        return bad("Couldn't send your registration. Please try again.", 502)

    return jsonify(ok=True)


if __name__ == "__main__":
    if not WEBHOOK_URL:
        print("WARNING: DISCORD_WEBHOOK_URL is not set. Registrations will not be sent.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
