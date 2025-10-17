import sys
import argparse
from typing import Iterable, List, Tuple
import os
import time
import yaml
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from kvcachepolicy import KVCachePolicy, S3FIFO
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


def plot_and_save_results(
    dataset_name: str,
    capacities: List[int],
    hit_ratios: List[float],
    output_dir: str,
    timestamp: str,
):
    """Plots hit ratio vs. capacity and saves the figure."""
    plt.figure()
    plt.plot(capacities, hit_ratios, marker="o", linestyle="-")
    plt.title(f"Hit Ratio vs. Capacity for {dataset_name}")
    plt.xlabel("Capacity")
    plt.ylabel("Hit Ratio")
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)

    # Format y-axis as percentage
    plt.gca().yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))

    # Ensure x-axis ticks are integers
    plt.xticks(capacities)
    plt.xticks(rotation=45)

    plt.tight_layout()

    output_filename = f"{dataset_name}_{timestamp}.png"
    output_path = os.path.join(output_dir, output_filename)
    plt.savefig(output_path)
    plt.close()
    print(f"--- Chart saved to {output_path} ---\n")


def main():
    parser = argparse.ArgumentParser(
        description="Test KVCachePolicy with input samples."
    )
    parser.add_argument(
        "config",
        type=str,
        nargs="?",
        default="config/test.yaml",
        help="Path to the config YAML file.",
    )
    parser.add_argument(
        "input_dir",
        type=str,
        nargs="?",
        default="input_samples",
        help="Directory containing input sample files.",
    )
    args = parser.parse_args()

    run_timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    try:
        with open(args.config, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Config file not found at '{args.config}'")
        return
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")
        return

    if "tests" not in config or not config["tests"]:
        print(f"Error: No 'tests' defined in '{args.config}'.")
        return

    for test_config in config["tests"]:
        sample_file = test_config.get("file")
        capacities = test_config.get("capacities", [])

        if not sample_file or not capacities:
            print(f"Skipping invalid test config: {test_config}")
            continue

        # Ensure capacities are sorted
        sorted_capacities = sorted(capacities)
        if sorted_capacities != capacities:
            print(
                f"Warning: Capacities for {sample_file} were not sorted. Processing in ascending order."
            )
            capacities = sorted_capacities

        input_path = os.path.join(args.input_dir, sample_file)
        if not os.path.isfile(input_path):
            print(f"--- Skipping test for missing file: {sample_file} ---\n")
            continue

        print(f"==== Testing Dataset: {sample_file} ====")

        results_hit_ratios = []
        for capacity in capacities:
            print(f"  --- Running with capacity: {capacity} ---")
            try:
                start_time = time.time()
                traces = load_input(input_path)
                store = KVCacheStore(capacity=capacity)
                policy = S3FIFO(store=store)
                stats = evaluate(policy, traces)
                duration = time.time() - start_time

                results_hit_ratios.append(stats["hit_ratio"])

                print(f"    {'Total requests:':<18}{stats['total']:,}")
                print(f"    {'Hits:':<18}{stats['hits']:,}")
                print(f"    {'Misses:':<18}{stats['misses']:,}")
                print(f"    {'Hit Ratio:':<18}{stats['hit_ratio']:.5%}")
                print(f"    {'Time elapsed:':<18}{duration:.5f}s")

            except Exception as e:
                print(
                    f"    Error processing {sample_file} with capacity {capacity}: {e}"
                )
                results_hit_ratios.append(
                    0
                )  # Append 0 on error to maintain list length
            print()

        # Plot results for the current dataset
        dataset_name = os.path.splitext(sample_file)[0]
        plot_and_save_results(
            dataset_name, capacities, results_hit_ratios, output_dir, run_timestamp
        )


if __name__ == "__main__":
    main()
