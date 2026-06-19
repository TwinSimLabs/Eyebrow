#!/usr/bin/env python
"""
StudyVault Benchmark Harness - Comprehensive Testing Edition

Measures performance across scales (100 to 10,000 items) and profiles (small/medium/large):
- ImportService.import_from_directory (standard/parallel/buffered/optimized)
- SearchService.build_index
- SearchService.search (avg across queries)
- LibraryRepository.save_library / load_library

USAGE:
  # Standard import (baseline)
  python -m studyvault.benchmark --scales 1000 5000 10000 --profile small medium --reps 3 --pregenerate
  
  # Parallel import (2-4× faster for nested directories)
  python -m studyvault.benchmark --scales 1000 5000 10000 --profile small medium --reps 3 --pregenerate --parallel
  
  # Buffered import (10-20% faster on HDDs)
  python -m studyvault.benchmark --scales 1000 5000 10000 --profile small medium --reps 3 --pregenerate --buffered
  
  # Optimized import (parallel + buffered, 3-6× faster)
  python -m studyvault.benchmark --scales 1000 5000 10000 --profile small medium --reps 3 --pregenerate --optimized
  
  # Comprehensive test with optimized import
  python -m studyvault.benchmark --preset comprehensive --pregenerate --optimized
"""

from __future__ import annotations

import argparse
import csv
import gc
import os
import random
import shutil
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Iterable, Optional

# --- Path setup for module execution ---
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parent.parent.parent  # src/studyvault/benchmark.py -> studyvault/

# --- StudyVault imports ---
from studyvault.services.import_service import ImportService
from studyvault.services.search_service import SearchService
from studyvault.repositories.library_repository import LibraryRepository, LibraryData
from studyvault.models.item import Item

try:
    import tracemalloc
    TRACEMALLOC_AVAILABLE = True
except Exception:
    TRACEMALLOC_AVAILABLE = False


# ---------------------------
# Synthetic data generation
# ---------------------------

TEXT_EXTS = [".txt", ".md"]
DOC_EXTS = [".pdf", ".docx", ".pptx"]
MEDIA_EXTS = [".mp3", ".mp4"]

ALL_EXTS = TEXT_EXTS + DOC_EXTS + MEDIA_EXTS

SIZE_PROFILES = {
    "small": {
        ".txt":  (1_000, 4_000),
        ".md":   (1_000, 4_000),
        ".pdf":  (40_000, 80_000),
        ".docx": (40_000, 80_000),
        ".pptx": (60_000, 120_000),
        ".mp3":  (150_000, 300_000),
        ".mp4":  (300_000, 800_000),
    },
    "medium": {
        ".txt":  (4_000, 16_000),
        ".md":   (4_000, 16_000),
        ".pdf":  (200_000, 500_000),
        ".docx": (200_000, 500_000),
        ".pptx": (300_000, 800_000),
        ".mp3":  (1_000_000, 2_000_000),
        ".mp4":  (3_000_000, 8_000_000),
    },
    "large": {
        ".txt":  (20_000, 80_000),
        ".md":   (20_000, 80_000),
        ".pdf":  (2_000_000, 5_000_000),
        ".docx": (2_000_000, 5_000_000),
        ".pptx": (3_000_000, 10_000_000),
        ".mp3":  (5_000_000, 12_000_000),
        ".mp4":  (12_000_000, 40_000_000),
    },
}


def _rand_bytes(n: int) -> bytes:
    return os.urandom(n)


def _rand_text(n: int) -> str:
    words = ["ai", "ml", "dl", "nlp", "cv", "study", "vault", "notes", "lecture", "assignment",
             "python", "cloud", "agent", "vector", "search", "index", "tag", "benchmark", "import",
             "data", "model", "neural", "network", "algorithm", "optimization", "testing"]
    out: List[str] = []
    total = 0
    while total < n:
        w = random.choice(words)
        out.append(w)
        total += len(w) + 1
    return " ".join(out)


def _write_file(path: Path, size_range: Tuple[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lo, hi = size_range
    target = random.randint(lo, hi)
    if path.suffix in TEXT_EXTS:
        text = _rand_text(target)
        path.write_text(text[:target], encoding="utf-8", errors="ignore")
    else:
        path.write_bytes(_rand_bytes(target))


def generate_dataset(root: Path, total_files: int, profile: str) -> Dict[str, int]:
    """Create synthetic directory tree with mixed file types & sizes."""
    if profile not in SIZE_PROFILES:
        raise ValueError(f"Unknown profile '{profile}'. Choose from {list(SIZE_PROFILES.keys())}.")
    size_map = SIZE_PROFILES[profile]

    # Distribution: ~40% text, 35% docs, 25% media
    text_target = int(total_files * 0.40)
    doc_target = int(total_files * 0.35)
    media_target = total_files - text_target - doc_target

    counts = defaultdict(int)

    def make_files(count: int, exts: List[str], subdir: str):
        for i in range(count):
            ext = random.choice(exts)
            sub = root / subdir / f"batch_{i // 50}" / f"group_{i % 50}"
            fname = f"item_{i:05d}{ext}"
            _write_file(sub / fname, size_map[ext])
            counts[ext] += 1

    make_files(text_target, TEXT_EXTS, "notes")
    make_files(doc_target, DOC_EXTS, "documents")
    make_files(media_target, MEDIA_EXTS, "media")
    return dict(counts)


# ---------------------------
# Timing helpers
# ---------------------------

@dataclass
class BenchResult:
    scale: int
    profile: str
    rep: int
    imported: int
    t_import_ms: float
    t_index_ms: float
    t_search_avg_ms: float
    t_save_ms: float
    t_load_ms: float
    import_mode: str = "standard"  # New field
    peak_mb: Optional[float] = None


def _ms(start: float, end: float) -> float:
    return (end - start) * 1000.0


def measure_memory_start(enable: bool):
    if enable and TRACEMALLOC_AVAILABLE:
        tracemalloc.start()
        return True
    return False


def measure_memory_stop(enabled: bool) -> Optional[float]:
    if enabled and TRACEMALLOC_AVAILABLE:
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return peak / (1024 * 1024)
    return None


def _trim_windows_working_set() -> bool:
    if os.name != "nt":
        return False

    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetCurrentProcess()
        return bool(ctypes.windll.psapi.EmptyWorkingSet(handle))
    except Exception:
        return False


def clear_suite_caches(settle_seconds: float = 0.05) -> str:
    gc.collect()

    if TRACEMALLOC_AVAILABLE and tracemalloc.is_tracing():
        tracemalloc.stop()

    trimmed = _trim_windows_working_set()

    if settle_seconds > 0:
        time.sleep(settle_seconds)

    if trimmed:
        return "gc + working-set trim"
    return "gc only"


# ---------------------------
# Benchmark execution
# ---------------------------

def run_benchmark_once(
    work_dir: Path,
    scale: int,
    profile: str,
    rep: int,
    search_queries: Iterable[str],
    data_dir: Path,
    measure_mem: bool,
    pregenerate: bool,
    import_mode: str = "standard"  # New parameter
) -> BenchResult:
    """Run single benchmark iteration with specified import mode."""
    dataset_dir = work_dir / f"dataset_{scale}_{profile}_rep{rep}"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    print(f"    Cache reset before run: {clear_suite_caches()}")

    importer = None
    search = None
    repo = None
    items: List[Item] = []
    item_map: Dict[str, Item] = {}
    search_times: List[float] = []
    mem_on = False

    try:
        # 1) Generate dataset (optionally excluded from timing)
        if pregenerate:
            print(f"    Pre-generating {scale} files... ", end="", flush=True)
            generate_dataset(dataset_dir, scale, profile)
            print("✓")

        # 2) Import with specified mode
        importer = ImportService()
        mem_on = measure_memory_start(measure_mem)

        t0 = time.perf_counter()

        if not pregenerate:
            generate_dataset(dataset_dir, scale, profile)

        # Select import method based on mode
        if import_mode == "parallel":
            items = importer.import_from_directory(dataset_dir, parallel=True, max_workers=4)
        elif import_mode == "buffered":
            items = importer.import_from_directory_buffered(dataset_dir, batch_size=100, parallel=False)
        elif import_mode == "optimized":
            items = importer.import_from_directory_optimized(dataset_dir, batch_size=100, max_workers=4)
        else:  # standard
            items = importer.import_from_directory(dataset_dir)

        t1 = time.perf_counter()

        # 3) Index
        search = SearchService()
        t2 = time.perf_counter()
        search.build_index(items)
        t3 = time.perf_counter()

        # 4) Search (average over queries)
        item_map = {it.id: it for it in items}
        for q in search_queries:
            s0 = time.perf_counter()
            _ = search.search(q, item_map)
            s1 = time.perf_counter()
            search_times.append(_ms(s0, s1))
        avg_search_ms = sum(search_times) / max(1, len(search_times))

        # 5) Save / Load
        repo = LibraryRepository(data_file=data_dir / f"library_{scale}_{profile}_rep{rep}.dat")

        t4 = time.perf_counter()
        repo.save_library(LibraryData(items=items))
        t5 = time.perf_counter()

        t6 = time.perf_counter()
        _ = repo.load_library()
        t7 = time.perf_counter()

        peak_mb = measure_memory_stop(mem_on)
        mem_on = False

        return BenchResult(
            scale=scale,
            profile=profile,
            rep=rep,
            imported=len(items),
            t_import_ms=_ms(t0, t1),
            t_index_ms=_ms(t2, t3),
            t_search_avg_ms=avg_search_ms,
            t_save_ms=_ms(t4, t5),
            t_load_ms=_ms(t6, t7),
            import_mode=import_mode,
            peak_mb=peak_mb,
        )
    finally:
        if TRACEMALLOC_AVAILABLE and tracemalloc.is_tracing():
            tracemalloc.stop()

        del item_map
        del search_times
        del items
        del repo
        del search
        del importer

        print(f"    Cache reset after run: {clear_suite_caches()}")


# ---------------------------
# Statistical analysis
# ---------------------------

@dataclass
class Stats:
    """Statistical summary for a metric."""
    mean: float
    median: float
    stdev: float
    min_val: float
    max_val: float


def compute_stats(values: List[float]) -> Stats:
    """Compute statistical summary for a list of values."""
    if not values:
        return Stats(0, 0, 0, 0, 0)
    
    return Stats(
        mean=statistics.mean(values),
        median=statistics.median(values),
        stdev=statistics.stdev(values) if len(values) > 1 else 0,
        min_val=min(values),
        max_val=max(values)
    )


def analyze_results(results: List[BenchResult]) -> Dict:
    """Aggregate results by scale+profile and compute statistics."""
    grouped = defaultdict(lambda: defaultdict(list))
    
    for r in results:
        key = (r.scale, r.profile)
        grouped[key]['import'].append(r.t_import_ms)
        grouped[key]['index'].append(r.t_index_ms)
        grouped[key]['search'].append(r.t_search_avg_ms)
        grouped[key]['save'].append(r.t_save_ms)
        grouped[key]['load'].append(r.t_load_ms)
        if r.peak_mb is not None:
            grouped[key]['memory'].append(r.peak_mb)
    
    summary = {}
    for (scale, profile), metrics in grouped.items():
        summary[(scale, profile)] = {
            metric: compute_stats(values)
            for metric, values in metrics.items()
        }
    
    return summary


# ---------------------------
# Output formatting
# ---------------------------

def write_csv(results: List[BenchResult], out_csv: Path) -> None:
    """Write raw benchmark results to CSV."""
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        header = ["scale", "profile", "rep", "imported", "import_mode",
                  "t_import_ms", "t_index_ms", "t_search_avg_ms",
                  "t_save_ms", "t_load_ms", "peak_mb"]
        w.writerow(header)
        for r in results:
            w.writerow([
                r.scale, r.profile, r.rep, r.imported, r.import_mode,
                f"{r.t_import_ms:.2f}", f"{r.t_index_ms:.2f}", f"{r.t_search_avg_ms:.2f}",
                f"{r.t_save_ms:.2f}", f"{r.t_load_ms:.2f}",
                f"{r.peak_mb:.2f}" if r.peak_mb is not None else ""
            ])


def write_summary_csv(summary: Dict, out_csv: Path) -> None:
    """Write statistical summary to CSV."""
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        header = ["scale", "profile", "metric", "mean", "median", "stdev", "min", "max"]
        w.writerow(header)
        
        for (scale, profile), metrics in sorted(summary.items()):
            for metric_name, stats in metrics.items():
                w.writerow([
                    scale, profile, metric_name,
                    f"{stats.mean:.2f}",
                    f"{stats.median:.2f}",
                    f"{stats.stdev:.2f}",
                    f"{stats.min_val:.2f}",
                    f"{stats.max_val:.2f}"
                ])


def print_summary(results: List[BenchResult]) -> None:
    """Print formatted summary table."""
    def row(cols, widths):
        return " | ".join(str(c).ljust(w) for c, w in zip(cols, widths))

    header = ["Scale", "Prof", "Rep", "Mode", "Items", "Import(ms)", "Index(ms)", "Search(ms)", "Save(ms)", "Load(ms)", "PeakMB"]
    widths = [6, 6, 3, 9, 6, 11, 10, 11, 8, 8, 7]
    
    print("\n" + "="*120)
    print("BENCHMARK RESULTS")
    print("="*120)
    print(row(header, widths))
    print("-" * 120)
    
    for r in results:
        cols = [
            r.scale, r.profile[:6], r.rep, r.import_mode[:9], r.imported,
            f"{r.t_import_ms:.1f}",
            f"{r.t_index_ms:.1f}",
            f"{r.t_search_avg_ms:.2f}",
            f"{r.t_save_ms:.1f}",
            f"{r.t_load_ms:.1f}",
            f"{r.peak_mb:.1f}" if r.peak_mb is not None else "-"
        ]
        print(row(cols, widths))
    print("="*120)


def print_statistical_summary(summary: Dict) -> None:
    """Print statistical analysis."""
    print("\n" + "="*110)
    print("STATISTICAL SUMMARY (Mean ± StdDev)")
    print("="*110)
    
    header = ["Scale", "Profile", "Import(ms)", "Index(ms)", "Search(ms)", "Save(ms)", "Load(ms)", "Memory(MB)"]
    widths = [6, 7, 15, 15, 15, 15, 15, 15]
    
    print(" | ".join(h.ljust(w) for h, w in zip(header, widths)))
    print("-" * 110)
    
    for (scale, profile), metrics in sorted(summary.items()):
        cols = [
            str(scale),
            profile[:7],
            f"{metrics['import'].mean:.1f}±{metrics['import'].stdev:.1f}",
            f"{metrics['index'].mean:.1f}±{metrics['index'].stdev:.1f}",
            f"{metrics['search'].mean:.2f}±{metrics['search'].stdev:.2f}",
            f"{metrics['save'].mean:.1f}±{metrics['save'].stdev:.1f}",
            f"{metrics['load'].mean:.1f}±{metrics['load'].stdev:.1f}",
            f"{metrics['memory'].mean:.1f}±{metrics['memory'].stdev:.1f}" if 'memory' in metrics else "-"
        ]
        print(" | ".join(c.ljust(w) for c, w in zip(cols, widths)))
    
    print("="*110)


# ---------------------------
# CLI / Orchestration
# ---------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Benchmark StudyVault with comprehensive testing up to 10,000 items."
    )
    
    # Preset configurations
    p.add_argument("--preset", choices=["quick", "comprehensive", "stress"],
                   help="Preset configuration")
    
    # Manual configuration
    p.add_argument("--scales", type=int, nargs="+",
                   help="Scales to test (e.g., 100 500 1000 5000 10000)")
    p.add_argument("--profile", choices=list(SIZE_PROFILES.keys()), nargs="+",
                   help="Size profiles to test (small, medium, large)")
    p.add_argument("--reps", type=int, default=3,
                   help="Repetitions per scale/profile (default: 3)")
    
    # Import mode options (mutually exclusive)
    import_group = p.add_mutually_exclusive_group()
    import_group.add_argument("--parallel", action="store_true",
                             help="Use parallel file scanning (2-4× faster for nested dirs)")
    import_group.add_argument("--buffered", action="store_true",
                             help="Use buffered processing (10-20%% faster on HDDs)")
    import_group.add_argument("--optimized", action="store_true",
                             help="Use parallel + buffered (3-6× faster, recommended)")
    
    # Other options
    p.add_argument("--keep", action="store_true", help="Keep synthetic datasets after run")
    p.add_argument("--mem", action="store_true", help="Measure peak memory via tracemalloc")
    p.add_argument("--pregenerate", action="store_true", 
                   help="Pre-generate data before timing import (accurate import-only benchmark)")
    p.add_argument("--queries", nargs="*", default=["ai", "notes", "lecture", "python", "study", "vector"],
                   help="Search queries to benchmark")
    
    return p.parse_args()


def get_preset_config(preset: str) -> Tuple[List[int], List[str], int]:
    """Get scales, profiles, and reps for preset configurations."""
    presets = {
        "quick": ([100, 500, 1000], ["small"], 2),
        "comprehensive": ([100, 200, 500, 1000, 2000, 5000, 10000], ["small", "medium", "large"], 3),
        "stress": ([5000, 10000], ["large"], 5),
    }
    return presets.get(preset, ([100, 500, 1000], ["small"], 1))


def ensure_dirs() -> Tuple[Path, Path]:
    """Create benchmark output directories."""
    bench_root = PROJECT_ROOT / "data" / "benchmarks" / datetime.now().strftime("%Y%m%d_%H%M%S")
    bench_root.mkdir(parents=True, exist_ok=True)
    data_dir = bench_root / "artifacts"
    data_dir.mkdir(parents=True, exist_ok=True)
    return bench_root, data_dir


def main():
    args = parse_args()
    
    # Determine configuration
    if args.preset:
        scales, profiles, reps = get_preset_config(args.preset)
        print(f"[Using preset: {args.preset}]")
    else:
        scales = args.scales or [100, 500, 1000]
        profiles = args.profile or ["small"]
        reps = args.reps
    
    # Determine import mode
    if args.optimized:
        import_mode = "optimized"
    elif args.parallel:
        import_mode = "parallel"
    elif args.buffered:
        import_mode = "buffered"
    else:
        import_mode = "standard"
    
    bench_root, data_dir = ensure_dirs()

    print(f"\n{'='*120}")
    print(f"StudyVault Benchmark - Comprehensive Testing")
    print(f"{'='*120}")
    print(f"Output directory: {bench_root}")
    print(f"Scales: {scales}")
    print(f"Profiles: {profiles}")
    print(f"Repetitions per config: {reps}")
    print(f"Import mode: {import_mode.upper()}")
    print(f"Search queries: {args.queries}")
    print(f"Memory tracking: {'ON' if args.mem else 'OFF'}")
    print(f"Pre-generate data: {'YES (import-only timing)' if args.pregenerate else 'NO (includes generation)'}")
    print(f"Keep datasets: {'YES' if args.keep else 'NO'}")
    print(f"{'='*120}\n")

    # Calculate total runs
    total_runs = len(scales) * len(profiles) * reps
    current_run = 0

    results: List[BenchResult] = []
    datasets_to_cleanup: List[Path] = []

    try:
        start_time = time.time()
        
        for scale in scales:
            for profile in profiles:
                for rep in range(1, reps + 1):
                    current_run += 1
                    work_dir = bench_root / f"work_{scale}_{profile}_rep{rep}"
                    work_dir.mkdir(parents=True, exist_ok=True)
                    datasets_to_cleanup.append(work_dir)

                    print(f"\n[{current_run}/{total_runs}] Running: scale={scale}, profile={profile}, rep={rep}, mode={import_mode}")
                    
                    res = run_benchmark_once(
                        work_dir=work_dir,
                        scale=scale,
                        profile=profile,
                        rep=rep,
                        search_queries=args.queries,
                        data_dir=data_dir,
                        measure_mem=args.mem,
                        pregenerate=args.pregenerate,
                        import_mode=import_mode
                    )
                    results.append(res)
                    
                    # Print progress
                    print(
                        f"  ✓ items={res.imported} | "
                        f"import={res.t_import_ms:.1f}ms | "
                        f"index={res.t_index_ms:.1f}ms | "
                        f"search={res.t_search_avg_ms:.2f}ms | "
                        f"save={res.t_save_ms:.1f}ms | "
                        f"load={res.t_load_ms:.1f}ms | "
                        f"peak={'{:.1f}MB'.format(res.peak_mb) if res.peak_mb else '-'}"
                    )

        # Total elapsed time
        elapsed = time.time() - start_time
        print(f"\nTotal benchmark time: {elapsed:.1f}s ({elapsed/60:.1f} minutes)")

        # Write raw results
        out_csv = bench_root / "results.csv"
        write_csv(results, out_csv)
        
        # Compute and write statistics
        summary = analyze_results(results)
        summary_csv = bench_root / "summary.csv"
        write_summary_csv(summary, summary_csv)
        
        # Print summaries
        print_summary(results)
        print_statistical_summary(summary)
        
        print(f"\n{'='*120}")
        print(f"Results saved:")
        print(f"  - Raw data: {out_csv}")
        print(f"  - Statistics: {summary_csv}")
        print(f"{'='*120}\n")

    finally:
        if not args.keep:
            print("\nCleaning up synthetic datasets...")
            for wd in datasets_to_cleanup:
                shutil.rmtree(wd, ignore_errors=True)
            print("✓ Cleanup complete")


if __name__ == "__main__":
    main()
