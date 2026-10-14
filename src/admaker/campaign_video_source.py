"""Resolve the unoverlaid source of the exact delivered campaign pack."""
from pathlib import PurePosixPath


def delivered_video_source(connection, job_id, account_id) -> dict:
    # Match the settled export manifest, not the newest or currently active run.
    rows = connection.execute(
        "SELECT r.id,p.result FROM app.jobs j JOIN app.job_runs r ON r.job_id=j.id "
        "JOIN app.job_stages c ON c.run_id=r.id AND c.stage_key='campaign_pack_compose' "
        "JOIN app.job_stages p ON p.run_id=r.id AND p.stage_key='provider_compose' "
        "WHERE j.id=%s AND j.owner_id=%s AND j.state='delivered' "
        "AND j.settings->>'generationKind'='campaign_pack' "
        "AND c.result=j.result->'exports'",
        (job_id, account_id),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("A unique delivered campaign video source is unavailable")
    run_id, exports = rows[0]
    item = exports.get("tiktok") if isinstance(exports, dict) else None
    key = item.get("key") if isinstance(item, dict) else None
    if (not isinstance(key, str) or not key or len(key) > 1024 or "\\" in key
            or ":" in key or any(part in {"", ".", ".."} for part in key.split("/"))
            or PurePosixPath(key).is_absolute()):
        raise ValueError("Delivered campaign video source is invalid")
    # Internal only: caller must verify/stage owned bytes before rendering.
    # A source receipt does not prove its audio is free of spoken offers.
    return {"runId": str(run_id), "key": key}
