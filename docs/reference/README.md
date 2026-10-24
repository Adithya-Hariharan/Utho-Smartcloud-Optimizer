# Reference material for the engine and API owner

Nothing in the app imports these files. The frontend talks only to the backend API described in `frontend/API_CONTRACT.md`.

| File | What it is |
|---|---|
| `mock_engine.py` | A stand-in engine over `data/`. It covers cleaning (snap, sort, dedupe, out-of-range, flatline), features, sizing with the prod one-step rule, Peak Replay, vetoes, risk, options and formulas, alerts, what-if, scorecard, and the data-quality reconciliation. **Verdicts are copied from `truth.csv`**, so it is not a real engine. It is useful as a worked example of the response shapes and numbers. |
| `export_reference.ts` | How the CSV, Markdown and dry-run `apply.sh` exports were built in the browser before export moved to `POST /api/export`. |

`mock_engine.py` also writes the frontend's fallback data. The dev server serves it while the backend is down, and the browser tests use it:

```bash
.venv/Scripts/python docs/reference/mock_engine.py     # → frontend/fallback/api/
cd frontend && node scripts/check_fixtures.mjs   # validates frontend/fallback/api/
```

Known data issue in data commit 7b73730: `truth.csv` says the service group prod-web-11a/b/c should be resized. The busiest member (11b) needs 4.1 vCPU at the 70% prod CPU target. The next cheaper plan, B2, has 4 vCPU, so the sizing rules reject it (`NO_CHEAPER_PLAN`). Either the data or the truth label needs to change.
