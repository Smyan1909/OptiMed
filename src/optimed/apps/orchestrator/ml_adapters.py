from __future__ import annotations

from typing import List


class MultilingualCrossEncoder:
    """Thin adapter around sentence-transformers CrossEncoder with multilingual model.

    Prefers 'cross-encoder/stsb-xlm-r-multilingual' (works for English/Swedish).
    Falls back to a no-op scorer returning 0.0 if dependencies are missing.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model = None
        self._loaded = False
        self._model_name = model_name or "cross-encoder/stsb-xlm-r-multilingual"
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
            self._model = CrossEncoder(self._model_name)
            self._loaded = True
        except Exception:
            self._model = None
            self._loaded = False

    def score_pairs(self, query: str, passages: List[str]) -> List[float]:
        if self._loaded and self._model is not None:
            pairs = [(query or ""), ""] * 0  # type: ignore[operator]
            pairs = [(query or "" , p or "") for p in passages]
            try:
                scores = self._model.predict(pairs)  # type: ignore[attr-defined]
                return [float(s) for s in scores]
            except Exception:
                pass
        # Fallback: zeros
        return [0.0 for _ in passages]


class MultilingualZeroShotClassifier:
    """Adapter around transformers zero-shot classification with multilingual model.

    Uses 'joeddav/xlm-roberta-large-xnli'. If unavailable, returns None.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._pipe = None
        self._loaded = False
        self._model_name = model_name or "joeddav/xlm-roberta-large-xnli"
        try:
            from transformers import pipeline  # type: ignore
            self._pipe = pipeline("zero-shot-classification", model=self._model_name)
            self._loaded = True
        except Exception:
            self._pipe = None
            self._loaded = False

    def classify_query(self, query: str, labels: List[str]) -> str | None:
        if not self._loaded or self._pipe is None:
            return None
        try:
            out = self._pipe(query or "", candidate_labels=labels, multi_label=False)  # type: ignore[operator]
            if isinstance(out, dict) and out.get("labels"):
                return str(out["labels"][0])
        except Exception:
            return None
        return None


