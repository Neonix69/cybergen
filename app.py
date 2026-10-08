"""CYBERGEN registration: receives the form + payment screenshot and posts them to a Discord channel."""
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))

# Paste your Discord webhook URL between the quotes.
WEBHOOK_URL = "https://discord.com/api/webhooks/1557631556951089212/D7YrTl4TKuJL56ZAcXWrMrvEa6uMKW60YNkbJupBiI1qHvmOcLpZbJ7aPj8u0YUuDYeh"

DEPARTMENTS = {"B.Sc. ISDF", "B.Sc. AIDS", "M.Sc. ISDF", "M.Sc. AIDS"}
YEARS = {"I", "II", "III"}
ROLES = ["Team Leader", "Member 1", "Member 2", "Member 3"]
MAX_IMAGE = 8 * 1024 * 1024  # 8 MB

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


def clean(value):
    return " ".join(str(value or "").split())


def bad(message, status=400):
    return jsonify(ok=False, error=message), status


@app.errorhandler(413)
def too_big(_e):
    return bad("That image is too large. Please choose a smaller screenshot.", 413)


def sniff_image(blob):
    """Return (extension, mime) based on the file's real contents, or None."""
    if blob[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def send_to_discord(payload, filename, blob, mime):
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        f"Content-Type: application/json\r\n\r\n"
    ).encode() + json.dumps(payload).encode("utf-8") + b"\r\n"
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + blob + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        WEBHOOK_URL.strip(),
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            # Discord can reject Python's default User-Agent, so send our own.
            "User-Agent": "CYBERGEN-Registration/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25):
        pass


@app.get("/")
def index():
    return send_from_directory(os.path.join(BASE, "static"), "index.html")


@app.post("/api/register")
def register():
    try:
        data = json.loads(request.form.get("data", ""))
    except ValueError:
        return bad("Something went wrong. Please refresh and try again.")
    if not isinstance(data, dict):
        return bad("Something went wrong. Please refresh and try again.")

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

    shot = request.files.get("screenshot")
    if shot is None:
        return bad("Upload your payment screenshot.")
    blob = shot.read(MAX_IMAGE + 1)
    if not blob:
        return bad("Upload your payment screenshot.")
    if len(blob) > MAX_IMAGE:
        return bad("That image is too large. Please choose a smaller screenshot.", 413)
    kind = sniff_image(blob)
    if kind is None:
        return bad("Use a JPG, PNG or WebP screenshot.")
    ext, mime = kind

    if not WEBHOOK_URL.startswith("https://"):
        app.logger.error("WEBHOOK_URL is not set in app.py")
        return bad("Registration isn't set up yet. Please tell the organisers.", 500)

    leader_name, leader_reg = people[0][1], people[0][2]
    safe = lambda s: re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:40] or "team"
    filename = f"{safe(leader_name)}_{safe(leader_reg)}_payment.{ext}"

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
                {"name": "Team Members", "value": member_lines, "inline": False},
            ],
            "image": {"url": f"attachment://{filename}"},
            "footer": {"text": "CYBERGEN \u2022 Registration \u2022 Payment screenshot below"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }

    try:
        send_to_discord(payload, filename, blob, mime)
    except urllib.error.HTTPError as e:
        app.logger.error("Discord rejected the message: %s %s", e.code, e.read()[:300])
        return bad("Couldn't send your registration. Please try again.", 502)
    except Exception as e:  # network errors, timeouts
        app.logger.error("Could not reach Discord: %s", e)
        return bad("Couldn't send your registration. Please try again.", 502)

    return jsonify(ok=True)


if __name__ == "__main__":
    if not WEBHOOK_URL.startswith("https://"):
        print("WARNING: paste your webhook URL into app.py. Registrations will not be sent.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
