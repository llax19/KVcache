from collections import deque, OrderedDict
from typing import Dict, List, Optional


from kvcachepolicy import KVCachePolicy, GhostFIFO
from kvstore import KVCacheStore


class S3FIFO_Attn(KVCachePolicy):
    """
    S3FIFO with offset-based attention:
    - offset records the key's "segment-from-tail" index within current request.
      Larger offset => the key is earlier in the request and assumed more likely to be reused.
    - Initialize offset per request by splitting request_prefix_hash_ids into contiguous runs
      (id[i] == id[i-1] + 1). The last run gets offset 0, previous run 1, and so on.
    - Insert: keys with offset>0 or present in Ghost go to Main queue (M); offset==0 and not in Ghost go to Small queue (S).
    - Update policy similar to freq:
        * on hit: offset <- min(offset+1, 3)
        * on M tail rotation: if offset>0, rotate to head and offset <- offset-1; else real eviction
    """

    def __init__(self, store: KVCacheStore, sm_ratio: float = 0.05):
        self.store = store

        # Small/Main queues and sets (for O(1) membership checks)
        self.S = deque()  # left is the head, right is the tail
        self.M = deque()

        self.G = GhostFIFO(capacity=store.capacity)

        # offset per resident key (0..3)
        self.offset: Dict[int, int] = {}

        self.s_capacity = int(sm_ratio * store.capacity)
        self.m_capacity = store.capacity - self.s_capacity

        # per-request offset cache
        self._offset_cache_req_id: Optional[int] = None  # id(request_prefix_hash_ids)
        self._offset_cache_map: Dict[int, int] = {}

    def access(
        self, key: int, request_prefix_hash_ids: List[int] = None, request_type=None
    ) -> bool:
        if self.store.contains(key):
            self.offset[key] = min(self.offset.get(key, 0) + 1, 3)
            return True

        init_offset = self._get_init_offset(key, request_prefix_hash_ids)
        self.offset[key] = init_offset
        self.insert(key)
        return False

    def insert(self, key: int):
        # Ensure space
        while self.store.size() >= self.store.capacity:
            self.evict()

        if self.G.contains(key):
            self._insert_head_M(key)
            self.G.remove(key)
            self._rebalance_M_if_over()
        else:
            self._insert_head_S(key)

    def evict(self):
        if len(self.S) >= self.s_capacity:
            self._evictS()
        else:
            self._evictM()

    def _evictS(self):
        """
        Evict from tail of S:
          - If t.offset > 0: promote to M; rebalance M if over
          - Else: real eviction -> move to Ghost and delete from store
          - Repeat until a real eviction occurs or S is empty
        """
        evicted = False
        while not evicted and len(self.S) > 0:
            t = self.S[-1]
            t_off = self.offset.get(t, 0)

            self.S.pop()

            if t_off > 0:
                self.M.appendleft(t)
                self._rebalance_M_if_over()
            else:  # Evict t to G (real eviction)
                self.G.add(t)
                self.store.delete(t)
                self.offset.pop(t, None)
                evicted = True

    def _evictM(self):
        """
        Evict from tail of M:
          - If t.offset > 0: rotate to head and decrement offset
          - Else: real eviction -> move to Ghost and delete from store
        """
        evicted = False
        while not evicted and len(self.M) > 0:
            t = self.M[-1]
            t_off = self.offset.get(t, 0)

            if t_off > 0:
                self.M.pop()
                self.M.appendleft(t)
                self.offset[t] = t_off - 1
            else:
                self.M.pop()
                self.store.delete(t)
                self.G.add(t)
                self.offset.pop(t, None)
                evicted = True

    def _insert_head_S(self, key: int):
        self.S.appendleft(key)
        self.store.add(key)

    def _insert_head_M(self, key: int):
        self.M.appendleft(key)
        self.store.add(key)

    def _rebalance_M_if_over(self):
        while len(self.M) > self.m_capacity:
            self._evictM()

    def _get_init_offset(
        self, key: int, request_prefix_hash_ids: Optional[List[int]]
    ) -> int:
        if not request_prefix_hash_ids:
            return 0
        req_id = id(request_prefix_hash_ids)
        if self._offset_cache_req_id != req_id:
            # compute once per new request (list object identity)
            self._offset_cache_map = self._compute_request_offsets(
                request_prefix_hash_ids
            )
            self._offset_cache_req_id = req_id
        return min(self._offset_cache_map.get(key, 0), 3)

    @staticmethod
    def _compute_request_offsets(seq: List[int]) -> Dict[int, int]:
        """
        Split seq into contiguous runs (x[i] == x[i-1]+1).
        The last run gets offset 0, the previous run gets 1, etc.
        Example:
          seq = [1,15,16,...,27,3869,3870]
          runs = [[1],[15..27],[3869,3870]]
          offsets: {1:2, 15..27:1, 3869..3870:0}
        """
        if not seq:
            return {}
        runs: List[List[int]] = []
        cur = [seq[0]]
        for i in range(1, len(seq)):
            if seq[i] == seq[i - 1] + 1:
                cur.append(seq[i])
            else:
                runs.append(cur)
                cur = [seq[i]]
        runs.append(cur)

        out: Dict[int, int] = {}
        for idx, run in enumerate(runs):
            off = len(runs) - 1 - idx  # last run -> 0
            for x in run:
                out[x] = off
        return out

    def current_keys(self):
        return list(self.S), list(self.M)
