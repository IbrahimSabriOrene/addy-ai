# Addy AI

Personal media-workflow prototype by Ibrahim Sabri Örene. Python/LangGraph backend and a React Native/Expo client coordinate product-media generation with human checkpoints, durable state and bounded retries.

## Engineering scope

- Intake, style planning, human decisions, video/photo workflows and QA routing.
- Checkpoints, job/worker state, explicit retry and provider-cost controls.
- Deterministic offline services for graph testing.
- Application/API code, migrations and a mobile client.

**Prototype source release:** live paid-provider acceptance, physical-device checks and store/release validation remain separate gates. Included requirements or legal drafts are not claims of completed production controls. Example prices and fixtures are test data.

## Backend

Python 3.12 is required by the current package. FFmpeg is needed for local video fixtures; PostgreSQL is needed for database/worker paths.

```sh
python -m venv .venv
# Activate the environment, then:
pip install -e '.[dev]'
# Copy .env.example to .env and configure your own local services.
python -m pytest tests/test_graph_account.py
```

Database-backed checkpoint, worker and API tests require PostgreSQL. `docker compose up --build` provides the local development stack. Its example database password is for local development only. Real paid-provider execution is opt-in; keep the `ENABLE_REAL_*` flags off for offline exploration.

## Mobile source

```sh
cd mobile
npm ci
npm start
```

The export includes source code and locally created app-brand assets. Large demo videos, preview media, provider-result assets and native build outputs are intentionally omitted. Add your own licensed preview assets before testing gallery/media flows; do not interpret a missing preview as a live generated result. Legal/support destinations in the source are draft configuration, not a launched service.

## Public export

This is a fresh source-only snapshot. Original history, `.env`, API credentials, local media/storage, private research, provider results, release evidence, downloaded dependencies and personal session data are excluded. Source and tests include synthetic account/credential fixtures. Original local files were not modified.

Third-party dependencies keep their licenses. No new license grant has been selected for this source release.
