"""The single interface the harness speaks to. It never knows which engine.

Contract, in order of use:
    wait_ready()  -> block until the server answers, or raise
    reset()       -> drop any prior index/collection and create a fresh one
    index(docs)   -> load the full corpus, return timing/size stats
    search(q, k)  -> return up to k doc ids, best first
    close()       -> release the HTTP session

``search`` returns ids only. Ranking quality is judged by the harness against
the golden set; the adapter's sole job is faithful config + id extraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..schema import Doc


@dataclass
class IndexStats:
    doc_count: int
    seconds: float
    index_bytes: int | None = None  # None when the engine can't report it
    # What ``index_bytes`` actually measures. The engines differ architecturally
    # (on-disk Lucene vs in-RAM), so the number is only meaningful alongside this
    # label; collapsing them into one unlabeled figure would invite a false
    # apples-to-apples comparison.
    footprint_kind: str | None = None


class SearchEngine(ABC):
    #: stable lowercase identifier, also the ``--engine`` CLI value
    name: str

    @abstractmethod
    def wait_ready(self, timeout: float = 60.0) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def index(self, docs: list[Doc]) -> IndexStats: ...

    @abstractmethod
    def search(self, q: str, k: int) -> list[str]: ...

    def close(self) -> None:  # optional override
        pass

    def __enter__(self) -> "SearchEngine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
