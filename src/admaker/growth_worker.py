"""Run periodically: python -m admaker.growth_worker. Push is disabled by default."""
import os
import uuid
import argparse
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import psycopg

PUSH_TEXT = {
    "en": {"completion": "Your creation is ready to review.", "weekly": "Ready to plan your next campaign? Continue when it suits you."},
    "tr": {"completion": "İçeriğin hazır. İnceleyebilirsin.", "weekly": "Yeni kampanyanı planlamak ister misin? Sana uygun bir zamanda devam et."},
    "pt-BR": {"completion": "Sua criação está pronta para revisar.", "weekly": "Vamos planejar sua próxima campanha? Continue quando for melhor para você."},
    "es": {"completion": "Tu contenido está listo para revisar.", "weekly": "¿Quieres planear tu próxima campaña? Continúa cuando te venga bien."},
}


def collect_notifications(c, account, now=None):
    now = now or datetime.now(timezone.utc)
    row = c.execute("SELECT preferences,updated_at FROM app.growth_preferences WHERE account_id=%s", (account,)).fetchone()
    if not row or c.execute("SELECT 1 FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone():
        return
    preferences, enabled_at = row
    local = now.astimezone(ZoneInfo(preferences.get("timezone", "UTC")))
    if not 9 <= local.hour < 20:
        return
    keys = []
    if preferences.get("completion"):
        # A single daily summary, not a push for every output in a pack.
        jobs = c.execute("SELECT j.id,j.version FROM app.jobs j JOIN app.job_events e ON e.job_id=j.id AND e.event_key='state:'||j.version WHERE j.owner_id=%s AND j.state='delivered' AND e.occurred_at>=%s AND e.occurred_at>=%s-interval '7 days' ORDER BY e.occurred_at DESC LIMIT 100", (account, enabled_at, now)).fetchall()
        for job, version in jobs:
            keys.append((f"job:{job}:{version}", "completion"))
    if preferences.get("weekly") and local.weekday() == preferences.get("weekday", 0) and local.hour == preferences.get("hour", 10):
        keys.append((f"week:{local.isocalendar().year}:{local.isocalendar().week}", "weekly"))
    for key, kind in keys:
        c.execute("INSERT INTO app.growth_notifications(id,account_id,event_key,kind,created_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(account_id,event_key) DO NOTHING", (uuid.uuid4(), account, key, kind, now))


def dispatch_account(database_url, account, *, send=None, now=None):
    """At most one summary/day. Uncertain sends are not retried automatically."""
    if send is None and os.environ.get("ENABLE_ENGAGEMENT_PUSH") != "true":
        return
    with psycopg.connect(database_url) as c:
        c.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (account,))
        if c.execute("SELECT 1 FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone():
            return
        row = c.execute("SELECT preferences FROM app.growth_preferences WHERE account_id=%s", (account,)).fetchone()
        if not row:
            return
        prefs = row[0]
        local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(prefs.get("timezone", "UTC")))
        if not 9 <= local.hour < 20:
            return
        if c.execute("SELECT 1 FROM app.growth_notifications WHERE account_id=%s AND push_attempted_at>now()-interval '24 hours' LIMIT 1", (account,)).fetchone():
            return
        kinds = [kind for kind in ("completion", "weekly") if prefs.get(kind) and
                 (kind != "weekly" or (local.weekday() == prefs.get("weekday", 0) and local.hour == prefs.get("hour", 10)))]
        note = c.execute("SELECT id,kind FROM app.growth_notifications WHERE account_id=%s AND kind=ANY(%s) AND read_at IS NULL AND push_attempted_at IS NULL AND created_at>now()-interval '24 hours' ORDER BY created_at DESC LIMIT 1", (account, kinds)).fetchone()
        device = c.execute("SELECT token FROM app.push_devices WHERE account_id=%s AND expires_at>now() ORDER BY expires_at DESC LIMIT 1", (account,)).fetchone()
        if not note or not device:
            return
        c.execute("UPDATE app.growth_notifications SET push_attempted_at=now(),push_state='attempting' WHERE id=%s", (note[0],))
        c.commit()  # Persist before the external effect; a crash must not spam users.
        # Reacquire account lock; withdrawal/deletion before this check cancels sending.
        c.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (account,))
        current = c.execute("SELECT preferences FROM app.growth_preferences WHERE account_id=%s", (account,)).fetchone()
        if (not current or not current[0].get(note[1]) or
            c.execute("SELECT 1 FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone() or
            not c.execute("SELECT 1 FROM app.push_devices WHERE token=%s AND account_id=%s AND expires_at>now()", (device[0], account)).fetchone()):
            return
        message = {"to": device[0], "title": "Addy AI", "body": PUSH_TEXT.get(current[0].get("locale", "en"), PUSH_TEXT["en"])[note[1]], "data": {"screen": "notifications"}, "ttl": 3600, "channelId": "campaigns"}
        try:
            if send is None:
                headers = {"Authorization": f"Bearer {os.environ['EXPO_ACCESS_TOKEN']}"} if os.environ.get("EXPO_ACCESS_TOKEN") else {}
                response = httpx.post("https://exp.host/--/api/v2/push/send", json=message, headers=headers, timeout=10)
                response.raise_for_status()
                result = response.json().get("data", {})
            else:
                result = send(message)
            state = "accepted" if result.get("status") == "ok" else "rejected"
            c.execute("UPDATE app.growth_notifications SET push_state=%s,ticket_id=%s WHERE id=%s", (state, result.get("id"), note[0]))
            if result.get("details", {}).get("error") == "DeviceNotRegistered":
                c.execute("DELETE FROM app.push_devices WHERE token=%s AND account_id=%s", (device[0], account))
        except (httpx.HTTPError, ValueError, TypeError):
            c.execute("UPDATE app.growth_notifications SET push_state='unknown' WHERE id=%s", (note[0],))


def reconcile_receipts(database_url, *, fetch=None):
    """Expo receipt OK acknowledges the platform service, not handset display."""
    if fetch is None and os.environ.get("ENABLE_ENGAGEMENT_PUSH") != "true":
        return
    with psycopg.connect(database_url) as c:
        rows = c.execute("SELECT id,account_id,ticket_id FROM app.growth_notifications WHERE push_state='accepted' AND ticket_id IS NOT NULL AND push_attempted_at<now()-interval '15 minutes' AND push_attempted_at>now()-interval '24 hours' ORDER BY push_attempted_at LIMIT 100").fetchall()
    if not rows:
        return
    ids = [row[2] for row in rows]
    try:
        if fetch is None:
            headers = {"Authorization": f"Bearer {os.environ['EXPO_ACCESS_TOKEN']}"} if os.environ.get("EXPO_ACCESS_TOKEN") else {}
            response = httpx.post("https://exp.host/--/api/v2/push/getReceipts", json={"ids": ids}, headers=headers, timeout=10)
            response.raise_for_status()
            receipts = response.json().get("data", {})
        else:
            receipts = fetch(ids)
        for note_id, account, ticket in rows:
            receipt = receipts.get(ticket)
            if not receipt:
                continue
            with psycopg.connect(database_url) as c:
                c.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (account,))
                if c.execute("SELECT 1 FROM app.account_deletions WHERE account_id=%s", (account,)).fetchone():
                    continue
                c.execute("UPDATE app.growth_notifications SET push_state=%s WHERE id=%s AND account_id=%s AND push_state='accepted'", ("receipt_ok" if receipt.get("status") == "ok" else "receipt_error", note_id, account))
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return  # Receipt reads can safely be retried on the next worker run.


def run_once(database_url):
    with psycopg.connect(database_url) as c:
        c.execute("DELETE FROM app.growth_events WHERE day<CURRENT_DATE-90")
        c.execute("DELETE FROM app.growth_notifications WHERE created_at<now()-interval '30 days'")
        c.execute("DELETE FROM app.push_devices WHERE expires_at<=now()")
        c.execute("UPDATE app.growth_notifications SET push_state='receipt_expired' WHERE push_state='accepted' AND push_attempted_at<now()-interval '24 hours'")
        accounts = [r[0] for r in c.execute("SELECT account_id FROM app.growth_preferences ORDER BY account_id")]
    reconcile_receipts(database_url)
    for account in accounts:
        with psycopg.connect(database_url) as c:
            c.execute("SELECT id FROM app.accounts WHERE id=%s FOR UPDATE", (account,))
            collect_notifications(c, account)
        dispatch_account(database_url, account)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=0, help="Seconds between runs; 0 runs once")
    args = parser.parse_args()
    if args.interval != 0 and not 30 <= args.interval <= 3600:
        parser.error("interval must be 0 or 30..3600 seconds")
    while True:
        run_once(os.environ["DATABASE_URL"])
        if not args.interval:
            break
        time.sleep(args.interval)
