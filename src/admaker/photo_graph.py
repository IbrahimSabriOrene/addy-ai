"""Durable photo generation/review using the existing reservation settlement path."""
import hashlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb
from PIL import Image, ImageOps
from langgraph.graph import START, END, StateGraph

from admaker.db import FencedPostgresSaver, lock_run_lease, postgres_checkpointer
from admaker.media_review import MediaVerdict, MediaReviewPending
from admaker.photo_attempt import generate_photo_attempt
from admaker.photo_provider import PHOTO_MODEL
from admaker.provider_graph import ProviderState, ReviewedCandidate


PHOTO_GRAPH_VERSION = "worker-photo-v1"


def materialize_photo(data, root, job_id, run_id, platforms):
    if not platforms or any(platform not in {"feed", "feed_square", "tiktok", "reels", "stories"} for platform in platforms):
        raise ValueError("Unsupported photo output platforms")
    exports = {}
    with Image.open(io.BytesIO(data)) as source:
        source = ImageOps.exif_transpose(source).convert("RGB")
        for platform in platforms:
            size = (1080, 1080) if platform in {"feed", "feed_square"} else (1080, 1920)
            image = ImageOps.pad(source, size, color="white")
            content = io.BytesIO()
            image.save(content, format="PNG")
            payload = content.getvalue()
            key = f"runs/{job_id}/{run_id}/photo_{platform}.png"
            target = root / key
            if not target.resolve().is_relative_to(root):
                raise ValueError("Photo output escapes private storage")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(payload)
                temporary.replace(target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            exports[platform] = {"key": key, "mimeType": "image/png", "caption": "",
                "width": size[0], "height": size[1], "sha256": hashlib.sha256(payload).hexdigest()}
    return exports


def run_photo_graph(database_url, run_id, attempt_id, owner, fence, settings, platforms, estimate, reviewer, generate):
    if settings.get("outputKind") != "photo" or settings.get("photoModel") != PHOTO_MODEL or not settings.get("preparedPhotoPrompt"):
        raise ValueError("A frozen photo request is required")
    identity = hashlib.sha256(json.dumps([str(run_id), str(attempt_id), settings, platforms, estimate], sort_keys=True).encode()).hexdigest()
    root = Path(os.environ.get("LOCAL_ASSET_ROOT", ".local-assets")).resolve()
    with psycopg.connect(database_url) as connection:
        thread, version, job_id, reservation = connection.execute("SELECT r.thread_id,r.graph_version,r.job_id,a.reservation_id FROM app.job_runs r JOIN app.job_attempts a ON a.run_id=r.id WHERE r.id=%s AND a.id=%s", (run_id, attempt_id)).fetchone()
    if version != PHOTO_GRAPH_VERSION:
        raise ValueError("Photo run requires another graph version")

    def render(state):
        data = generate_photo_attempt(database_url, attempt_id, owner, fence, settings["preparedPhotoPrompt"],
            "1:1" if all(p in {"feed", "feed_square"} for p in platforms) else "9:16", estimate, reviewer, generate=generate)
        exports = materialize_photo(data, root, job_id, run_id, platforms)
        with psycopg.connect(database_url) as connection:
            lock_run_lease(connection, run_id, owner, fence)
            previous = connection.execute("SELECT request_hash,result FROM app.job_stages WHERE run_id=%s AND stage_key='provider_compose'", (run_id,)).fetchone()
            if previous and previous != (identity, exports):
                raise MediaReviewPending("Previously composed photo changed")
            if not previous:
                connection.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'provider_compose',%s,%s,%s)", (run_id, identity, Jsonb(exports), fence))
            saved = connection.execute("SELECT request_hash,result FROM app.job_stages WHERE run_id=%s AND stage_key='candidate_review'", (run_id,)).fetchone()
        if saved:
            if saved[0] != identity:
                raise MediaReviewPending("Photo review identity changed")
            validation = saved[1]
        else:
            try:
                verdict = MediaVerdict.model_validate(reviewer(root, exports)).model_dump()
            except ValueError:
                raise MediaReviewPending("Photo review did not return a valid verdict") from None
            validation = {**verdict, "technicalPassed": True, "reservationId": str(reservation),
                "exportsHash": hashlib.sha256(json.dumps(exports, sort_keys=True).encode()).hexdigest()}
            with psycopg.connect(database_url) as connection:
                lock_run_lease(connection, run_id, owner, fence)
                connection.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,'candidate_review',%s,%s,%s)", (run_id, identity, Jsonb(validation), fence))
        if not validation["policyAllowed"]:
            raise subprocess.SubprocessError("Content review blocked the photo")
        return {"exports": exports, "validation": validation}

    builder = StateGraph(ProviderState)
    builder.add_node("render", render)
    builder.add_edge(START, "render")
    builder.add_edge("render", END)
    with postgres_checkpointer(database_url) as saver:
        graph = builder.compile(checkpointer=FencedPostgresSaver(saver.conn, run_id, owner, fence))
        config = {"configurable": {"thread_id": thread}}
        saved = graph.get_state(config)
        if saved.values and saved.values.get("identity") != identity:
            raise MediaReviewPending("Photo checkpoint identity changed")
        result = graph.invoke(None if saved.created_at else {"identity": identity}, config=config, durability="sync")
    # A completed checkpoint may outlive local cache files after publication failure.
    with psycopg.connect(database_url) as connection:
        lock_run_lease(connection, run_id, owner, fence)
        data, checksum = connection.execute("SELECT data,checksum FROM app.photo_attempt_outputs WHERE attempt_id=%s", (attempt_id,)).fetchone()
        if hashlib.sha256(data).hexdigest() != checksum or materialize_photo(data, root, job_id, run_id, platforms) != result["exports"]:
            raise MediaReviewPending("Persisted photo changed before delivery")
    return ReviewedCandidate(result["exports"], result["validation"])
