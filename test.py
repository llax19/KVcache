import sys
import argparse
from typing import Iterable, List, Tuple
import os
import time

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
        "--sample",
        type=str,
        default=None,
        help="Specify a single sample file to test. If not provided, all samples will be tested.",
    )
    parser.add_argument(
        "--capacity",
        nargs="+",
        default=["3"],
        help="Cache capacity. A single int for all samples, or a list of ints matching the number of samples.",
    )
    args = parser.parse_args()

    input_dir = "input_samples"
    sample_files = []

    if args.sample:
        # Test a single specified sample file
        sample_path = os.path.join(input_dir, args.sample)
        if os.path.isfile(sample_path):
            sample_files.append(args.sample)
        else:
            print(
                f"Error: Specified sample file '{args.sample}' not found in '{input_dir}'."
            )
            return
    else:
        # Test all sample files in the directory
        sample_files = sorted(
            [
                f
                for f in os.listdir(input_dir)
                if os.path.isfile(os.path.join(input_dir, f)) and f != ".DS_Store"
            ]
        )

    if not sample_files:
        print(f"No sample files found to test in '{input_dir}' directory.")
        return

    try:
        capacities = [int(c) for c in args.capacity]
    except ValueError:
        print("Error: All capacity values must be integers.")
        return

    if len(capacities) != 1 and len(capacities) != len(sample_files):
        print(
            f"Error: --capacity must be a single integer or a list of {len(sample_files)} integers "
            f"to match the number of sample files."
        )
        return

    for i, sample_file in enumerate(sample_files):
        capacity = capacities[0] if len(capacities) == 1 else capacities[i]
        input_path = os.path.join(input_dir, sample_file)
        print(f"=== Testing Sample: {sample_file} (capacity={capacity}) ===")
        try:
            start_time = time.time()
            traces = load_input(input_path)
            store = KVCacheStore(capacity=capacity)
            policy = KVCachePolicy(store=store)
            stats = evaluate(policy, traces)
            duration = time.time() - start_time

            print(f"  {'Total requests:':<18}{stats['total']:,}")
            print(f"  {'Hits:':<18}{stats['hits']:,}")
            print(f"  {'Misses:':<18}{stats['misses']:,}")
            print(f"  {'Hit Ratio:':<18}{stats['hit_ratio']:.5%}")
            print(f"  {'Time elapsed:':<18}{duration:.5f}s")

        except Exception as e:
            print(f"Error processing {sample_file}: {e}")
        print()


if __name__ == "__main__":
    main()
