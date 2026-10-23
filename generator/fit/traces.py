"""Load the mirrored public traces (Arrow IPC stream files written by HF `datasets`)."""
import json
from pathlib import Path

import numpy as np
import pyarrow as pa

EXTERNAL = Path(__file__).resolve().parents[2] / "data" / "external"
SCHEMA = Path(__file__).resolve().parent / "trace_schema.json"


def read_table(key):
    with pa.memory_map(str(EXTERNAL / f"{key}.arrow")) as src:
        return pa.ipc.open_stream(src).read_all()


def items(key, limit=None, rng=None, sample=None):
    """Yield dicts: item_id, start (numpy datetime64), freq, channels {name: float array}.
    Channel names come from trace_schema.json; unknown channels are skipped."""
    schema = json.loads(SCHEMA.read_text())[key]
    t = read_table(key)
    idx = np.arange(t.num_rows)
    if sample is not None and sample < len(idx):
        idx = np.sort(rng.choice(idx, sample, replace=False))
    if limit is not None:
        idx = idx[:limit]
    for i in idx:
        row = t.slice(int(i), 1).to_pylist()[0]
        ch = {}
        for field in ("target", "past_feat_dynamic_real"):
            arr = row.get(field)
            if arr is None:
                continue
            arr = np.atleast_2d(np.asarray(arr, dtype=float)) if field == "past_feat_dynamic_real" else \
                np.asarray(arr, dtype=float)
            if arr.ndim == 1:
                arr = arr[None, :]
            for j, vec in enumerate(arr):
                meaning = schema["channels"].get(f"{field}[{j}]", {}).get("meaning", "unknown")
                if meaning != "unknown":
                    ch[meaning] = np.asarray(vec, dtype=float)
        yield {"item_id": row["item_id"], "start": np.datetime64(row["start"]), "freq": row["freq"],
               "channels": ch}
