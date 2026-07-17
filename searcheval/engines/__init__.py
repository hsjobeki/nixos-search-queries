"""Engine adapters. Each implements the ``SearchEngine`` contract in ``base``."""

from .base import IndexStats, SearchEngine
from .elasticsearch import Elasticsearch
from .typesense import Typesense

# Registry consumed by the CLI. Keys are the ``--engine`` values.
ENGINES = {"elasticsearch": Elasticsearch, "typesense": Typesense}

__all__ = ["SearchEngine", "IndexStats", "Elasticsearch", "Typesense", "ENGINES"]
