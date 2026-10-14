"""Resumable reserved video attempt. Provider selection remains outside the graph."""

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import TypedDict
from dataclasses import dataclass

import psycopg
import httpx
from langgraph.graph import START, END, StateGraph
from langgraph.types import Command, interrupt

from admaker.db import FencedPostgresSaver, lock_run_lease, postgres_checkpointer
from admaker.media import compose_video
from admaker.veo import submit_video_attempt, poll_video_attempt

PROVIDER_GRAPH_VERSION = "worker-provider-v2"


class ProviderState(TypedDict, total=False):
    identity: str
    operation: str
    raw: str | None
    exports: dict
    validation: dict


@dataclass(frozen=True)
class ReviewedCandidate:
    exports: dict
    validation: dict



def run_provider_graph(database_url, run_id, attempt_id, owner, fence, request,
                       estimated_cost_microusd, service, settings, output_id, platforms, reviewer):
    if not callable(reviewer):
        raise ValueError("A content reviewer is required before provider submission")
    if settings.get("preparedVideoPrompt") is not None and request.prompt != settings["preparedVideoPrompt"]:
        raise ValueError("Video request does not match the approved creative direction")
    root = Path(os.environ.get("LOCAL_ASSET_ROOT", ".local-assets")).resolve()
    identity = hashlib.sha256(json.dumps({"run": str(run_id), "attempt": str(attempt_id),
        "prompt": request.prompt, "model": request.model, "cost": estimated_cost_microusd,
        "settings": settings, "platforms": platforms}, sort_keys=True).encode()).hexdigest()
    with psycopg.connect(database_url) as connection:
        thread, version, account_id = connection.execute("SELECT r.thread_id,r.graph_version,j.owner_id FROM app.job_runs r JOIN app.jobs j ON j.id=r.job_id WHERE r.id=%s", (run_id,)).fetchone()
    if version != PROVIDER_GRAPH_VERSION:
        raise RuntimeError("Run requires a different graph version")
    if request.image_path is not None or request.image_bytes is not None:
        raise ValueError("The graph uses only the job's verified image")

    def ensure_stage_media(key, result):
        if key not in {'provider_download', 'provider_compose'}:
            return
        from admaker.cloud_objects import stage_private_object, publish_account_outputs, CloudPublicationPending
        manifest = {'raw': {'key': result['key'], 'mimeType': 'video/mp4'}} if key == 'provider_download' else result
        try:
            if os.environ.get('PUBLISH_PRIVATE_OUTPUTS') == 'true':
                publish_account_outputs(database_url, account_id, root, manifest)
            else:
                for item in manifest.values():
                    if isinstance(item, dict) and isinstance(item.get('key'), str):
                        stage_private_object(database_url, account_id, item['key'], root)
                        if 'sha256' in item:
                            path = (root / item['key']).resolve()
                            if not path.is_relative_to(root.resolve()) or not path.is_file() or not 0 < path.stat().st_size <= 100 * 1024 * 1024:
                                raise ValueError('Recorded output is unavailable')
                            with path.open('rb') as stream:
                                if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                                    raise ValueError('Recorded output has changed')
        except (OSError, ValueError):
            raise CloudPublicationPending('Provider media staging is unconfirmed') from None

    def saved_stage(key):
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            lock_run_lease(cursor, run_id, owner, fence)
            row = cursor.execute("SELECT request_hash,result FROM app.job_stages WHERE run_id=%s AND stage_key=%s", (run_id, key)).fetchone()
        if row and row[0] != identity:
            raise RuntimeError("Provider stage input changed")
        if row:
            ensure_stage_media(key, row[1])
        return row[1] if row else None

    def save_stage(key, result):
        with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
            lock_run_lease(cursor, run_id, owner, fence)
            cursor.execute("INSERT INTO app.job_stages(run_id,stage_key,request_hash,result,fence) VALUES (%s,%s,%s,%s,%s)",
                           (run_id, key, identity, psycopg.types.json.Jsonb(result), fence))
        ensure_stage_media(key, result)

    def submit(state):
        return {"operation": submit_video_attempt(database_url, attempt_id, owner, fence,
                    request, estimated_cost_microusd, service)}

    def poll(state):
        saved = saved_stage("provider_download")
        if saved:
            return {"raw": saved["key"]}
        with psycopg.connect(database_url) as connection:
            status = connection.execute("SELECT provider_state FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone()[0]
        if status == "failed":
            raise subprocess.SubprocessError("Generation returned no allowed output")
        try:
            operation = poll_video_attempt(database_url, attempt_id, owner, fence, service)
        except (TimeoutError, ConnectionError, httpx.TransportError):
            return {"raw": None}
        if operation is None:
            return {"raw": None}
        with psycopg.connect(database_url) as connection:
            status = connection.execute("SELECT provider_state FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone()[0]
        if status != "ready":
            raise subprocess.SubprocessError("Generation returned no allowed output")
        key = f"runs/{output_id}/raw.mp4"
        destination = root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            service.download(operation, str(destination))
        except (TimeoutError, ConnectionError, httpx.TransportError):
            return {"raw": None}
        save_stage("provider_download", {"key": key})
        return {"raw": key}

    def wait(state):
        interrupt({"kind": "provider_wait"})
        return {}

    def compose(state):
        exports = saved_stage("provider_compose")
        if exports is None:
            exports = compose_video(root / state["raw"], root, output_id, platforms)
            save_stage("provider_compose", exports)
        return {"exports": exports}

    def review(state):
        validation = saved_stage("candidate_review")
        if validation is None:
            verdict = reviewer(root, state["exports"])
            if (not isinstance(verdict, dict) or not {"policyAllowed", "qualityPassed"} <= set(verdict)
                    or not set(verdict) <= {"policyAllowed", "qualityPassed", "offerFree"}
                    or any(type(value) is not bool for value in verdict.values())):
                raise subprocess.SubprocessError("Content review returned an invalid verdict")
            with psycopg.connect(database_url) as connection:
                reservation = connection.execute("SELECT reservation_id FROM app.job_attempts WHERE id=%s", (attempt_id,)).fetchone()[0]
            validation = {**verdict, "technicalPassed": True, "reservationId": str(reservation),
                "exportsHash": hashlib.sha256(json.dumps(state["exports"], sort_keys=True).encode()).hexdigest()}
            # Optional trusted review: no offers/prices/CTA in either picture or speech.
            # Bind this stronger verdict to bytes, not only a reusable filename.
            if verdict.get("offerFree") is True:
                source = (root / state["exports"]["tiktok"]["key"]).resolve()
                if not source.is_relative_to(root.resolve()) or not source.is_file() or not 0 < source.stat().st_size <= 100 * 1024 * 1024:
                    raise subprocess.SubprocessError("Reviewed source is unavailable")
                validation["sourceSha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            save_stage("candidate_review", validation)
        if not validation["policyAllowed"]:
            raise subprocess.SubprocessError("Content review blocked the candidate")
        return {"validation": validation}

    builder = StateGraph(ProviderState)
    for name, node in (("submit", submit), ("poll", poll), ("wait", wait), ("compose", compose), ("review", review)):
        builder.add_node(name, node)
    builder.add_edge(START, "submit")
    builder.add_edge("submit", "poll")
    builder.add_conditional_edges("poll", lambda state: "compose" if state.get("raw") else "wait")
    builder.add_edge("wait", "poll")
    builder.add_edge("compose", "review")
    builder.add_edge("review", END)
    with postgres_checkpointer(database_url) as saver:
        graph = builder.compile(checkpointer=FencedPostgresSaver(saver.conn, run_id, owner, fence))
        config = {"configurable": {"thread_id": thread}}
        snapshot = graph.get_state(config)
        if snapshot.values and snapshot.values.get("identity") != identity:
            raise RuntimeError("Provider checkpoint identity mismatch")
        if snapshot.values.get('raw'):
            ensure_stage_media('provider_download', {'key': snapshot.values['raw']})
        if snapshot.values.get('exports'):
            ensure_stage_media('provider_compose', snapshot.values['exports'])
        value = Command(resume=True) if snapshot.interrupts else None if snapshot.created_at else {"identity": identity}
        result = graph.invoke(value, config=config, durability="sync")
    return None if result.get("__interrupt__") else ReviewedCandidate(result["exports"], result["validation"])
