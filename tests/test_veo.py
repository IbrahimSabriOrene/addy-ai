import pytest

from admaker.veo import VeoService


def test_real_veo_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_REAL_VEO", raising=False)
    with pytest.raises(RuntimeError, match="disabled"):
        VeoService()
