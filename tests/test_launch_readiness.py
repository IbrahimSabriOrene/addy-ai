from admaker.launch_readiness import EVIDENCE, check_readiness


def test_missing_or_outside_evidence_and_unreviewed_markets_fail_closed(tmp_path):
    assert check_readiness({}, tmp_path)["checklistComplete"] is False
    (tmp_path / "review.txt").write_text("Test evidence placeholder; not a real legal review.")
    config = {"status": "reviewed", "operator": {key: "test" for key in ("name", "country", "address", "privacyEmail")},
              "documents": {key: "https://legal.example.org/" + key for key in ("privacy", "terms", "refunds")},
              "evidence": {key: "review.txt" for key in EVIDENCE},
              "markets": [{"country": "US", "review": "review.txt"}]}
    result = check_readiness(config, tmp_path)
    assert result["checklistComplete"] is True and result["legalCertification"] is False
    config["evidence"]["ai_output_provenance"] = "../outside.txt"
    assert check_readiness(config, tmp_path)["checklistComplete"] is False
    config["evidence"]["ai_output_provenance"] = "review.txt"
    config["markets"] = [{"country": "TR", "review": ""}]
    assert check_readiness(config, tmp_path)["checklistComplete"] is False
    config["markets"] = [{"country": "TR", "review": "review.txt"}]
    config["documents"]["privacy"] = "https://placeholder.invalid/privacy"
    assert check_readiness(config, tmp_path)["checklistComplete"] is False
