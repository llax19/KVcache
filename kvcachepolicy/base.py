from kvstore import KVCacheStore


class KVCachePolicy:
    """Base class for KV cache policies."""

    def __init__(self, store: KVCacheStore):
        self.store = store

    def access(self, key: int, request_prefix_hash_ids=None, request_type=None) -> bool:
        """
        Access the cache with the given key.
        Returns True if it's a cache hit, False if it's a miss.
        """
        raise NotImplementedError("access method must be implemented by subclasses")
