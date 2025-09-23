from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional


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
        self._executor = ThreadPoolExecutor(max_workers=4)  # For parallel execution
        self._shutdown = False

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
            print("[MultilingualCrossEncoder] Using heuristic fallback")
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

    def shutdown(self) -> None:
        """Shutdown the thread pool executor."""
        if not self._shutdown and self._executor:
            self._executor.shutdown(wait=True)
            self._shutdown = True

    def __del__(self) -> None:
        """Ensure executor is properly shutdown when instance is garbage collected."""
        self.shutdown()

    async def score_pairs_async(self, query: str, passages: List[str]) -> List[float]:
        """Async wrapper for score_pairs to enable parallel execution."""
        try:
            if self._shutdown:
                # Fallback to synchronous execution
                return self.score_pairs(query, passages)

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, self.score_pairs, query, passages)
        except Exception as e:
            print(f"[MultilingualCrossEncoder] Async execution failed: {e}, falling back to sync")
            return self.score_pairs(query, passages)

    async def score_multiple_batches_parallel(self, query: str, passage_batches: List[List[str]]) -> List[List[float]]:
        """Score multiple batches of passages in parallel.
        
        Args:
            query: The query string
            passage_batches: List of passage lists to score
            
        Returns:
            List of score lists, one for each batch
        """
        print(f"[MultilingualCrossEncoder] score_multiple_batches_parallel called with {len(passage_batches)} batches")
        
        # Create tasks for parallel execution
        tasks = [self.score_pairs_async(query, passages) for passages in passage_batches]
        
        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks)
        
        print(f"[MultilingualCrossEncoder] Completed parallel scoring of {len(passage_batches)} batches")
        return results

    async def score_all_operations_parallel(self, query: str, operations: List[dict]) -> List[List[float]]:
        """Score multiple different operations in parallel for maximum efficiency.
        
        This method combines all cross-encoder operations (reranking, gating, refinement)
        into a single parallel execution to minimize overhead and maximize throughput.
        
        Args:
            query: The query string
            operations: List of operation dicts, each containing:
                - 'passages': List of passages to score
                - 'operation_type': String identifier for the operation
                - 'metadata': Optional additional metadata
                
        Returns:
            List of score lists, one for each operation
        """
        print(f"[MultilingualCrossEncoder] score_all_operations_parallel called with {len(operations)} operations")
        
        # Log operation details
        for i, op in enumerate(operations):
            passages = op.get('passages', [])
            op_type = op.get('operation_type', 'unknown')
            print(f"[MultilingualCrossEncoder] Operation {i}: {op_type} with {len(passages)} passages")
        
        # Create tasks for all operations
        tasks = []
        for op in operations:
            passages = op.get('passages', [])
            if passages:  # Only create task if there are passages to score
                task = self.score_pairs_async(query, passages)
                tasks.append(task)
            else:
                # If no passages, return empty scores
                async def empty_result() -> list[float]:
                    return []
                tasks.append(asyncio.create_task(empty_result()))
        
        # Execute all tasks in parallel
        start_time = asyncio.get_event_loop().time()
        results = await asyncio.gather(*tasks)
        end_time = asyncio.get_event_loop().time()
        
        print(f"[MultilingualCrossEncoder] Completed {len(operations)} operations in {end_time - start_time:.3f}s")
        return results

    async def score_rerank_and_gate_parallel(self, query: str, rerank_passages: List[str], gate_passages: List[str]) -> tuple[List[float], List[float]]:
        """Optimized method to run reranking and gating in parallel.
        
        This is a specialized method for the common pattern of reranking followed by gating,
        which can be run in parallel since they don't depend on each other.
        
        Args:
            query: The query string
            rerank_passages: Passages to rerank
            gate_passages: Passages to gate (may overlap with rerank_passages)
            
        Returns:
            Tuple of (rerank_scores, gate_scores)
        """
        print(f"[MultilingualCrossEncoder] score_rerank_and_gate_parallel called with {len(rerank_passages)} rerank and {len(gate_passages)} gate passages")
        
        # Create both tasks
        rerank_task = self.score_pairs_async(query, rerank_passages)
        gate_task = self.score_pairs_async(query, gate_passages)
        
        # Execute both in parallel
        start_time = asyncio.get_event_loop().time()
        rerank_scores, gate_scores = await asyncio.gather(rerank_task, gate_task)
        end_time = asyncio.get_event_loop().time()
        
        print(f"[MultilingualCrossEncoder] Completed rerank and gate in {end_time - start_time:.3f}s")
        return rerank_scores, gate_scores

    async def score_refinement_queries_parallel(self, refined_queries: List[str], passages: List[str]) -> List[List[float]]:
        """Score multiple refined queries against the same passages in parallel.
        
        This is optimized for the refinement scenario where we have multiple query variants
        but the same set of passages to score against.
        
        Args:
            refined_queries: List of refined query strings
            passages: List of passages to score against each query
            
        Returns:
            List of score lists, one for each refined query
        """
        print(f"[MultilingualCrossEncoder] score_refinement_queries_parallel called with {len(refined_queries)} queries and {len(passages)} passages")
        
        if not refined_queries or not passages:
            return [[] for _ in refined_queries]
        
        # Create tasks for each refined query
        tasks = [self.score_pairs_async(query, passages) for query in refined_queries]
        
        # Execute all tasks in parallel
        start_time = asyncio.get_event_loop().time()
        results = await asyncio.gather(*tasks)
        end_time = asyncio.get_event_loop().time()
        
        print(f"[MultilingualCrossEncoder] Completed {len(refined_queries)} refinement queries in {end_time - start_time:.3f}s")
        return results

    async def score_comprehensive_retrieval_parallel(self, query: str, all_passages: List[str], rerank_indices: List[int], gate_indices: List[int], refined_queries: Optional[List[str]] = None) -> dict:
        """Comprehensive parallel scoring for the entire retrieval pipeline.
        
        This method runs all possible cross-encoder operations in parallel:
        - Reranking of initial passages
        - Gating of MMR-selected passages  
        - Scoring of refined queries (if provided)
        
        Args:
            query: The original query string
            all_passages: All available passages
            rerank_indices: Indices of passages to rerank
            gate_indices: Indices of passages to gate
            refined_queries: Optional list of refined queries
            
        Returns:
            Dict containing all scoring results
        """
        print("[MultilingualCrossEncoder] score_comprehensive_retrieval_parallel called")
        print(f"[MultilingualCrossEncoder] - Query: '{query[:50]}...'")
        print(f"[MultilingualCrossEncoder] - All passages: {len(all_passages)}")
        print(f"[MultilingualCrossEncoder] - Rerank indices: {len(rerank_indices)}")
        print(f"[MultilingualCrossEncoder] - Gate indices: {len(gate_indices)}")
        print(f"[MultilingualCrossEncoder] - Refined queries: {len(refined_queries) if refined_queries else 0}")
        
        # Prepare all operations
        operations: List[dict] = []
        
        # Operation 1: Reranking
        if rerank_indices:
            rerank_passages = [all_passages[i] for i in rerank_indices if i < len(all_passages)]
            if rerank_passages:
                operations.append({
                    'passages': rerank_passages,
                    'operation_type': 'reranking',
                    'metadata': {'indices': rerank_indices}
                })
        
        # Operation 2: Gating
        if gate_indices:
            gate_passages = [all_passages[i] for i in gate_indices if i < len(all_passages)]
            if gate_passages:
                operations.append({
                    'passages': gate_passages,
                    'operation_type': 'gating',
                    'metadata': {'indices': gate_indices}
                })
        
        # Operation 3-N: Refined queries (if provided)
        if refined_queries:
            for i, refined_query in enumerate(refined_queries):
                if all_passages:  # Score all passages against each refined query
                    operations.append({
                        'passages': all_passages,
                        'operation_type': f'refined_query_{i}',
                        'metadata': {'query': refined_query, 'query_index': i}
                    })
        
        print(f"[MultilingualCrossEncoder] Starting comprehensive parallel execution of {len(operations)} operations")
        start_time = asyncio.get_event_loop().time()
        
        # Run all operations in parallel
        all_results = await self.score_all_operations_parallel(query, operations)
        
        end_time = asyncio.get_event_loop().time()
        print(f"[MultilingualCrossEncoder] Comprehensive parallel execution completed in {end_time - start_time:.3f}s")
        
        # Organize results
        results: dict = {
            'rerank_scores': [],
            'gate_scores': [],
            'refined_query_scores': {}
        }
        
        result_index = 0
        for op in operations:
            op_type = op['operation_type']
            if op_type == 'reranking' and result_index < len(all_results):
                results['rerank_scores'] = all_results[result_index]
                result_index += 1
            elif op_type == 'gating' and result_index < len(all_results):
                results['gate_scores'] = all_results[result_index]
                result_index += 1
            elif op_type.startswith('refined_query_') and result_index < len(all_results):
                query_index = op['metadata'].get('query_index', 0)
                results['refined_query_scores'][query_index] = all_results[result_index]
                result_index += 1
        
        return results


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
            print("[MultilingualZeroShotClassifier] All model loading attempts failed")
            self._pipe = None

    def classify_query(self, query: str, labels: List[str]) -> str | None:
        print(f"[MultilingualZeroShotClassifier] classify_query called with query: '{query[:50]}...' and labels: {labels}")
        print(f"[MultilingualZeroShotClassifier] Model loaded: {self._loaded}, Pipeline exists: {self._pipe is not None}")
        
        if not self._loaded or self._pipe is None:
            print("[MultilingualZeroShotClassifier] Model not loaded, using heuristic fallback")
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
        print("[MultilingualZeroShotClassifier] No valid output, using heuristic fallback")
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
            result = max(scores, key=lambda k: scores[k])
            print(f"[MultilingualZeroShotClassifier] Heuristic classification: {result} (score: {scores[result]})")
            return result
        
        print("[MultilingualZeroShotClassifier] Heuristic classification: no clear match, returning None")
        return None


