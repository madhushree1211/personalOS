from __future__ import annotations

from typing import Iterable

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def lexical_tfidf_search(
    query: str,
    chunks: Iterable[dict],
    limit: int,
) -> list[dict]:
    chunk_list = list(chunks)
    if not chunk_list or not query.strip():
        return []
    texts = [str(chunk["text"]) for chunk in chunk_list]
    vectorizer = TfidfVectorizer()
    matrix = vectorizer.fit_transform([*texts, query])
    scores = cosine_similarity(matrix[-1], matrix[:-1])[0]
    ranked = sorted(
        zip(chunk_list, scores),
        key=lambda item: item[1],
        reverse=True,
    )
    return [
        {**chunk, "score": float(score)}
        for chunk, score in ranked[:limit]
    ]
