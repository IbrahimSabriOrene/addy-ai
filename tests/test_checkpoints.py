import uuid

from admaker.db import postgres_checkpointer
from admaker.graph import build_graph


def test_postgres_checkpoint_survives_new_saver(harness) -> None:
    database_url = "postgresql://postgres:postgres@localhost:54322/postgres"
    thread_id = f"checkpoint-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}
    with postgres_checkpointer(database_url) as saver:
        app = build_graph(
            harness.runners,
            checkpointer=saver,
            image_probe=harness.probe,
            image_cleaner=harness.cleaner,
            video_service=harness.video,
            compositor=harness.compositor,
            asset_store=harness.store,
            sleep=lambda _: None,
        )
        app.invoke({"job_id": thread_id, "source_image_url": "https://example.com/shoe.png", "fast_mode": True, "target_platforms": ["tiktok"]}, config=config)
    with postgres_checkpointer(database_url) as saver:
        checkpoint = saver.get_tuple(config)
    assert checkpoint is not None
    assert checkpoint.checkpoint["channel_values"]["job_id"] == thread_id
