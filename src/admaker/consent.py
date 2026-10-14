"""Versioned permission for transferring merchant media to Google AI."""
import os
import uuid

import psycopg

DISCLOSURE_VERSION = "google-media-2026-09-09-v3"
DISCLOSURE = (
    "To create and review your ad, Addy AI sends your selected product photos, "
    "campaign instructions, and generated images and videos (including sound) to "
    "Google for AI generation and content/quality checks. You can decline or withdraw permission "
    "to stop new transfers. Withdrawal cannot undo a transfer already submitted."
)


def require_ai_consent(account_id: str) -> None:
    from admaker.account_deletion import deletion_requested
    if deletion_requested(account_id):
        raise PermissionError("Account deletion has been requested")
    from admaker.eligibility import eligibility_status
    if not eligibility_status(account_id)["confirmed"]:
        raise PermissionError("Adult professional-use confirmation is required")
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        row = connection.execute(
            "SELECT granted,disclosure_version FROM app.ai_consent WHERE account_id=%s",
            (uuid.UUID(account_id),),
        ).fetchone()
    if not row or not row[0] or row[1] != DISCLOSURE_VERSION:
        raise PermissionError("Current AI-sharing consent is required")
