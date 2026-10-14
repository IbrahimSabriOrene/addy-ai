"""Unexpected worker failures must not print private exception payloads."""
import traceback

import pytest

from admaker import photo_worker, provider_worker, worker


@pytest.mark.parametrize("module", [photo_worker, provider_worker, worker])
def test_worker_entrypoint_hides_unexpected_error(module, monkeypatch, capsys):
    marker = "PRIVATE_WORKER_FIXTURE_MARKER"

    def fail(*args, **kwargs):
        raise KeyError(marker)

    monkeypatch.setattr("sys.argv", ["worker", "--once"])
    if module is worker:
        monkeypatch.setattr(worker, "database_ready", lambda _: True)
        monkeypatch.setattr("admaker.billing.process_pending_billing", fail)
    else:
        monkeypatch.setattr(module, "photo_worker_configuration" if module is photo_worker else "provider_worker_configuration", fail)
    with pytest.raises(SystemExit) as caught:
        module.main()
    assert caught.value.code not in (None, 0)
    output = capsys.readouterr()
    assert marker not in output.out + output.err + "".join(traceback.format_exception(caught.value))
