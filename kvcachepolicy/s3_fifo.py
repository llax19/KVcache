from collections import deque, OrderedDict


from kvcachepolicy import KVCachePolicy
from kvstore import KVCacheStore


class GhostFIFO:
    """
    Ghost queue: FIFO order + O(1) membership via OrderedDict.
    """

    def __init__(self, capacity: int):
        self.capacity = max(1, capacity)
        self.od = OrderedDict()  # key -> virtual timestamp
        self.N = 0

    def contains(self, key: int) -> bool:
        return key in self.od

    def add(self, key: int):
        self.N += 1
        # Insert newest; refresh if already exists
        self.od[key] = self.N
        self.od.move_to_end(key, last=True)
        # Enforce capacity
        while len(self.od) > self.capacity:
            self.od.popitem(last=False)

    def remove(self, key: int):
        self.od.pop(key, None)


class S3FIFO(KVCachePolicy):
    """
    An implementation of the S3FIFO cache replacement policy.

    Notes:
    - To enable fast "in S / in M / in G" checks, corresponding sets are maintained.
    - G is a FIFO + set with a capacity limit set to the total cache size (empirical value for stability); this can be adjusted as needed.
    """

    def __init__(self, store: KVCacheStore, sm_ratio: float = 0.1):
        self.store = store

        # Small/Main queues and sets (for O(1) membership checks)
        self.S = deque()  # left is the head, right is the tail
        self.M = deque()

        # Ghost queue and set
        self.G = GhostFIFO(capacity=store.capacity)

        # Hit frequency (maintained only for resident keys; ghost keys do not have freq)
        self.freq = {}  # key -> int (0..3)

        self.s_capacity = int(sm_ratio * store.capacity)
        self.m_capacity = store.capacity - self.s_capacity

    def access(self, key: int, request_prefix_hash_ids=None, request_type=None) -> bool:
        """
        Corresponds to READ(x):
        - On hit (x in S or x in M): freq <- min(freq+1, 3)
        - On miss: INSERT(x), then freq <- 0
        Returns True/False indicating hit/miss.
        """
        if self.store.contains(key):
            # Cache hit
            self.freq[key] = min(self.freq.get(key, 0) + 1, 3)
            return True

        # Cache miss -> INSERT
        self.insert(key)
        self.freq[key] = 0
        return False

    def insert(self, key: int):
        while (
            self.store.size() >= self.store.capacity
        ):  # Ensure space (resident cache is not full)
            self.evict()

        if self.G.contains(key):
            self._insert_head_M(key)
            self.G.remove(key)
            self._rebalance_M_if_over()
        else:
            self._insert_head_S(key)
            # Optional: if S grows too fast, subsequent EVICT will prioritize cleaning S

    def evict(self):
        if len(self.S) >= self.s_capacity:
            self._evictS()
        else:
            self._evictM()

    def _evictS(self):
        """
        Evict from the tail of S
          - If t.freq > 1: move t to M; if M is full, call evictM()
          - Else: evict t to G and remove t from S (a real eviction occurs)
          - Repeat until a real eviction occurs or S is empty
        """
        evicted = False
        while not evicted and len(self.S) > 0:
            t = self.S[-1]  # tail of S
            t_freq = self.freq.get(t, 0)

            # Remove t from S (both moving and evicting require removal from S first)
            self.S.pop()

            if t_freq > 1:  # Promote t to M
                self.M.appendleft(t)
                self._rebalance_M_if_over()
            else:  # Evict t to G (real eviction)
                self.G.add(t)
                self.store.delete(t)
                self.freq.pop(t, None)
                evicted = True

    def _evictM(self):
        """
        Evict from the tail of M
          - If t.freq > 0: rotate t to the head of M and decrement t.freq (no real eviction occurs)
          - Else: remove t from M
          - Repeat until a real eviction occurs or M is empty
        """
        evicted = False
        while not evicted and len(self.M) > 0:
            t = self.M[-1]  # tail of M
            t_freq = self.freq.get(t, 0)

            if t_freq > 0:
                # Rotate t to the head of M and decrement its frequency
                self.M.pop()
                self.M.appendleft(t)
                self.freq[t] = t_freq - 1
            else:
                self.M.pop()
                self.store.delete(t)
                self.G.add(t)
                self.freq.pop(t, None)
                evicted = True

    def _insert_head_S(self, key: int):
        """Insert key at the head of S"""
        self.S.appendleft(key)
        self.store.add(key)

    def _insert_head_M(self, key: int):
        """Insert key at the head of M"""
        self.M.appendleft(key)
        self.store.add(key)

    def _rebalance_M_if_over(self):
        """If M exceeds its target size (90%), proactively evict from M to rebalance"""
        while len(self.M) > self.m_capacity:
            self._evictM()

    def current_keys(self):
        """Return the current resident keys (S head->tail, M head->tail) for debugging/inspection"""
        return list(self.S), list(self.M)
