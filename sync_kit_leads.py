#!/usr/bin/env python3
"""Sync Kit's (ElevenLabs phone agent) calls into Supabase kit_leads.
Idempotent: unique call_id + ignore-duplicates, safe to run any time.
  python3 sync_kit_leads.py            # sync
  python3 sync_kit_leads.py --dry      # show what would sync, insert nothing
Runs every 15 min via launchd (com.mountaingoats.kitleads). Disable with:
  launchctl unload ~/Library/LaunchAgents/com.mountaingoats.kitleads.plist
"""
import json, sys, urllib.request, datetime

XI_KEY = open("/Users/wboone/Desktop/Mountain Goats/Divine Paradox/.elevenlabs_key").read().strip()
SB_URL = "https://nrfiomvamfcrvopynfdf.supabase.co"
SB_KEY = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5yZmlvbXZhbWZjcnZvcHluZmRmIiwi"
          "cm9sZSI6ImFub24iLCJpYXQiOjE3Njg1MDY5OTgsImV4cCI6MjA4NDA4Mjk5OH0.J7bEn5YtQ69WbVMsga5oIEewapJV9Nf8OEK2xWefAYU")
AGENT_NAME_MATCH = "kit"
SPAM = ("scam","spam","verification","robocall","telemarket","unwanted","solicit","wrong number","incoherent")
LEADY = ("sponsor","invest","donat","join","quote","meeting","interview","ticket","premiere","media","press","volunteer")

def xi(path):
    req = urllib.request.Request("https://api.elevenlabs.io" + path, headers={"xi-api-key": XI_KEY})
    return json.load(urllib.request.urlopen(req, timeout=30))

def classify(title):
    t = (title or "").lower()
    if any(s in t for s in SPAM): return "spam"
    if any(s in t for s in LEADY): return "lead"
    return "other"

def main():
    dry = "--dry" in sys.argv
    agents = xi("/v1/convai/agents")["agents"]
    kit = next(a for a in agents if AGENT_NAME_MATCH in a["name"].lower())
    convs, cursor = [], None
    while True:
        q = f"/v1/convai/conversations?agent_id={kit['agent_id']}&page_size=100" + (f"&cursor={cursor}" if cursor else "")
        page = xi(q)
        convs += page.get("conversations", [])
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor: break

    rows = []
    for c in convs:
        cid = c.get("conversation_id")
        title = c.get("call_summary_title") or ""
        cat = classify(title)
        row = {
            "call_id": cid,
            "started_at": (datetime.datetime.fromtimestamp(c["start_time_unix_secs"], datetime.timezone.utc).isoformat()
                           if c.get("start_time_unix_secs") else None),
            "duration_secs": c.get("call_duration_secs"),
            "title": title, "category": cat,
        }
        # transcripts + summary only for non-spam (worth the extra call)
        if cat != "spam":
            try:
                d = xi(f"/v1/convai/conversations/{cid}")
                row["summary"] = (d.get("analysis") or {}).get("transcript_summary")
                tr = d.get("transcript") or []
                row["transcript"] = "\n".join(f"{t.get('role','?')}: {t.get('message','')}" for t in tr)[:8000] or None
                meta = (d.get("metadata") or {})
                row["from_number"] = ((meta.get("phone_call") or {}).get("external_number")) or None
            except Exception:
                pass
        for k in ("summary","transcript","from_number"):
            row.setdefault(k, None)
        rows.append(row)

    print(f"Kit calls fetched: {len(rows)} | lead:{sum(r['category']=='lead' for r in rows)} "
          f"spam:{sum(r['category']=='spam' for r in rows)} other:{sum(r['category']=='other' for r in rows)}")
    if dry:
        for r in rows[:10]: print("  would sync:", r["started_at"], r["category"], (r["title"] or "")[:40])
        return

    ok = dup = fail = 0
    for r in rows:
        req = urllib.request.Request(SB_URL + "/rest/v1/kit_leads", data=json.dumps(r).encode(), method="POST",
            headers={"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY,
                     "Content-Type": "application/json", "Prefer": "return=minimal"})
        try:
            urllib.request.urlopen(req, timeout=30); ok += 1
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:160]
            if e.code == 409 or "duplicate" in msg or "23505" in msg: dup += 1
            else: fail += 1; print("  row fail:", e.code, msg[:100])
    print(f"synced: {ok} new, {dup} already there, {fail} failed.")

if __name__ == "__main__":
    main()
