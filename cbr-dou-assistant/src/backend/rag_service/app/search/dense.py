"""Dense index backends: in-memory numpy (tests/fallback) and Qdrant local mode."""
from __future__ import annotations

import uuid
from typing import Protocol, Sequence

import numpy as np

from app.core.chunks import Chunk


class DenseIndex(Protocol):
    """Anything that can answer 'nearest chunk ids' under an access-level cap."""
    def search(self, qvec: np.ndarray, k: int, max_access: int) -> list[tuple[str, float]]: ...


class NumpyDense:
    """Exact cosine search over L2-normalised vectors."""

    def __init__(self, ids: Sequence[str], vecs: np.ndarray, access: Sequence[int]) -> None:
        self.ids, self.vecs, self.access = list(ids), vecs, np.array(access)

    def search(self, qvec: np.ndarray, k: int, max_access: int) -> list[tuple[str, float]]:
        sims = self.vecs @ qvec
        sims = np.where(self.access <= max_access, sims, -np.inf)
        top = np.argsort(-sims)[:k]
        return [(self.ids[i], float(sims[i])) for i in top if np.isfinite(sims[i])]


def _uid(collection: str, chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{collection}/{chunk_id}"))


class QdrantDense:
    """Qdrant (local mode, path=...) collection per version; payload = full chunk."""

    def __init__(self, path: str, collection: str) -> None:
        from qdrant_client import QdrantClient
        self.client, self.collection = QdrantClient(path=path), collection

    @classmethod
    def build(cls, path: str, collection: str, chunks: list[Chunk], vecs: np.ndarray) -> "QdrantDense":
        """(Re)create the collection and upsert all chunks — idempotent."""
        from qdrant_client.models import Distance, PointStruct, VectorParams
        self = cls(path, collection)
        if self.client.collection_exists(collection):
            self.client.delete_collection(collection)
        self.client.create_collection(collection, vectors_config=VectorParams(size=int(vecs.shape[1]), distance=Distance.COSINE))
        self.client.upsert(collection, points=[PointStruct(id=_uid(collection, c["id"]), vector=v.tolist(), payload=c)
                                               for c, v in zip(chunks, vecs)])
        return self

    def count(self) -> int:
        """Number of stored points."""
        return self.client.count(self.collection).count

    def search(self, qvec: np.ndarray, k: int, max_access: int) -> list[tuple[str, float]]:
        from qdrant_client.models import FieldCondition, Filter, Range
        flt = Filter(must=[FieldCondition(key="access_level", range=Range(lte=max_access))])
        res = self.client.query_points(self.collection, query=qvec.tolist(), limit=k, query_filter=flt,
                                       with_payload=["id"]).points
        return [(p.payload["id"], float(p.score)) for p in res]
