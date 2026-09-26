# -*- coding: utf-8 -*-
"""Optional FAISS index for the memory vector route.

The plugin keeps SQLite+cosine as a zero-dependency fallback. This adapter is
used only when the host provides faiss and numpy.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


class FaissIndex:
    """IndexIDMap2(IndexFlatIP) with atomic index and ID-map persistence."""

    def __init__(self, path, dim=0):
        self.path = Path(path)
        self.meta_path = Path(str(self.path) + ".json")
        self.dim = int(dim or 0)
        self._faiss = None
        self._np = None
        self.index = None
        self.ids = {}
        try:
            import faiss
            import numpy as np
            self._faiss = faiss
            self._np = np
        except Exception:
            return
        self._load()

    @property
    def enabled(self):
        return self._faiss is not None and self._np is not None

    def _load(self):
        try:
            if self.path.exists():
                self.index = self._faiss.read_index(str(self.path))
                if self.dim and self.index.d != self.dim:
                    self.index = None
            if self.meta_path.exists():
                self.ids = {str(k): int(v) for k, v in json.loads(
                    self.meta_path.read_text(encoding="utf-8")).items()}
        except Exception:
            self.index = None
            self.ids = {}

    def _ensure(self, dim):
        if self.index is None:
            self.dim = int(dim)
            self.index = self._faiss.IndexIDMap2(
                self._faiss.IndexFlatIP(self.dim))
        if self.index.d != int(dim):
            raise ValueError("embedding dimension mismatch")

    @staticmethod
    def _stable_id(key: str) -> int:
        """跨进程稳定的正整数 FAISS ID。"""
        raw = hashlib.blake2b(str(key).encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(raw, "big") & ((1 << 62) - 1)

    def upsert(self, item_id, vector):
        if not self.enabled:
            return False
        vec = self._np.asarray([vector], dtype="float32")
        norm = self._np.linalg.norm(vec, axis=1, keepdims=True)
        if not norm[0, 0]:
            return False
        vec = vec / norm
        self._ensure(vec.shape[1])
        key = str(item_id)
        if key in self.ids:
            self.index.remove_ids(self._np.asarray([self.ids[key]], dtype="int64"))
        fid = self._stable_id(key)
        while fid in self.ids.values() and self.ids.get(key) != fid:
            fid = (fid + 1) % (2 ** 62)
        self.index.add_with_ids(vec, self._np.asarray([fid], dtype="int64"))
        self.ids[key] = fid
        self.save()
        return True

    def remove(self, item_id):
        if not self.enabled or str(item_id) not in self.ids:
            return False
        fid = self.ids.pop(str(item_id))
        self.index.remove_ids(self._np.asarray([fid], dtype="int64"))
        self.save()
        return True

    def reconcile(self, valid_ids):
        """Remove index entries absent from the SQLite vector table."""
        if not self.enabled:
            return 0
        valid = {str(x) for x in valid_ids}
        stale = [key for key in self.ids if key not in valid]
        for key in stale:
            self.remove(key)
        return len(stale)

    def search(self, vector, top_k=8):
        if not self.enabled or self.index is None or not self.ids:
            return []
        q = self._np.asarray([vector], dtype="float32")
        if q.shape[1] != self.index.d:
            return []
        norm = self._np.linalg.norm(q, axis=1, keepdims=True)
        if not norm[0, 0]:
            return []
        q = q / norm
        scores, found = self.index.search(q, min(int(top_k), self.index.ntotal))
        reverse = {v: k for k, v in self.ids.items()}
        return [(reverse[int(fid)], float(score))
                for score, fid in zip(scores[0], found[0])
                if int(fid) in reverse]

    def save(self):
        if not self.enabled or self.index is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self.path.name + ".",
                                   dir=str(self.path.parent))
        os.close(fd)
        tmp_path = Path(tmp)
        meta_tmp = Path(str(self.meta_path) + ".tmp")
        try:
            self._faiss.write_index(self.index, str(tmp_path))
            os.replace(tmp_path, self.path)
            meta_tmp.write_text(json.dumps(self.ids, ensure_ascii=False),
                                encoding="utf-8")
            os.replace(meta_tmp, self.meta_path)
        finally:
            tmp_path.unlink(missing_ok=True)
            meta_tmp.unlink(missing_ok=True)
