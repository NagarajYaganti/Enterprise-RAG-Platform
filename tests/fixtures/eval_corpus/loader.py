from pathlib import Path
from typing import Any

import yaml
from retrieval.eval import GoldenQuery

EVAL_CORPUS_DIR = Path(__file__).resolve().parent


def load_eval_documents() -> list[dict[str, Any]]:
    content = yaml.safe_load((EVAL_CORPUS_DIR / "documents.yaml").read_text())
    documents: list[dict[str, Any]] = content["documents"]
    return documents


def load_golden_queries() -> list[GoldenQuery]:
    content = yaml.safe_load((EVAL_CORPUS_DIR / "golden_queries.yaml").read_text())
    return [
        GoldenQuery(query=entry["query"], relevant_chunk_ids=entry["relevant_chunk_ids"])
        for entry in content["golden_queries"]
    ]
