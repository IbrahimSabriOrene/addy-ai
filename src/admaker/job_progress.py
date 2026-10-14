"""Public progress from the owned active run; no prompts or provider IDs escape."""


def generation_stage(connection, job_id, account_id):
    row = connection.execute("""
        SELECT ARRAY(SELECT stage_key FROM app.job_stages WHERE run_id=r.id),
               (SELECT provider_state FROM app.job_attempts WHERE run_id=r.id
                ORDER BY sequence DESC LIMIT 1)
        FROM app.jobs j JOIN app.job_runs r ON r.id=j.active_run_id AND r.job_id=j.id
        WHERE j.id=%s AND j.owner_id=%s AND j.state='running'
        """, (job_id, account_id)).fetchone()
    if not row:
        return None
    stages, provider = row
    for key, stage in (("candidate_review", "reviewed"), ("provider_compose", "composed")):
        if key in stages:
            return stage
    if provider == "ready":
        return "generated"
    if provider in {"submitting", "submitted"}:
        return "generating"
    if provider in {"failed", "submission_unknown"}:
        return None
    if "input_media" in stages:
        return "input_review"
    if "creative_plan_request" in stages:
        return "planning"
    return None
