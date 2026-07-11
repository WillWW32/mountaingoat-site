#!/usr/bin/env python3
"""Giveaway follow-up sequence (runs every 10 min via launchd com.mountaingoats.followups).
Step 1 WELCOME  — sent right after someone enters ("You're in").
Step 2 DROP DAY — sent once the trailer is live (double-entry window reminder to share).
Reads pending rows via a secret-guarded RPC; sends via SendGrid; marks sent (idempotent).
  python3 followup_giveaway.py --dry     # show pending, send nothing
Disable: launchctl unload ~/Library/LaunchAgents/com.mountaingoats.followups.plist
"""
import os, json, sys, urllib.request, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SB_URL = "https://nrfiomvamfcrvopynfdf.supabase.co"
SB_KEY = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5yZmlvbXZhbWZjcnZvcHluZmRmIiwi"
          "cm9sZSI6ImFub24iLCJpYXQiOjE3Njg1MDY5OTgsImV4cCI6MjA4NDA4Mjk5OH0.J7bEn5YtQ69WbVMsga5oIEewapJV9Nf8OEK2xWefAYU")
SECRET = open(os.path.join(HERE, ".worker_secret")).read().strip()
_env = {}
for line in open(os.path.join(HERE, ".mail_env")):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1); _env[k] = v
RESEND_KEY = _env["RESEND_API_KEY"]; FROM = _env.get("EMAIL_FROM", "Mountain Goats <mountaingoats@artflowmail.com>")

def sb(path, body):
    req = urllib.request.Request(SB_URL + path, data=json.dumps(body).encode(), method="POST",
        headers={"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = r.read()
        return json.loads(d) if d else None

def config():
    req = urllib.request.Request(SB_URL + "/rest/v1/site_config?select=key,value",
        headers={"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY})
    return {r["key"]: r["value"] for r in json.load(urllib.request.urlopen(req, timeout=30))}

def send_email(to, subject, html):
    body = {"from": FROM, "to": [to], "subject": subject, "html": html}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + RESEND_KEY, "Content-Type": "application/json", "User-Agent": "mountaingoats-worker/1.0", "Accept": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=30)

STYLE = "font-family:Arial,Helvetica,sans-serif;background:#0d0d0d;color:#f2ede2;padding:28px;border-radius:12px;max-width:560px;margin:0 auto;"
GOLD = "color:#e8a849;"

def welcome_html(name, weight):
    dbl = ("<p style='%s'><b>Your entry counts DOUBLE</b> — you got in during the early window. 🐐</p>" % GOLD) if weight == 2 else ""
    return f"""<div style="{STYLE}">
<h2 style="{GOLD}margin:0 0 12px;">You're in, {name.split()[0] if name else 'friend'}. 🏀</h2>
<p>You're officially entered in the <b>Mountain Goats free ticket giveaway</b> for the community screening.</p>{dbl}
<p>What happens next:</p>
<ol><li>The trailer drops — watch for it at <a href="https://mountaingoats.co" style="{GOLD}">mountaingoats.co</a></li>
<li>We announce the <b>ticket drop night</b> — winners claim seats first-come</li>
<li>Claim fast — unclaimed seats release to the waitlist</li></ol>
<p style="margin-top:18px;">Made in Missoula, for Missoula.<br>— Jesse &amp; the Mountain Goats crew</p></div>"""

def drop_html(name):
    return f"""<div style="{STYLE}">
<h2 style="{GOLD}margin:0 0 12px;">The trailer is LIVE. 🎬</h2>
<p>{name.split()[0] if name else 'Hey'} — the Mountain Goats trailer just dropped. Watch it now at
<a href="https://mountaingoats.co/trailer" style="{GOLD}">mountaingoats.co/trailer</a>.</p>
<p><b>For the next 24 hours, new entries count double</b> — share the giveaway with a friend who should be in the building:
<a href="https://mountaingoats.co/#giveaway" style="{GOLD}">mountaingoats.co</a></p>
<p>Ticket drop night gets announced soon. Eyes on your inbox.<br>— The Mountain Goats crew</p></div>"""

def main():
    dry = "--dry" in sys.argv
    log = lambda *a: print(datetime.datetime.now().strftime("%H:%M"), *a)
    # STEP 1 — welcomes
    pend = sb("/rest/v1/rpc/pending_followups", {"kind": "welcome", "secret": SECRET}) or []
    log(f"welcome pending: {len(pend)}")
    done = []
    for e in pend:
        if dry: log("  would welcome:", e["email"], "w", e.get("entry_weight")); continue
        try:
            send_email(e["email"], "You're in — Mountain Goats ticket giveaway 🏀", welcome_html(e.get("name") or "", e.get("entry_weight") or 1))
            done.append(e["id"]); log("  welcomed", e["email"])
        except Exception as ex: log("  send fail", e["email"], str(ex)[:80])
    if done: sb("/rest/v1/rpc/mark_followup", {"kind": "welcome", "ids": done, "secret": SECRET})
    # STEP 2 — drop-day reminder (only once trailer is live)
    try: cfg = config()
    except Exception: cfg = {}
    drop = cfg.get("trailer_drop_at")
    if drop and datetime.datetime.now(datetime.timezone.utc) >= datetime.datetime.fromisoformat(drop):
        pend = sb("/rest/v1/rpc/pending_followups", {"kind": "drop", "secret": SECRET}) or []
        log(f"drop-day pending: {len(pend)}")
        done = []
        for e in pend:
            if dry: continue
            try:
                send_email(e["email"], "The Mountain Goats trailer is LIVE 🎬", drop_html(e.get("name") or ""))
                done.append(e["id"]); log("  drop-mailed", e["email"])
            except Exception as ex: log("  send fail", e["email"], str(ex)[:80])
        if done: sb("/rest/v1/rpc/mark_followup", {"kind": "drop", "ids": done, "secret": SECRET})

if __name__ == "__main__":
    main()
