"""Keep explicitly admitted provider photos off the fixture/video queue."""
import os
import re

from fastapi import HTTPException
from admaker.consent import require_ai_consent


def photo_queue(settings, owner_id):
    if settings.get("photoProvider") is not True:
        from admaker.video_routing import video_queue
        return video_queue(settings, owner_id)
    queue = os.environ.get("PHOTO_QUEUE", "")
    if (settings.get("outputKind") != "photo" or os.environ.get("ENABLE_REAL_PHOTO") != "true"
            or os.environ.get("ENABLE_REAL_MEDIA_REVIEW") != "true"
            or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", queue)
            or queue in {"commands", os.environ.get("CAMPAIGN_PACK_QUEUE", "")}):
        raise HTTPException(503, "Photo generation is unavailable")
    try:
        require_ai_consent(owner_id)
    except PermissionError:
        raise HTTPException(403, "Current AI-processing permission is required") from None
    return queue
