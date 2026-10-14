"""Read-only release evidence checklist. This is not a legal certification or geofence."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

EVIDENCE = (
    "legal_review", "provider_contracts_and_paid_project", "international_transfers",
    "retention_and_erasure_rehearsal", "privacy_requests_and_incident_rehearsal",
    "age_assurance_assessment", "ai_output_provenance", "native_store_privacy_and_billing",
)


def check_readiness(config, root):
    problems = []
    if config.get("status") != "reviewed":
        problems.append("Documents and launch are still in draft review.")
    operator = config.get("operator", {})
    for field in ("name", "country", "address", "privacyEmail"):
        if not isinstance(operator.get(field), str) or not operator[field].strip():
            problems.append(f"Missing operator.{field}.")
    for name in ("privacy", "terms", "refunds"):
        value = config.get("documents", {}).get(name, "")
        url = urlsplit(value) if isinstance(value, str) else urlsplit("")
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.hostname in {"localhost", "example.com"} or url.hostname.endswith((".test", ".invalid")):
            problems.append(f"Missing published HTTPS {name} destination.")
    root = Path(root).resolve()

    def evidence_exists(value):
        if not isinstance(value, str) or not value.strip():
            return False
        path = (root / value).resolve()
        return path.is_relative_to(root) and path.is_file() and path.stat().st_size > 0

    for key in EVIDENCE:
        if not evidence_exists(config.get("evidence", {}).get(key)):
            problems.append(f"Missing evidence: {key}.")
    markets = config.get("markets", [])
    if not isinstance(markets, list) or not markets:
        problems.append("No reviewed launch markets selected.")
    else:
        for market in markets:
            if (not isinstance(market, dict) or not isinstance(market.get("country"), str)
                    or len(market["country"]) != 2 or not market["country"].isascii()
                    or not market["country"].isupper() or not market["country"].isalpha()
                    or not evidence_exists(market.get("review"))):
                problems.append("Each launch country needs a country code and its own review evidence.")
    return {"checklistComplete": not problems, "legalCertification": False, "blockers": problems}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        result = check_readiness(json.loads(args.config.read_text(encoding="utf-8")), args.config.parent)
    except (OSError, ValueError, TypeError, AttributeError):
        result = {"checklistComplete": False, "legalCertification": False, "blockers": ["Readiness configuration could not be validated."]}
    print(json.dumps(result))
    return 0 if result["checklistComplete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
