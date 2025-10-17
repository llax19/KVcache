class KVCacheStore:
    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._set = set()

    def add(self, prefix_hash_id: int):
        self._set.add(prefix_hash_id)

    def delete(self, prefix_hash_id: int):
        self._set.discard(prefix_hash_id)

    def contains(self, prefix_hash_id: int) -> bool:
        return prefix_hash_id in self._set

    def size(self) -> int:
        return len(self._set)
