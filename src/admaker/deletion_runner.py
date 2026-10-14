"""Run admitted local-storage deletion phases; retention completion is separate."""
import argparse
import json
import os
import uuid

from admaker.delete_application import delete_requested_application_data
from admaker.delete_billing_data import minimize_deleted_account_billing
from admaker.delete_identity import delete_requested_identity
from admaker.delete_media import delete_requested_media
from admaker.cloud_objects import delete_requested_cloud_objects
from admaker.review_files import delete_requested_review_files


def run_account_deletion(database_url, account_id, root, *, client=None):
    account_id = uuid.UUID(str(account_id))
    review_files = delete_requested_review_files(database_url, account_id)
    if review_files["state"] == "waiting_for_writers":
        return review_files
    cloud = delete_requested_cloud_objects(database_url, account_id)
    if cloud["state"] == "waiting_for_writers":
        return cloud
    # Remove owned media before identity; retain ownership rows until both succeed.
    media = delete_requested_media(database_url, account_id, root)
    if media["state"] == "waiting_for_writers":
        return media
    delete_requested_identity(database_url, account_id, client=client)
    minimize_deleted_account_billing(database_url, account_id)
    application = delete_requested_application_data(database_url, account_id)
    if application["state"] == "waiting_for_writers":
        return application
    return {"state": "retention_pending"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("account_id", type=uuid.UUID)
    parser.add_argument("--root", required=True, help="Private local storage root")
    args = parser.parse_args()
    try:
        result = run_account_deletion(os.environ["DATABASE_URL"], args.account_id, args.root)
    except Exception:
        # DB/transport exceptions can contain credentials or private payloads.
        print(json.dumps({"state": "unconfirmed", "action": "Check configuration and retry the same account"}))
        return 1
    print(json.dumps(result))
    return 0 if result["state"] == "retention_pending" else 2


if __name__ == "__main__":
    raise SystemExit(main())
