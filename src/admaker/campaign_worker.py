"""Fenced pack stages reuse completed provider work before customer settlement."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import psycopg
from psycopg.types.json import Jsonb

from admaker.campaign_pack import compose_campaign_pack, require_available_pack
from admaker.db import lock_run_lease
from admaker.provider_graph import ReviewedCandidate


class CampaignPackNeedsReview(Exception):
    """Local pack retries are exhausted; preserve completed work and held credit."""


def finish_campaign_pack(database_url, run_id, owner, fence, source, settings, candidate, reviewer):
    root = Path(os.environ.get("LOCAL_ASSET_ROOT", ".local-assets")).resolve()
    identity = hashlib.sha256(json.dumps({"settings": settings, "source": source,
        "video": candidate.exports, "validation": candidate.validation}, sort_keys=True).encode()).hexdigest()

    def load(stage):
        with psycopg.connect(database_url) as c:
            lock_run_lease(c, run_id, owner, fence)
            row = c.execute("SELECT request_hash,result FROM app.job_stages WHERE run_id=%s AND stage_key=%s", (run_id, stage)).fetchone()
            if row and row[0] != identity:
                raise RuntimeError("Campaign stage inputs changed")
            return row[1] if row else None

    def save(stage, result):
        with psycopg.connect(database_url) as c:
            lock_run_lease(c, run_id, owner, fence)
            c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,%s,%s,%s,%s)", (run_id, stage, identity, Jsonb(result), fence))

    manifest = load("campaign_pack_compose")
    if manifest is None:
        failures = load("campaign_pack_failures") or {"count": 0}
        if failures["count"] >= 3:
            raise CampaignPackNeedsReview()
        try:
            from admaker.campaign_logo import stage_campaign_logo
            with psycopg.connect(database_url) as c:
                account_id = c.execute("SELECT j.owner_id FROM app.job_runs r JOIN app.jobs j ON j.id=r.job_id WHERE r.id=%s", (run_id,)).fetchone()[0]
                logo = stage_campaign_logo(c, account_id, settings["campaignBrief"], root)
            manifest = compose_campaign_pack(root, source, candidate.exports["tiktok"]["key"], settings["campaignBrief"], run_id,
                                             **({"logo": logo} if logo else {}))
        except (OSError, ValueError, subprocess.SubprocessError):
            failures["count"] += 1
            with psycopg.connect(database_url) as c:
                lock_run_lease(c, run_id, owner, fence)
                c.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'campaign_pack_failures',%s,%s,%s) ON CONFLICT (run_id,stage_key) DO UPDATE SET result=EXCLUDED.result,fence=EXCLUDED.fence", (run_id, identity, Jsonb(failures), fence))
            if failures["count"] >= 3:
                raise CampaignPackNeedsReview()
            return None
        save("campaign_pack_compose", manifest)
    from admaker.cloud_objects import publish_job_outputs, stage_private_object, CloudPublicationPending
    with psycopg.connect(database_url) as c:
        job_id, account_id = c.execute("SELECT r.job_id,j.owner_id FROM app.job_runs r JOIN app.jobs j ON j.id=r.job_id WHERE r.id=%s", (run_id,)).fetchone()
    try:
        if os.environ.get('PUBLISH_PRIVATE_OUTPUTS') == 'true':
            publish_job_outputs(database_url, job_id, root, manifest)
        else:
            for item in manifest.values():
                if isinstance(item, dict) and isinstance(item.get('key'), str):
                    stage_private_object(database_url, account_id, item['key'], root)
        require_available_pack(root, manifest)
    except (OSError, ValueError):
        raise CloudPublicationPending('Campaign media staging is unconfirmed') from None
    verdict = load("campaign_pack_review")
    if verdict is None:
        verdict = reviewer(root, manifest)
        if (not isinstance(verdict, dict) or not {"policyAllowed", "qualityPassed"} <= set(verdict)
                or not set(verdict) <= {"policyAllowed", "qualityPassed", "offerFree"}
                or any(type(value) is not bool for value in verdict.values())):
            raise subprocess.SubprocessError("Campaign review returned an invalid verdict")
        save("campaign_pack_review", verdict)
    if not verdict["policyAllowed"] or not candidate.validation["policyAllowed"]:
        raise subprocess.SubprocessError("Campaign review blocked the output")
    validation = {**candidate.validation,
        "qualityPassed": verdict["qualityPassed"] and candidate.validation["qualityPassed"],
        "exportsHash": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()}
    return ReviewedCandidate(manifest, validation)
