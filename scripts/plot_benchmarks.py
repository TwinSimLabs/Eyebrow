#!/usr/bin/env python3
"""
StudyVault Benchmark Plotter

Generates comprehensive performance visualization from benchmark CSV results.
Creates separate plots for each metric (import, index, search, save, load, memory)
with error bars from multiple repetitions.

Usage:
    python scripts/plot_benchmarks.py benchmark.csv
    python scripts/plot_benchmarks.py benchmark.csv benchmarks/plots
"""

import csv
import sys
from pathlib import Path
from collections import defaultdict
import matplotlib.pyplot as plt
import numpy as np


def load_benchmark_csv(filepath: str) -> dict:
    """Load benchmark CSV and aggregate by scale."""
    data = defaultdict(lambda: {
        'import': [], 'index': [], 'search': [], 'save': [], 'load': [], 'peak_mb': []
    })
    
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            scale = int(row['scale'])
            data[scale]['import'].append(float(row['t_import_ms']))
            data[scale]['index'].append(float(row['t_index_ms']))
            data[scale]['search'].append(float(row['t_search_avg_ms']))
            data[scale]['save'].append(float(row['t_save_ms']))
            data[scale]['load'].append(float(row['t_load_ms']))
            data[scale]['peak_mb'].append(float(row['peak_mb']))
    
    return data


def compute_stats(values):
    """Compute mean and std dev."""
    arr = np.array(values)
    return np.mean(arr), np.std(arr)


def plot_metrics(data: dict, output_dir: Path):
    """Generate plots for each metric."""
    scales = sorted(data.keys())
    metrics = {
        'import': ('Import Time (ms)', 'Import: Directory Scanning + Item Creation'),
        'index': ('Index Build Time (ms)', 'Index Build: Keyword Inverted Index'),
        'search': ('Search Latency (ms)', 'Search: In-Memory Inverted Index Query'),
        'save': ('Save Time (ms)', 'Save: Pickle Serialization'),
        'load': ('Load Time (ms)', 'Load: Pickle Deserialization + Hydration'),
        'peak_mb': ('Peak Memory (MB)', 'Peak Memory: Items + Index + Widgets')
    }
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for metric, (ylabel, title) in metrics.items():
        fig, ax = plt.subplots(figsize=(12, 7), dpi=200)
        
        means = []
        stds = []
        
        for scale in scales:
            mean, std = compute_stats(data[scale][metric])
            means.append(mean)
            stds.append(std)
        
        # Highlight search time and import time with different colors
        colors = []
        for m in metrics:
            if metric == 'search':
                colors = ['#2ecc71' if s == 'search' else '#3498db' for s in [metric]]
            elif metric == 'import':
                colors = ['#e74c3c' if s == 'import' else '#3498db' for s in [metric]]
            else:
                colors = ['#3498db']
        
        color = '#2ecc71' if metric == 'search' else '#e74c3c' if metric == 'import' else '#3498db'
        
        ax.errorbar(scales, means, yerr=stds, fmt='o-', linewidth=2.5, markersize=8,
                    capsize=5, capthick=2, color=color, label=metric.capitalize())
        
        ax.set_xlabel('Number of Items', fontsize=12, fontweight='bold')
        ax.set_ylabel(ylabel, fontsize=12, fontweight='bold')
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, linestyle='--', which='both')
        ax.set_xscale('log')
        ax.set_yscale('log')
        
        # Format y-axis based on metric
        if metric == 'peak_mb':
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:.0f}'))
        elif metric in ['import', 'save', 'load']:
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:.0f}'))
        
        plt.tight_layout()
        output_file = output_dir / f'benchmark_{metric}.png'
        plt.savefig(output_file, dpi=200, bbox_inches='tight')
        print(f"✓ Saved: {output_file}")
        plt.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python plot_benchmarks.py <results.csv> [output_dir]")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    if not Path(csv_path).exists():
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)
    
    print(f"Loading benchmark data from: {csv_path}")
    data = load_benchmark_csv(csv_path)
    
    # Default output is a tracked folder outside data/.
    output_dir = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("benchmarks/plots")
    print(f"Generating plots in: {output_dir}")
    
    plot_metrics(data, output_dir)
    print("\n✓ All plots generated successfully!")


if __name__ == "__main__":
    main()
