"""Read-only deletion inventory. A snapshot is not authorization to unlink files."""
from pathlib import Path
import uuid
import os


def media_keys(value):
    if isinstance(value, dict):
        for name, child in value.items():
            if name == "key" and isinstance(child, str) and child:
                yield child
            elif isinstance(child, (dict, list)):
                yield from media_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from media_keys(child)


def account_media_inventory(connection, account_id, root):
    account_id = uuid.UUID(str(account_id))
    if not connection.execute("SELECT 1 FROM app.accounts WHERE id=%s", (account_id,)).fetchone():
        raise LookupError("Account not found")
    root = Path(root).resolve(strict=True)
    owned, others = set(), set()
    for owner, key in connection.execute("SELECT owner_id,storage_key FROM app.assets"):
        (owned if owner == account_id else others).add(key)
    # Include durable intermediate outputs as well as published and historical exports.
    for owner, manifest in connection.execute(
        "SELECT owner_id,result FROM app.jobs UNION ALL "
        "SELECT c.owner_id,l.manifest FROM app.campaign_layouts l JOIN app.campaigns c ON c.id=l.campaign_id UNION ALL "
        "SELECT j.owner_id,s.result FROM app.job_stages s JOIN app.job_runs r ON r.id=s.run_id JOIN app.jobs j ON j.id=r.job_id"
    ):
        (owned if owner == account_id else others).update(media_keys(manifest))
    directories = [root / "incoming" / str(account_id), root / "verified" / str(account_id)]
    directories.extend(root / "runs" / str(row[0]) for row in connection.execute("SELECT id FROM app.jobs WHERE owner_id=%s", (account_id,)))
    directories.extend(root / "campaigns" / str(row[0]) for row in connection.execute("SELECT id FROM app.campaigns WHERE owner_id=%s", (account_id,)))
    directories.extend(root / "campaign-runs" / str(row[0]) for row in connection.execute("SELECT r.id FROM app.job_runs r JOIN app.jobs j ON j.id=r.job_id WHERE j.owner_id=%s", (account_id,)))
    for directory in directories:
        if directory.resolve() != directory.absolute():
            owned.add(directory.relative_to(root).as_posix())
            continue
        for folder, subdirs, names in os.walk(directory, followlinks=False):
            for name in list(subdirs):
                path = Path(folder) / name
                if path.is_symlink() or path.is_junction():
                    owned.add(path.relative_to(root).as_posix())
                    subdirs.remove(name)
            owned.update((Path(folder) / name).relative_to(root).as_posix() for name in names)
    other_paths = {(root / key).resolve() for key in others}
    files = []
    for key in sorted(owned):
        path = (root / key).resolve()
        status = ("outside_storage_root" if not path.is_relative_to(root) else
                  "shared_reference" if path in other_paths else
                  "linked_path" if path != (root / key).absolute() else
                  "missing" if not path.exists() else
                  "not_a_file" if not path.is_file() else "owned_file")
        files.append({"key": key, "status": status})
    jobs = connection.execute(
        "SELECT id,state FROM app.jobs WHERE owner_id=%s AND (state IN ('submitted','running','awaiting_user_decision') "
        "OR EXISTS (SELECT 1 FROM app.credit_reservations r WHERE r.job_id=app.jobs.id AND r.state='held')) ORDER BY id",
        (account_id,),
    ).fetchall()
    return {"files": files, "pendingJobs": [{"id": str(job), "state": state} for job, state in jobs],
            "scope": "Referenced files and durable owner-scoped directories; stop writers and recheck before cleanup. Legacy unscoped orphan files, identity, checkpoints, financial retention and backup expiry require separate handling."}
