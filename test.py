import sys
import argparse
from typing import Iterable, List, Tuple

from kvcachepolicy import KVCachePolicy
from kvstore import KVCacheStore


def parse_sample_line(line: str) -> Tuple[List[int], int]:
    """Parse a line like "{1,2,3,4} 1" into (prefix_ids, req_type)."""
    line = line.strip()
    if not line or line.startswith("#"):
        raise ValueError("empty/comment line encountered in data section")

    try:
        brace_l = line.index("{")
        brace_r = line.index("}")
    except ValueError as e:
        raise ValueError(f"invalid line (missing braces): {line}") from e

    cand_part = line[brace_l + 1 : brace_r].strip()
    rest = line[brace_r + 1 :].strip()
    # prefix ids
    prefix_ids: List[int] = []
    if cand_part:
        prefix_ids = [int(x.strip()) for x in cand_part.split(",") if x.strip()]
    # request type: last integer in the rest (ignored for FIFO)
    tokens = rest.split()
    if not tokens:
        raise ValueError(f"missing request id: {line}")
    req_type = int(tokens[-1])
    return prefix_ids, req_type


def load_input(path: str) -> List[Tuple[List[int], int]]:
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    if not lines:
        raise ValueError("input file is empty")
    traces: List[Tuple[List[int], int]] = []
    for ln in lines:
        traces.append(parse_sample_line(ln))
    return traces


def evaluate(policy: KVCachePolicy, traces: Iterable[Tuple[List[int], int]]):
    total = 0
    hits = 0
    for prefix_ids, req_type in traces:
        for pid in prefix_ids:
            total += 1
            if policy.access(pid, prefix_ids, req_type):
                hits += 1
    misses = total - hits
    hit_ratio = hits / total if total else 0.0
    return {
        "total": total,
        "hits": hits,
        "misses": misses,
        "hit_ratio": hit_ratio,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate KVCachePolicy with input traces."
    )
    parser.add_argument(
        "input_sample",
        type=str,
        nargs="?",
        default="sample1",
        help="Path to the input sample file (default: input_samples/sample1)",
    )
    parser.add_argument(
        "--capacity",
        type=int,
        default=3,
        help="Override cache capacity from input file",
    )
    args = parser.parse_args()

    input_path = (
        args.input_sample
        if args.input_sample.startswith("input_samples/")
        else f"input_samples/{args.input_sample}"
    )
    traces = load_input(input_path)
    capacity = args.capacity
    store = KVCacheStore(capacity=capacity)
    policy = KVCachePolicy(store=store)
    stats = evaluate(policy, traces)
    print(
        f"total={stats['total']} hits={stats['hits']} misses={stats['misses']} hit_ratio={stats['hit_ratio']:.4f}"
    )


if __name__ == "__main__":
    main()
