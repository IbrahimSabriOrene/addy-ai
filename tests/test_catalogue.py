import pytest

from admaker.catalogue import catalogue_items, require_template
from admaker.presets import PRESETS


def test_editor_video_scenes_have_independent_ids_and_motion_instructions():
    from admaker.job_prompts import prepare_video_prompt
    for scene in ("lifestyle", "studio", "minimal", "editorial"):
        template = require_template("editor_" + scene + "_video", 1, "video")
        prompt = prepare_video_prompt(template["prompt"])
        assert "slow camera push-in" in prompt
        assert "without speech" in prompt
        assert "eight-second vertical video" in prompt
        assert len(prompt) <= 4000
        with pytest.raises(ValueError):
            require_template("editor_" + scene + "_video", 1, "photo")


def test_editor_scenes_are_private_versioned_photo_edits():
    from admaker.job_prompts import prepare_photo_prompt

    ids = {"editor_lifestyle", "editor_studio", "editor_minimal", "editor_editorial"}
    public = {item["id"]: item for item in catalogue_items(output_kind="photo")}
    prepared = []
    for template_id in ids:
        assert "prompt" not in public[template_id]
        assert public[template_id]["validated"] is False
        template = require_template(template_id, 1, "photo")
        prompt = prepare_photo_prompt(template["prompt"])
        assert "{product}" not in prompt
        assert "reference product count" in prompt
        assert "not the product design" in prompt
        assert len(prompt) <= 4000
        prepared.append(prompt)
        with pytest.raises(ValueError):
            require_template(template_id, 1, "video")
        with pytest.raises(ValueError):
            require_template(template_id, 2, "photo")
    assert len(set(prepared)) == 4
    assert not ids.intersection(item["id"] for item in catalogue_items(output_kind="video"))


def test_catalogue_preserves_ids_hides_prompts_and_rejects_invalid_selection():
    items = catalogue_items("beauty", "photo")
    assert set(PRESETS) <= {item["id"] for item in catalogue_items()}
    assert len(catalogue_items()) == 29
    assert "fresh_pour" not in {item["id"] for item in items}
    assert "clean_studio" in {item["id"] for item in items}
    assert all("food" in item["categories"] for item in catalogue_items("food"))
    assert all("prompt" not in item and item["validated"] is False for item in items)
    items[0]["outputKinds"].clear()
    assert catalogue_items()[0]["outputKinds"]
    assert require_template("pedestal_spin", 1, "video")["prompt"]
    for selection in (("missing", 1, "video"), ("pedestal_spin", 2, "video"), ("pedestal_spin", 1, "pack"), ("fresh_pour", 1, "photo"), ("clean_studio", 1, "video")):
        with pytest.raises(ValueError):
            require_template(*selection)
    with pytest.raises(ValueError):
        catalogue_items("missing")
