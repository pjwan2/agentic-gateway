# agents/semantic_router.py

import os
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from typing import Dict, List

# Redirect model cache away from ~/.cache (which may be a file on some Windows setups)
_cache_dir = os.path.join(os.path.dirname(__file__), "..", ".model_cache")
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", os.path.abspath(_cache_dir))
os.environ.setdefault("HF_HOME", os.path.abspath(_cache_dir))

class IntentRouter:
    """
    Enterprise-grade semantic router to classify user intents and direct traffic
    to the appropriate underlying LLM or Agent queue.
    """
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        # We use a lightweight local model for zero-latency routing.
        # This prevents making external API calls just to figure out the intent.
        print(f"Loading embedding model: {model_name}...")
        self.encoder = SentenceTransformer(model_name)
        
        # Define routes and their anchor phrases (System 1 Memory)
        self.routes: Dict[str, List[str]] = {
            "casual_chat": [
                "hello", "hi there", "how are you", "tell me a joke", "what is your name"
            ],
            "financial_quant": [
                "analyze the earnings report", "what is the implied volatility of NVDA",
                "calculate the max loss for this bull put spread", "stock market trends"
            ],
            "code_assistant": [
                "write a python script", "debug this React component", 
                "explain this regex", "fix my git merge conflict"
            ]
        }
        
        # Pre-compute anchor embeddings during startup to ensure sub-millisecond routing
        self.route_embeddings = self._precompute_embeddings()

    def _precompute_embeddings(self) -> Dict[str, np.ndarray]:
        precomputed = {}
        for intent, phrases in self.routes.items():
            # Encode all phrases for a specific route
            embeddings = self.encoder.encode(phrases)
            precomputed[intent] = embeddings
        return precomputed

    def classify_intent(self, query: str, threshold: float = 0.5) -> tuple[str, float]:
        """
        Calculates cosine similarity between the user query and precomputed anchors.
        Returns (intent, confidence_score).
        confidence_score is the raw cosine similarity of the winning anchor [0.0 – 1.0].
        If no intent exceeds the threshold, falls back to casual_chat.
        """
        query_embedding = self.encoder.encode([query])

        best_intent = "casual_chat"
        highest_score = 0.0

        for intent, anchor_embeddings in self.route_embeddings.items():
            similarities = cosine_similarity(query_embedding, anchor_embeddings)
            max_sim = float(np.max(similarities))

            if max_sim > highest_score:
                highest_score = max_sim
                best_intent = intent

        if highest_score >= threshold:
            return best_intent, round(highest_score, 3)
        else:
            return "casual_chat", round(highest_score, 3)

# Initialize a singleton instance to be used across FastAPI workers
semantic_router = IntentRouter()