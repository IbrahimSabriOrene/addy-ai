from admaker.state import additive_merge, keyed_merge


def test_keyed_merge_unions_across_keys():
    assert keyed_merge({"a": "1"}, {"b": "2"}) == {"a": "1", "b": "2"}


def test_keyed_merge_right_wins_per_key():
    assert keyed_merge({"a": "1"}, {"a": "2"}) == {"a": "2"}


def test_keyed_merge_handles_none():
    assert keyed_merge(None, {"a": "1"}) == {"a": "1"}
    assert keyed_merge({"a": "1"}, None) == {"a": "1"}


def test_additive_merge_adds_same_key():
    # Attempt/cost counters must ADD across concurrent writes, not overwrite —
    # a late webhook resume that also spent money must not erase the tally.
    assert additive_merge({"video_gen": 2}, {"video_gen": 1}) == {"video_gen": 3}


def test_additive_merge_unions_across_keys():
    assert additive_merge({"video_gen": 1}, {"cleanup": 5}) == {
        "video_gen": 1,
        "cleanup": 5,
    }


def test_additive_merge_handles_none():
    assert additive_merge(None, {"video_gen": 1}) == {"video_gen": 1}
    assert additive_merge({"video_gen": 1}, None) == {"video_gen": 1}


def test_additive_merge_non_numeric_falls_back_to_right_wins():
    assert additive_merge({"k": "a"}, {"k": "b"}) == {"k": "b"}
