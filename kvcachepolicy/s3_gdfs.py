from collections import deque
from typing import Dict, Any, List, Optional, Tuple
import heapq

from kvcachepolicy import KVCachePolicy, GhostFIFO
from kvstore import KVCacheStore


class S3FIFO_Prio(KVCachePolicy):
    """
    S3-FIFO with GDFS-style priority admission (no frequency term).

    Priority = Clock + PosBonus
      - Clock: max priority of recently evicted item (monotonically non-decreasing)
      - PosBonus: pos_alpha * ((n - i) / n), where i is index(key) in request list

    Behavior:
      - Hit: update priority, promote to M if currently in S.
      - Miss: compute prio_new; if cache full, admit only if prio_new >= current min priority.
              Evict the min-priority resident (global) and admit new key.
      - Insert target queue:
          * If key present in Ghost -> M
          * Else if prio_new >= current min resident priority (if any) -> M, else -> S
      - Eviction updates Clock = max(Clock, victim_priority).
    """

    def __init__(
        self, store: KVCacheStore, pos_alpha: float = 1.0, sm_ratio: float = 0.1
    ):
        self.store = store
        self.S = deque()  # small FIFO (head=left, tail=right)
        self.M = deque()  # main FIFO
        self.ghost = GhostFIFO(capacity=store.capacity)

        # Priority metadata and heap
        self.clock: float = 0.0
        self._heap: list[tuple[float, int, int]] = []  # (priority, version, key)
        self._meta: Dict[int, Dict[str, Any]] = {}  # key -> {priority, version}

        # Queue capacities
        self.s_capacity = max(1, int(sm_ratio * store.capacity))
        self.m_capacity = max(0, store.capacity - self.s_capacity)

        self.pos_alpha = float(pos_alpha)

    # --------------------- Public API ---------------------
    def access(
        self,
        key: int,
        request_prefix_hash_ids: Optional[List[int]] = None,
        request_type=None,
    ) -> bool:
        if self.store.contains(key):
            # Update priority on hit
            prio = self._calc_priority(
                self._position_bonus(key, request_prefix_hash_ids)
            )
            meta = self._meta.get(key)
            if meta is None:
                meta = {"priority": prio, "version": 0}
                self._meta[key] = meta
            meta["priority"] = prio
            meta["version"] += 1
            heapq.heappush(self._heap, (prio, meta["version"], key))
            # Promote S -> M on hit
            if self._in_deque(self.S, key):
                self._remove_from_deque(self.S, key)
                self.M.appendleft(key)
            return True

        # Miss path with admission gate by priority
        prio_new = self._calc_priority(
            self._position_bonus(key, request_prefix_hash_ids)
        )

        if self.store.size() >= self.store.capacity:
            min_pr, victim = self._peek_valid_min()
            if victim is not None and prio_new < min_pr:
                # Reject admission
                return False
            if victim is not None:
                self._evict_key(victim, evicted_priority=min_pr)

        # Admit new key
        self._admit_new(key, prio_new)

        # Choose target queue
        if self.ghost.contains(key):
            self.ghost.remove(key)
            self._ensure_space_and_insert_M(key)
        else:
            # Heuristic: if new prio >= current min resident prio, prefer M; else S
            cur_min, _ = self._peek_valid_min()
            if cur_min is None or prio_new >= cur_min:
                self._ensure_space_and_insert_M(key)
            else:
                self._ensure_space_and_insert_S(key)

        return False

    def current_keys(self):
        # Return keys currently resident (unordered)
        return list(self._meta.keys())

    # --------------------- Internal helpers ---------------------
    def _calc_priority(self, pos_bonus: float) -> float:
        return self.clock + float(pos_bonus)

    def _position_bonus(
        self, key: int, request_prefix_hash_ids: Optional[List[int]]
    ) -> float:
        ids = request_prefix_hash_ids or []
        n = len(ids)
        if n <= 0:
            return 0.0
        try:
            i = ids.index(key)
        except ValueError:
            return 0.0
        return self.pos_alpha * ((n - i) / n)

    def _peek_valid_min(self) -> Tuple[Optional[float], Optional[int]]:
        while self._heap:
            prio, ver, k = self._heap[0]
            meta = self._meta.get(k)
            if (
                meta is not None
                and ver == meta.get("version")
                and self.store.contains(k)
            ):
                return prio, k
            heapq.heappop(self._heap)
        return None, None

    def _admit_new(self, key: int, prio: float) -> None:
        self.store.add(key)
        meta = {"priority": float(prio), "version": 0}
        self._meta[key] = meta
        heapq.heappush(self._heap, (prio, meta["version"], key))

    def _evict_key(self, victim: int, evicted_priority: float) -> None:
        # Remove from queues
        self._remove_from_deque(self.S, victim)
        self._remove_from_deque(self.M, victim)
        # Update structures
        self.store.delete(victim)
        self._meta.pop(victim, None)
        self.clock = max(self.clock, float(evicted_priority))
        # Record in ghost
        self.ghost.add(victim)

    def _ensure_space_and_insert_S(self, key: int) -> None:
        # Prefer evict from S tail if S over target, else from M
        if len(self.S) >= self.s_capacity:
            self._evict_from_S_tail()
        elif self.store.size() > self.store.capacity:
            self._evict_lowest_priority()
        self.S.appendleft(key)

    def _ensure_space_and_insert_M(self, key: int) -> None:
        if len(self.M) >= self.m_capacity:
            self._evict_from_M_tail_or_rotate()
        elif self.store.size() > self.store.capacity:
            self._evict_lowest_priority()
        self.M.appendleft(key)

    def _evict_from_S_tail(self) -> None:
        if not self.S:
            return
        t = self.S.pop()
        # S-tail eviction is real eviction (priority-aware clock)
        meta = self._meta.get(t)
        prio = meta["priority"] if meta else 0.0
        self._evict_key(t, evicted_priority=prio)

    def _evict_from_M_tail_or_rotate(self) -> None:
        if not self.M:
            return
        # In pure FIFO, tail eviction; we keep FIFO but still update clock by victim's priority.
        t = self.M.pop()
        meta = self._meta.get(t)
        prio = meta["priority"] if meta else 0.0
        self._evict_key(t, evicted_priority=prio)

    def _evict_lowest_priority(self) -> None:
        min_pr, victim = self._peek_valid_min()
        if victim is not None:
            self._evict_key(
                victim, evicted_priority=min_pr if min_pr is not None else 0.0
            )

    @staticmethod
    def _in_deque(dq: deque, key: int) -> bool:
        return key in dq

    @staticmethod
    def _remove_from_deque(dq: deque, key: int) -> None:
        if not dq:
            return
        # Remove first occurrence
        try:
            idx = dq.index(key)
            del dq[idx]
        except ValueError:
            pass
