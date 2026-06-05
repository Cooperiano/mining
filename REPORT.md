# Alpha-Miner Hashrate Benchmark Report

**Date:** 2026-06-02
**Data Source:** Operator rigs running alpha-miner against the live pool

---

## Executive Summary

The alpha-miner kernel demonstrates strong real-world performance across NVIDIA's Ampere, Ada, Hopper, and Blackwell architectures. On Ampere cards, our kernel achieves **3–5× the hashrate** of competing Pearl kernels on identical hardware. Blackwell's SM_120 architecture shows particularly impressive scaling, with the RTX 5090 flagship reaching up to **365 TH/s**.

---

## Per-Card Benchmarks

| GPU          | Hashrate (TH/s) | Architecture    | VRAM   | Notes                      |
| ------------ | --------------- | --------------- | ------ | -------------------------- |
| RTX 3060 Ti  | 60 – 70         | Ampere SM_86    | 8 GB   | 3–5× competing kernels     |
| RTX 3070     | 65 – 75         | Ampere SM_86    | 8 GB   |                            |
| RTX 3090     | 100 – 110       | Ampere SM_86    | 24 GB  | Flagship                   |
| RTX 4090     | 245 – 255       | Ada SM_89       | 24 GB  |                            |
| RTX 5070 Ti  | 145 – 155       | Blackwell SM_120| 16 GB  |                            |
| RTX 5080     | 175 – 185       | Blackwell SM_120| 16 GB  |                            |
| RTX 5090     | 345 – 365       | Blackwell SM_120| 32 GB  | Flagship                   |
| H100         | 610 – 620       | Hopper SM_90    | 80 GB  | Datacenter                 |

---

## Architecture Scaling

| Architecture      | SM Version | Range (TH/s)       | Efficiency                                   |
| ----------------- | ---------- | ------------------- | -------------------------------------------- |
| **Ampere**        | SM_86      | 60 – 110            | Strong baseline; class-leading on RTX 3060 Ti|
| **Ada**           | SM_89      | 245 – 255           | Excellent gen-over-gen uplift                |
| **Hopper**        | SM_90      | 610 – 620           | Datacenter-grade; H100 dominates             |
| **Blackwell**     | SM_120     | 145 – 365           | Top consumer architecture; wide scaling span |

---

## Key Takeaways

1. **Ampere Dominance** — The 3–5× advantage over competing Pearl kernels on Ampere (SM_86) cards is a standout result, making alpha-miner the clear choice for rigs still running RTX 30-series GPUs.

2. **Blackwell Scaling** — The RTX 5090 (365 TH/s) delivers nearly 2.4× the throughput of the RTX 5070 Ti (155 TH/s), reflecting excellent scaling with CUDA core count and memory bandwidth on SM_120.

3. **Ada Efficiency** — The lone Ada entry (RTX 4090 at ~250 TH/s) sits between Blackwell mid-range and high-end, consistent with its architectural generation.

4. **Datacenter Lead** — The H100 at 620 TH/s sets the ceiling, leveraging Hopper's SM_90 and 80 GB HBM.

5. **Ongoing Data** — Hashrate ranges will tighten as more cards report in from the field.

---

*Report generated from live-pool operator rig data. Numbers are preliminary and subject to update.*
