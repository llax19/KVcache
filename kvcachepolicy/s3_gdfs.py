from collections import deque
import heapq
from typing import Dict, Tuple, Optional


from kvcachepolicy import KVCachePolicy, GhostFIFO
from kvstore import KVCacheStore


class S3GDFS(KVCachePolicy):
    """
    S3-FIFO eviction + GDS/GDSF-style admission gate.

    - G (ghost) tracks evicted keys only
    - freq: small capped counter (0..3) per resident key
    - Heap for admission minPriority: (priority, version, key)
    - Clock updated on real eviction
    """

    def __init__(self, store: KVCacheStore, beta_pos: float = 1.0):
        self.store = store

        # S/M queues (left=head, right=tail)
        self.S = deque()
        self.M = deque()
        self.small_target = max(1, store.capacity // 10)
        self.main_target = store.capacity - self.small_target

        # Ghost
        self.ghost = GhostFIFO(capacity=store.capacity)

        # Frequency and metadata
        self.freq: Dict[int, int] = {}  # key -> 0..3
        self.meta: Dict[int, Dict[str, float]] = (
            {}
        )  # key -> {"priority": float, "version": int}

        # Admission heap and clock
        self.heap: list[Tuple[float, int, int]] = []  # (priority, version, key)
        self.clock: float = 0.0
        self.beta_pos = beta_pos  # weight for position bias (front tokens)

    # --------------------- Public API ---------------------
    def access(self, key: int, request_prefix_hash_ids=None, request_type=None) -> bool:
        """
        Process one access.
        - Hit: freq capped +1, update priority and heap
        - Miss: compute admission priority; if full, gate; then insert via S3-FIFO
        """
        if self.store.contains(key):
            # Cache hit: freq := min(freq+1, 3)
            f = min(self.freq.get(key, 0) + 1, 3)
            self.freq[key] = f
            pr = self._calc_priority(f, self._pos_bias(key, request_prefix_hash_ids))
            self._update_meta_and_heap(key, pr)
            return True

        # Miss: compute admission priority using a first-seen freq=1 (prior)
        pr_new = self._calc_priority(1, self._pos_bias(key, request_prefix_hash_ids))

        # Admission gate if full
        if self.store.size() >= self.store.capacity:
            min_pr, victim = self._peek_valid_min()
            if min_pr is not None and pr_new < min_pr:
                # Reject caching; serve miss but do not insert to S/M/G
                return False
            # Accept: make space by one real eviction via S3-FIFO paths
            self._ensure_space_one_eviction()

        # Insert by S3-FIFO rules
        if self.ghost.contains(key):
            self._insert_head_M(key, pr_new)
            self.ghost.remove(key)
            self._rebalance_M_if_over()
        else:
            self._insert_head_S(key, pr_new)

        # S3-FIFO semantics: resident freq starts at 0
        self.freq[key] = 0
        return False

    def current_keys(self):
        return list(self.S), list(self.M)

    # --------------------- Admission helpers ---------------------
    def _calc_priority(self, freq: int, pos_bias: float) -> float:
        # GDSF under Cost=1, Size=1: Priority = Clock + Fr + PosBias
        return self.clock + float(freq) + pos_bias

    def _pos_bias(self, key: int, request_prefix_hash_ids) -> float:
        """
        Position bias: higher for front tokens.
        We use beta_pos / (1 + offset), where offset is index in current request if available.
        """
        if not request_prefix_hash_ids:
            return 0.0
        try:
            idx = request_prefix_hash_ids.index(key)  # O(n); acceptable for prototype
            return self.beta_pos / (1 + idx)
        except ValueError:
            return 0.0

    def _update_meta_and_heap(self, key: int, priority: float):
        m = self.meta.get(key)
        if m is None:
            m = {"priority": priority, "version": 0}
            self.meta[key] = m
        else:
            m["priority"] = priority
            m["version"] += 1
        heapq.heappush(self.heap, (m["priority"], m["version"], key))

    def _peek_valid_min(self) -> Tuple[Optional[float], Optional[int]]:
        """Return current valid min (priority, key) from heap."""
        while self.heap:
            pr, ver, k = self.heap[0]
            m = self.meta.get(k)
            if m is not None and ver == m.get("version") and self.store.contains(k):
                return pr, k
            heapq.heappop(self.heap)  # drop stale
        return None, None

    # --------------------- S3-FIFO core ---------------------
    def _insert_head_S(self, key: int, priority: float):
        self.store.add(key)
        self.S.appendleft(key)
        self._update_meta_and_heap(key, priority)

    def _insert_head_M(self, key: int, priority: float):
        self.store.add(key)
        self.M.appendleft(key)
        self._update_meta_and_heap(key, priority)

    def _rebalance_M_if_over(self):
        while len(self.M) > self.main_target and self.store.size() > 0:
            self._evictM_real_once()

    def _ensure_space_one_eviction(self):
        """Make space by one real eviction using S3-FIFO paths."""
        if len(self.S) >= self.small_target:
            self._evictS_real_once()
        else:
            self._evictM_real_once()

    def _evictS_real_once(self):
        """
        EVICTS(): pop from S tail; if freq>1 -> promote to M; else real eviction (to ghost)
        Repeat until a real eviction happens or S becomes empty.
        """
        evicted = False
        while not evicted and len(self.S) > 0:
            t = self.S[-1]
            # Remove from S structure
            self.S.pop()
            t_freq = self.freq.get(t, 0)

            if t_freq > 1:
                # Promote to M (not a real eviction)
                self.M.appendleft(t)
                self._rebalance_M_if_over()
            else:
                # Real eviction: remove resident, add to ghost, update clock
                self.store.delete(t)
                self.ghost.add(t)
                pr_t = self.meta.get(t, {}).get("priority", self.clock)
                # Update clock with victim's priority
                self.clock = max(self.clock, float(pr_t))
                # Cleanup meta/freq
                self.meta.pop(t, None)
                self.freq.pop(t, None)
                evicted = True

    def _evictM_real_once(self):
        """
        EVICTM(): pop from M tail; if freq>0 -> rotate to head and dec; else real eviction (to ghost)
        Repeat until a real eviction happens or M becomes empty.
        """
        evicted = False
        while not evicted and len(self.M) > 0:
            t = self.M[-1]
            t_freq = self.freq.get(t, 0)

            if t_freq > 0:
                # Rotate and decrement freq
                self.M.pop()
                self.M.appendleft(t)
                self.freq[t] = t_freq - 1
            else:
                # Real eviction: remove resident, add to ghost, update clock
                self.M.pop()
                self.store.delete(t)
                self.ghost.add(t)
                pr_t = self.meta.get(t, {}).get("priority", self.clock)
                self.clock = max(self.clock, float(pr_t))
                self.meta.pop(t, None)
                self.freq.pop(t, None)
                evicted = True
