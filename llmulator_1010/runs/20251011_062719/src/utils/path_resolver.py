import os
from typing import Dict, List


def _exists(p: str) -> bool:
    try:
        return os.path.exists(p)
    except Exception:
        return False


def get_base_model_path(cfg: Dict) -> str:
    """
    Resolve a usable base model path/name, preferring:
    1) env LLMULATOR_BASE_MODEL
    2) cfg["llm"]["base_model"] if exists
    3) first existing path in cfg["llm"]["candidate_paths"]
    Returns the chosen string (can be a local path or a HF model id).
    """
    env_val = os.environ.get("LLMULATOR_BASE_MODEL", "").strip()
    if env_val:
        return env_val

    llm = cfg.get("llm", {})
    base = (llm.get("base_model") or "").strip()
    if base:
        # If it exists locally, use it; otherwise return as-is (could be a HF id)
        return base

    # Probe candidates
    candidates: List[str] = llm.get("candidate_paths", []) or []
    for cand in candidates:
        if _exists(cand):
            return cand

    # Fallback to a reasonable small public model name if nothing else is set
    # Users can override with env or config
    return llm.get("fallback_model", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")

