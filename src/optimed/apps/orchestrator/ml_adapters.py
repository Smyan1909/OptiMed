from __future__ import annotations

from typing import List


class MultilingualCrossEncoder:
    """Thin adapter around sentence-transformers CrossEncoder with BAAI/bge-reranker-v2-m3.

    Uses only 'BAAI/bge-reranker-v2-m3' (high-quality reranking model).
    Applies sigmoid normalization to convert raw logits to [0, 1] range for compatibility with bi-encoder scores.
    Falls back to sigmoid-based heuristic scoring if model loading fails.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model = None
        self._loaded = False
        self._model_name = model_name or "BAAI/bge-reranker-v2-m3"
        
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
            print(f"[MultilingualCrossEncoder] Loading model: {self._model_name}")
            self._model = CrossEncoder(self._model_name)
            self._loaded = True
            print(f"[MultilingualCrossEncoder] Successfully loaded model: {self._model_name}")
        except Exception as e:
            print(f"[MultilingualCrossEncoder] Failed to load model {self._model_name}: {e}")
            self._model = None
            self._loaded = False

    def score_pairs(self, query: str, passages: List[str]) -> List[float]:
        print(f"[MultilingualCrossEncoder] score_pairs called with query: '{query[:50]}...' and {len(passages)} passages")
        print(f"[MultilingualCrossEncoder] Model loaded: {self._loaded}, Model exists: {self._model is not None}")
        
        if self._loaded and self._model is not None:
            pairs = [(query or "" , p or "") for p in passages]
            print(f"[MultilingualCrossEncoder] Created {len(pairs)} pairs for scoring")
            try:
                # Get raw logits from the model
                raw_scores = self._model.predict(pairs)  # type: ignore[attr-defined]
                print(f"[MultilingualCrossEncoder] Raw scores: {raw_scores}")
                
                # Apply sigmoid normalization to convert logits to [0, 1] range
                import math
                normalized_scores = []
                for score in raw_scores:
                    # Apply sigmoid: 1 / (1 + e^(-x))
                    sigmoid_score = 1 / (1 + math.exp(-float(score)))
                    normalized_scores.append(sigmoid_score)
                
                # Log score statistics for debugging
                if normalized_scores:
                    min_score = min(normalized_scores)
                    max_score = max(normalized_scores)
                    avg_score = sum(normalized_scores) / len(normalized_scores)
                    print(f"[MultilingualCrossEncoder] Score range: [{min_score:.4f}, {max_score:.4f}], avg: {avg_score:.4f}")
                
                print(f"[MultilingualCrossEncoder] Normalized scores (sigmoid): {normalized_scores}")
                return normalized_scores
            except Exception as e:
                print(f"[MultilingualCrossEncoder] Error during prediction: {e}, using heuristic fallback")
                return self._heuristic_score(query, passages)
        else:
            print(f"[MultilingualCrossEncoder] Using heuristic fallback")
            return self._heuristic_score(query, passages)
    
    def _heuristic_score(self, query: str, passages: List[str]) -> List[float]:
        """Heuristic scoring using sigmoid function based on word overlap.
        
        Returns scores in the range [0.0, 1.0] using sigmoid transformation.
        """
        import math
        
        if not query or not passages:
            return [0.0 for _ in passages]
        
        query_words = set(query.lower().split())
        scores = []
        
        for passage in passages:
            if not passage:
                scores.append(0.0)
                continue
            
            passage_words = set(passage.lower().split())
            
            # Calculate word overlap
            overlap = len(query_words.intersection(passage_words))
            total_words = len(query_words.union(passage_words))
            
            if total_words == 0:
                scores.append(0.0)
            else:
                # Jaccard similarity
                jaccard = overlap / total_words
                
                # Apply sigmoid function: sigmoid(x) = 1 / (1 + e^(-x))
                # Scale jaccard to a reasonable range for sigmoid (multiply by 6 to get good spread)
                x = jaccard * 6
                sigmoid_score = 1 / (1 + math.exp(-x))
                scores.append(float(sigmoid_score))
        
        print(f"[MultilingualCrossEncoder] Heuristic scores (sigmoid): {scores}")
        return scores


class MultilingualZeroShotClassifier:
    """Adapter around transformers zero-shot classification with multilingual model.

    Uses 'joeddav/xlm-roberta-large-xnli'. If unavailable, returns None.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._pipe = None
        self._loaded = False
        self._model_name = model_name or "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
        
        # Try multiple models in order of preference
        model_candidates = [
            self._model_name,
            "facebook/bart-large-mnli",  # Smaller, faster model
            "typeform/distilbert-base-uncased-mnli",  # Even smaller fallback
        ]
        
        for candidate_model in model_candidates:
            try:
                from transformers import pipeline  # type: ignore
                print(f"[MultilingualZeroShotClassifier] Trying to load model: {candidate_model}")
                self._pipe = pipeline("zero-shot-classification", model=candidate_model)
                self._model_name = candidate_model
                self._loaded = True
                print(f"[MultilingualZeroShotClassifier] Successfully loaded model: {candidate_model}")
                break
            except Exception as e:
                print(f"[MultilingualZeroShotClassifier] Failed to load model {candidate_model}: {e}")
                continue
        
        if not self._loaded:
            print(f"[MultilingualZeroShotClassifier] All model loading attempts failed")
            self._pipe = None

    def classify_query(self, query: str, labels: List[str]) -> str | None:
        print(f"[MultilingualZeroShotClassifier] classify_query called with query: '{query[:50]}...' and labels: {labels}")
        print(f"[MultilingualZeroShotClassifier] Model loaded: {self._loaded}, Pipeline exists: {self._pipe is not None}")
        
        if not self._loaded or self._pipe is None:
            print(f"[MultilingualZeroShotClassifier] Model not loaded, using heuristic fallback")
            return self._heuristic_classify(query, labels)
        try:
            out = self._pipe(query or "", candidate_labels=labels, multi_label=False)  # type: ignore[operator]
            print(f"[MultilingualZeroShotClassifier] Pipeline output: {out}")
            if isinstance(out, dict) and out.get("labels"):
                result = str(out["labels"][0])
                print(f"[MultilingualZeroShotClassifier] Returning classification: {result}")
                return result
        except Exception as e:
            print(f"[MultilingualZeroShotClassifier] Error during classification: {e}, using heuristic fallback")
            return self._heuristic_classify(query, labels)
        print(f"[MultilingualZeroShotClassifier] No valid output, using heuristic fallback")
        return self._heuristic_classify(query, labels)
    
    def _heuristic_classify(self, query: str, labels: List[str]) -> str | None:
        """Simple heuristic classification based on keyword matching."""
        if not query or not labels:
            return None
        
        query_lower = query.lower()
        
        # Define keyword patterns for each label
        patterns = {
            "factoid": ["what is", "define", "meaning", "definition", "range", "normal", "dose", "dosage", "how much", "how many"],
            "temporal": ["trend", "over time", "change", "increase", "decrease", "since", "when", "history", "progression", "evolution"],
            "broad": ["plan", "overview", "summary", "workup", "approach", "evaluation", "assessment", "strategy", "management"]
        }
        
        # Count matches for each label
        scores = {}
        for label in labels:
            if label in patterns:
                score = sum(1 for pattern in patterns[label] if pattern in query_lower)
                scores[label] = score
        
        # Return the label with the highest score, or None if no matches
        if scores and max(scores.values()) > 0:
            result = max(scores, key=scores.get)
            print(f"[MultilingualZeroShotClassifier] Heuristic classification: {result} (score: {scores[result]})")
            return result
        
        print(f"[MultilingualZeroShotClassifier] Heuristic classification: no clear match, returning None")
        return None


