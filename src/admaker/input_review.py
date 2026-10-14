"""Fenced input policy gate before any reserved video submission."""
import hashlib
import json
import subprocess

import psycopg
from psycopg.types.json import Jsonb

from admaker.db import lock_run_lease
from admaker.media_review import MediaReviewPending, MediaVerdict, REVIEW_INSTRUCTIONS
from admaker.veo import read_video_image


def require_reviewed_input(database_url, run_id, owner, fence, root, source, prompt, reviewer):
    root = root.resolve()
    path = (root / source).resolve()
    if not path.is_relative_to(root) or not isinstance(prompt, str) or not 1 <= len(prompt) <= 4000:
        raise MediaReviewPending("Input review fields are invalid")
    manifest = {"input": {"key": source, "instructions": prompt}}
    digest = hashlib.sha256(json.dumps([manifest, REVIEW_INSTRUCTIONS,
        hashlib.sha256(read_video_image(path)).hexdigest()], sort_keys=True).encode()).hexdigest()
    with psycopg.connect(database_url) as connection:
        lock_run_lease(connection, run_id, owner, fence)
        previous = connection.execute("SELECT request_hash FROM app.job_stages WHERE run_id=%s AND stage_key='input_media'", (run_id,)).fetchone()
        if previous and previous[0] != digest:
            raise MediaReviewPending("Previously reviewed input changed")
        if not previous:
            connection.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'input_media',%s,%s,%s)", (run_id, digest, Jsonb(manifest), fence))
        saved = connection.execute("SELECT request_hash,result FROM app.job_stages WHERE run_id=%s AND stage_key='input_content_review'", (run_id,)).fetchone()
        if saved and saved[0] != digest:
            raise MediaReviewPending("Input review binding changed")
    if saved:
        verdict = saved[1]
    else:
        try:
            verdict = MediaVerdict.model_validate(reviewer(root, manifest)).model_dump()
        except ValueError:
            raise MediaReviewPending("Input review returned an invalid verdict") from None
        with psycopg.connect(database_url) as connection:
            lock_run_lease(connection, run_id, owner, fence)
            connection.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'input_content_review',%s,%s,%s)", (run_id, digest, Jsonb(verdict), fence))
    if verdict.get("policyAllowed") is not True:
        raise subprocess.SubprocessError("Input content policy blocked generation")
