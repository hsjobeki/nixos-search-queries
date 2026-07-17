"""Engine adapters. Each implements the ``SearchEngine`` contract in ``base``."""

from .base import IndexStats, SearchEngine
from .elasticsearch import Elasticsearch
from .typesense import Typesense
from .quickwit import Quickwit

# Registry consumed by the CLI. Keys are the ``--engine`` values.
ENGINES = {"elasticsearch": Elasticsearch, "typesense": Typesense, "quickwit": Quickwit}

__all__ = ["SearchEngine", "IndexStats", "Elasticsearch", "Typesense", "Quickwit", "ENGINES"]
