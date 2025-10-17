from typing import Dict, Any
import heapq
from kvstore import KVCacheStore


class KVCachePolicy:
    """基于伪代码的 GDF/GDFS-Admission 简化策略（统一大小与代价）。

    优先级定义（统一 Cost=1, Size=1）：
        Priority(f) = Clock + Fr(f) + PosBonus(f)

    - Clock：最近一次被驱逐对象的优先级（单调不减）。
    - Fr(f)：对象被命中次数（首见为 1，命中 +1）。

    准入控制（Admission）：当缓存已满时，只有当新对象的 Priority 严格大于当前最小 Priority 时才执行驱逐并接纳新对象；否则直接拒绝缓存该对象（情况 C2）。这与伪代码的“先临时插入再判断是否为最小”等价且更高效。

    其中 PosBonus(f) 由本次请求中 key 在 request_prefix_hash_ids 的相对位置决定，靠近列表头部（更“早先”的 token）奖励更高：
        设 n=len(request_prefix_hash_ids)，i=index(key)（从 0 开始）
        PosBonus = pos_alpha * ((n - i) / n)

    注意：当前 `KVCacheStore` 的容量按“项数”计。pos_alpha 可调，默认 2。
    """

    def __init__(
        self,
        store: KVCacheStore,
        pos_alpha: float = 1,
    ):
        self.store = store
        # 全局时钟（最近一次被淘汰对象的优先级）
        self.clock: float = 0.0
        # 最小堆，元素为 (priority, version, key)
        self._heap: list[tuple[float, int, int]] = []
        # 元信息：key -> {freq, version, priority}
        self._meta: Dict[int, Dict[str, Any]] = {}
        # 容量（Total）与当前使用（Used，按项数计）
        self.total: int = int(self.store.capacity)
        self.used: int = int(self.store.size())
        # 位置加成系数
        self.pos_alpha: float = float(pos_alpha)

    # ------------------------------ 公共接口 ------------------------------
    def access(self, key: int, request_prefix_hash_ids, request_type) -> bool:
        """处理一次访问请求。

        返回值：是否命中（hit=True / miss=False）。在 miss 时可能根据准入控制选择是否缓存该对象。
        """
        # ----------------------
        # 1) 命中：更新频次和优先级
        # ----------------------
        if self.store.contains(key):
            meta = self._meta.get(key)
            if meta is None:
                # 兜底：若 Store 里已有但没有 meta（极少发生），用默认值补建。
                meta = {"freq": 0, "version": 0, "priority": 0.0}
                self._meta[key] = meta

            meta["freq"] += 1
            pos_bonus = self._position_bonus(key, request_prefix_hash_ids)
            prio = self._calc_priority(meta["freq"], pos_bonus)  # Priority = Clock + Fr + PosBonus
            meta["priority"] = prio
            meta["version"] += 1
            heapq.heappush(self._heap, (prio, meta["version"], key))
            return True

        # ----------------------
        # 2) 未命中：计算新对象优先级
        # ----------------------
        freq = 1
        pos_bonus = self._position_bonus(key, request_prefix_hash_ids)
        prio_new = self._calc_priority(freq, pos_bonus)

        # 2.1 空间足够：直接接纳
        if self.used < self.total:
            self._admit_new(key, freq, prio_new)
            return False

        # 2.2 空间不足：执行准入控制（C1/C2）
        min_pr, victim = self._peek_valid_min()
        if victim is None:
            # 理论上不应发生；为稳妥起见，直接拒绝准入
            return False

        # 若新对象优先级小于当前最小优先级，则拒绝缓存（C2）
        # 允许在相等时接纳以避免在初始阶段卡住
        if prio_new < min_pr:
            return False

        # 否则驱逐最小优先级对象并接纳新对象（C1）
        self._evict_key(victim, evicted_priority=min_pr)
        self._admit_new(key, freq, prio_new)
        return False

    def current_keys(self):
        # 返回当前在缓存中的 key 列表（无序）。
        return list(self._meta.keys())

    # ------------------------------ 内部方法 ------------------------------
    def _calc_priority(self, freq: float, pos_bonus: float) -> float:
        # 统一 Cost=1, Size=1 时：Priority = Clock + Fr + PosBonus
        return self.clock + float(freq) + float(pos_bonus)

    def _position_bonus(self, key: int, request_prefix_hash_ids) -> float:
        """基于 key 在本次请求列表中的相对位置计算位置加成（越靠近头部加成越高）。

        设列表长度为 n，key 的索引为 i（0-based）。
        PosBonus = pos_alpha * ((n - i) / n)。若 key 未出现在列表（理论不该发生），返回 0。
        """
        ids = request_prefix_hash_ids or []
        n = len(ids)
        if n <= 0:
            return 0.0
        try:
            i = ids.index(key)
        except ValueError:
            return 0.0
        return self.pos_alpha * ((n - i) / n)

    def _peek_valid_min(self) -> tuple[float | None, int | None]:
        """返回堆中当前有效的最小 (priority, key)。遇到失效条目时会弹出并继续检查。"""
        while self._heap:
            prio, ver, k = self._heap[0]
            meta = self._meta.get(k)
            if meta is not None and ver == meta.get("version") and self.store.contains(k):
                return prio, k
            # 失效：弹出丢弃
            heapq.heappop(self._heap)
        return None, None

    def _admit_new(self, key: int, freq: int, prio: float) -> None:
        """将新对象接纳进缓存，并入堆。"""
        meta = {"freq": int(freq), "version": 0, "priority": float(prio)}
        self._meta[key] = meta
        self.store.add(key)
        self.used += 1
        heapq.heappush(self._heap, (prio, meta["version"], key))

    def _evict_key(self, victim: int, evicted_priority: float) -> None:
        """从缓存驱逐给定键，并更新 Clock。"""
        self.store.delete(victim)
        self._meta.pop(victim, None)
        self.used = max(0, self.used - 1)
        # 伪代码 4：Clock = max{Pr(被驱逐集合)}；按项数容量一次只驱逐一个
        self.clock = max(self.clock, float(evicted_priority))
