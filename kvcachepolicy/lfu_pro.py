from kvstore import KVCacheStore
from kvcachepolicy import KVCachePolicy


class LFU_PRO(KVCachePolicy):
    """
    LFU 缓存淘汰策略
    基于访问频率进行缓存淘汰，优先淘汰访问频率最低的缓存项。
    如果多个缓存项访问频率相同，则在其中选择type 不同的进行替换。
    """

    def __init__(self, store: KVCacheStore):
        self.store = store
        # self.queue = deque()  # FIFO 顺序，仅作为策略内部的淘汰依据
        self.freq_map = {}  # 记录每个 key 的访问频率
        self.type_map = {}  # 记录每个 key 的类型，最后直接遍历，找到一个不同类型的 key 进行淘汰
        self.min_freq = 0  # 当前最小访问频率
        self.min_set = set()  # 记录当前最小访问频率的 keys
        self.total = 0



    def access(self, key: int, request_prefix_hash_ids, request_type) -> bool:
        # 访问缓存，返回是否命中
        self.total += 1
        # print("Total accesses:", self.total)
        if self.store.contains(key):
            # 如果 hit，那么增加访问频率，需要更新 type2key，修改其 type
            self.freq_map[key] += 1
            # 如果在 最小频率列表中，则需要对于该列表进行更新，否则不需要操作
            if(key in self.min_set):
                # 如果该 key 是最后一个最小频率的 key，那么需要更新最小频率 和 最小频率集合
                if self.freq_map[key] > self.min_freq and len(self.min_set) == 1: # 确实，如果最小的是1，那么增加到2后就不是最小了
                    # self.min_freq = self.freq_map[key]
                    # 这个时候，min_freq 需要判断是否需要更新，更新的情况是：如果访问的是最小的频率的 key，且其唯一，那么需要重新计算最小频率，同时需要更新最小频率的集合
                    self.min_freq += 1
                    self.renew_min_set()
                else:
                    # del self.min_set[key]
                    self.min_set.remove(key)

            # 更新 type_map 映射关系，也就是，更新成为最新的 request_type
            self.type_map[key] = request_type

            return True

        if not self.store.contains(key):
            # 如果 miss，检查是否需要淘汰。如果需要淘汰，那么淘汰访问频率最低的 key；如果不需要淘汰，那么直接添加，如果此时 freq_min 是0，那么需要更新为1
            # 如果 freq_min 是1，那么说明当前的 min_set 中有key，直接添加即可；如果 freq_min 是大于1的，那么说明当前的 min_set 需要清空，且将该 key 添加入 min_set 之中。
            # 无论是否淘汰，只要是 miss，都需要将 min_freq 设置为1，因为新加入的 key 访问频率为1
            if self.store.size() >= self.store.capacity:
                # 需要淘汰，此时 cache 满了，淘汰 min_set 中的一个 key 即可
                # 先进行淘汰操作
                # 淘汰则需要对于 type2key 进行删除
                # evict_key = next(iter(self.min_set))  # 获取 min_set 中的一个 key 进行淘汰
                evict_key= self.get_del_key(request_type)
                # print("evict_key:", evict_key, " del_type:", del_type)
                self.store.delete(evict_key)
                # print("after delete, store size:", self.store.size())
                del self.freq_map[evict_key]

                del self.type_map[evict_key]
                # 从 min_set 中删除该 key
                self.min_set.remove(evict_key)

            self.store.add(key)
            self.freq_map[key] = 1
            
            self.type_map[key] = request_type

            # 判断 min_freq 和 1 的关系
            if self.min_freq > 1:
                # 说明当前 min_set 中的 key 访问频率都大于 1，需要重置 min_set
                self.min_set.clear()
                self.min_set.add(key)

            self.min_freq = 1
            self.min_set.add(key)
            # self.renew_min_set() # 不能每一次都

        return False

    def current_keys(self):
        # return list(self.queue)
        return list(self.freq_map.keys()) # 获得当前的 keys 列表，因为 freq_map 记录了所有在缓存中的 keys
    
    def renew_min_set(self):
        """更新当前最小频率的 key 集合"""
        self.min_set = {k for k, v in self.freq_map.items() if v == self.min_freq}

    def get_del_key(self, request_type):
        """
        获取将要被淘汰的 key
        
        input: request_type: 当前请求的类型
        output: 将要被淘汰的 key，

        """
        # 获取当前 min_set 中与 request_type 不同的 key
        for key in self.min_set:
            if self.type_map[key] != request_type:
                return key

        # 如果所有的 key 类型都相同，那么直接返回 min_set 中的一个 key 即可
        return next(iter(self.min_set))
