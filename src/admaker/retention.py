"""Expire abandoned local uploads; verified product/history media are retained."""
import argparse
import json
import os
from pathlib import Path

import psycopg


def expire_uploads(database_url, root, *, apply=False, limit=100):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Limit must be between 1 and 1000")
    root = Path(root).resolve(strict=True)
    removed = eligible = skipped = 0
    with psycopg.connect(database_url) as connection:
        owners = connection.execute("SELECT DISTINCT owner_id FROM app.assets WHERE verification_state='pending' AND created_at<clock_timestamp()-interval '15 minutes' ORDER BY owner_id LIMIT %s", (limit,)).fetchall()
    for (owner,) in owners:
        with psycopg.connect(database_url) as connection:
            if not connection.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))", (f"account-media:{owner}",)).fetchone()[0]:
                skipped += 1
                continue
            if connection.execute("SELECT 1 FROM app.account_deletions WHERE account_id=%s", (owner,)).fetchone():
                continue
            rows = connection.execute("""SELECT a.asset_key,a.storage_key FROM app.assets a
                WHERE a.owner_id=%s AND a.verification_state='pending'
                AND a.created_at<clock_timestamp()-interval '15 minutes'
                AND NOT EXISTS (SELECT 1 FROM app.jobs j WHERE j.source_asset_id=a.asset_key)
                AND NOT EXISTS (SELECT 1 FROM app.products p WHERE p.source_asset_id=a.asset_key)
                AND NOT EXISTS (SELECT 1 FROM app.product_images p WHERE p.asset_key=a.asset_key)
                AND NOT EXISTS (SELECT 1 FROM app.cloud_objects o WHERE o.account_id=a.owner_id AND o.local_key=a.storage_key)
                ORDER BY a.created_at,a.asset_key LIMIT %s FOR UPDATE OF a SKIP LOCKED
                """, (owner, limit - eligible)).fetchall()
            for asset, key in rows:
                path = root / key
                expected_parent = root / "incoming" / str(owner)
                if (path.parent != expected_parent or path.stem != str(asset)
                        or path.resolve() != path.absolute() or not path.resolve().is_relative_to(root)
                        or path.is_symlink() or (path.exists() and not path.is_file())):
                    skipped += 1
                    continue
                eligible += 1
                if apply:
                    path.unlink(missing_ok=True)
                    connection.execute("DELETE FROM app.assets WHERE asset_key=%s AND verification_state='pending'", (asset,))
                    removed += 1
        if eligible >= limit:
            break
    return {"eligibleUploads": eligible, "removedUploads": removed, "skipped": skipped, "dryRun": not apply}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("LOCAL_ASSET_ROOT", ".local-assets"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = expire_uploads(os.environ["DATABASE_URL"], args.root, apply=args.apply, limit=args.limit)
    except Exception:
        print(json.dumps({"event": "retention_failed", "message": "Cleanup outcome is unconfirmed; verify database and storage configuration before retrying."}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
