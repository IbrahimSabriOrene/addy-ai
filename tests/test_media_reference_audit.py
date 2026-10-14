import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("audit_media", Path(__file__).parents[1] / "tools/audit_media_references.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_reference_audit_covers_history_and_rejects_missing_empty_escape(tmp_path):
    (tmp_path / "valid.png").write_bytes(b"image")
    (tmp_path / "empty.png").touch()

    class Connection:
        def execute(self, query):
            if "app.assets" in query:
                return [("valid", "valid.png"), ("missing", "missing.png"), ("escape", "../escape.png")]
            if "campaign_layouts" in query:
                return [("campaign", 1, {"story": {"key": "empty.png"}, "feed": {}})]
            return [("job", {"exports": {"feed": {"key": "valid.png"}}, "runs": {"1": {"exports": {"reels": {"key": "old.mp4"}}}}})]

    report = audit.inspect_references(Connection(), tmp_path)
    assert report["references"] == 7
    assert not report["ok"]
    assert {item["reason"] for item in report["issues"]} == {"missing_file", "outside_storage_root", "empty_file", "invalid_key"}
    assert any(item["reference"] == "job:job:1:reels" for item in report["issues"])
    assert (tmp_path / "valid.png").read_bytes() == b"image"
