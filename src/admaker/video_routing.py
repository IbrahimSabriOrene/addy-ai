"""Standalone video uses the existing Veo worker and its dedicated queue."""
import os
import re

from fastapi import HTTPException
from admaker.consent import require_ai_consent


def video_queue(settings, owner_id):
    if settings.get("videoProvider") is not True:
        return "commands"
    queue = os.environ.get("CAMPAIGN_PACK_QUEUE", "")
    if (settings.get("outputKind") != "video" or os.environ.get("ENABLE_REAL_VEO") != "true"
            or os.environ.get("ENABLE_REAL_MEDIA_REVIEW") != "true"
            or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", queue)
            or queue in {"commands", os.environ.get("PHOTO_QUEUE", "")}):
        raise HTTPException(503, "Video generation is unavailable")
    try:
        require_ai_consent(owner_id)
    except PermissionError:
        raise HTTPException(403, "Current AI-processing permission is required") from None
    return queue
