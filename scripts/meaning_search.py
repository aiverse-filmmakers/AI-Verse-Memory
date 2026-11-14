"""Optional meaning search for recall: a small local model, blended with word search.

Off until the member turns it on (`memory.py meaning enable`), because the model is a
download (about 130 MB for the default). Everything runs on this computer; nothing is
sent anywhere. Vectors live in the throwaway SQLite index and are rebuilt when a memory
changes. If the model or its library is missing or fails, recall silently stays word only.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
CONFIG_NAME = "meaning-search.json"
MAX_NEW_VECTORS_PER_RECALL = 400
MEANING_CANDIDATES = 20
RRF_K = 60

# Tests (and a future engine) can replace this with any texts -> vectors callable.
EMBEDDER: Optional[Callable[[Sequence[str]], List[List[float]]]] = None
_LOADED: Dict[str, Callable[[Sequence[str]], List[List[float]]]] = {}


def config_path(db_path: Path) -> Path:
    return Path(db_path).parent / CONFIG_NAME


def model_dir(db_path: Path) -> Path:
    """Kept next to the Memory index, not in a temporary folder the system clears."""
    return Path(db_path).parent / "meaning-model"


def read_config(db_path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(config_path(db_path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_config(db_path: Path, enabled: bool, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    data = {"schema_version": 1, "enabled": bool(enabled), "model": model}
    path = config_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return data


def library_available() -> bool:
    try:
        import fastembed  # noqa: F401
        return True
    except Exception:
        return False


def embedder(model: str, cache_dir: Optional[Path] = None) -> Optional[Callable[[Sequence[str]], List[List[float]]]]:
    if EMBEDDER is not None:
        return EMBEDDER
    if model in _LOADED:
        return _LOADED[model]
    try:
        from fastembed import TextEmbedding
        options = {"model_name": model}
        if cache_dir is not None:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            options["cache_dir"] = str(cache_dir)
        engine = TextEmbedding(**options)
    except Exception:
        return None

    def run(texts: Sequence[str]) -> List[List[float]]:
        return [list(map(float, v)) for v in engine.embed(list(texts))]

    _LOADED[model] = run
    return run


def _pack(vector: Sequence[float]) -> bytes:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return struct.pack(f"{len(vector)}f", *[x / norm for x in vector])


def _unpack(blob: bytes) -> List[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def _fingerprint(model: str, text: str) -> str:
    return hashlib.sha256((model + "\0" + text).encode("utf-8")).hexdigest()


def _ensure_table(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS item_vectors (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, vec BLOB NOT NULL)")


def _texts(row) -> str:
    tags = " ".join(t.lstrip("~") for t in str(row["tags"] or "").split(",") if t)
    return f"{row['text']} {tags}".strip()[:2000]


def blend(conn, db_path: Path, query: str, word_ranked: List[Any], candidate_sql: str, params: List[Any],
          limit: int, valid: Callable[[Any], bool] = lambda row: True) -> List[Any]:
    """Return word_ranked unchanged unless meaning search is on and working; then fuse both rankings."""
    config = read_config(db_path)
    if not config.get("enabled"):
        return word_ranked
    model = str(config.get("model") or DEFAULT_MODEL)
    embed = embedder(model, model_dir(db_path))
    if embed is None or not query.strip():
        return word_ranked
    try:
        _ensure_table(conn)
        rows = [row for row in conn.execute(candidate_sql, params).fetchall() if valid(row)]
        if not rows:
            return word_ranked
        stored = {r["id"]: (r["fingerprint"], r["vec"]) for r in conn.execute("SELECT id, fingerprint, vec FROM item_vectors")}
        missing = [row for row in rows if stored.get(row["id"], (None,))[0] != _fingerprint(model, _texts(row))]
        missing = missing[:MAX_NEW_VECTORS_PER_RECALL]
        if missing:
            vectors = embed([_texts(row) for row in missing])
            for row, vector in zip(missing, vectors):
                fingerprint, blob = _fingerprint(model, _texts(row)), _pack(vector)
                conn.execute("INSERT OR REPLACE INTO item_vectors(id, fingerprint, vec) VALUES (?,?,?)", (row["id"], fingerprint, blob))
                stored[row["id"]] = (fingerprint, blob)
            conn.commit()
        query_vec = _unpack(_pack(embed([query])[0]))
        scored = []
        for row in rows:
            entry = stored.get(row["id"])
            if not entry:
                continue
            vec = _unpack(entry[1])
            if len(vec) != len(query_vec):
                continue
            scored.append((sum(a * b for a, b in zip(vec, query_vec)), row))
        scored.sort(key=lambda item: -item[0])
        meaning_ranked = [row for _score, row in scored[:MEANING_CANDIDATES]]
    except Exception:
        return word_ranked
    fused: Dict[str, float] = {}
    by_id: Dict[str, Any] = {}
    for rank, row in enumerate(word_ranked):
        fused[row["id"]] = fused.get(row["id"], 0.0) + 1.0 / (RRF_K + rank + 1)
        by_id[row["id"]] = row
    for rank, row in enumerate(meaning_ranked):
        fused[row["id"]] = fused.get(row["id"], 0.0) + 1.0 / (RRF_K + rank + 1)
        by_id.setdefault(row["id"], row)
    ordered = sorted(by_id.values(), key=lambda row: (row["kind"] != "memory", -fused[row["id"]]))
    return ordered[: max(1, min(50, limit))]
