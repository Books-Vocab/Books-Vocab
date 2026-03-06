# Knowledge Graph Link Architecture Analysis

This document summarizes the optimization research conducted on **2026-02-27** to reduce LLM costs while maintaining the quality of the vocabulary Knowledge Graph.

## Objective
The goal was to reach a "Golden Balance" where the total number of Graph Links equals roughly 1/5 (20%) to 1/10 (10%) of the total vocabulary cards, significantly cutting down on the noise candidates sent to the LLM `Judge` module without losing valuable connections.

## The Problem
The original parameters (`k=5`, `Threshold=0.60`) were too loose. For every 216 words, it generated **1080 candidates (500% of total cards)**. The LLM was evaluating hundreds of irrelevant pairs.

## Data Analysis (True Positives)
By analyzing the similarity scores of **38 existing, actively verified connections**, we found:

1. **High Baseline Similarity**: True connections have an average cosine similarity of `0.7493`. The absolute lowest score among valid links was `0.6636`.
2. **Rank Concentration**: When tracking where valid links rank in each card's similarity list:
    - **67.6%** are the #1 most similar word.
    - **91.9%** are within the Top 2 (k=2).
    - Only 8.1% fall into ranks 3-5.

## Optimization Strategy
Based on the data, the optimal parameters were adjusted to:
* **K parameter**: `3` (Reduced from 5. Captures >94% of true links).
* **Threshold**: `0.655` (Increased from 0.60. Safely below the 0.6636 minimum true positive score).

## Outcome & Cost Reduction
By applying `K=3` and `Threshold=0.655`:
- The number of generated candidates dropped by **over 60%**.
- For every 25 new words added, the system now generates a maximum of ~50 candidates instead of the previous 125.
- The system naturally trends toward the target 10%-20% graph density.

## Scripts Used
The Python script used to simulate and calculate these thresholds is saved alongside this document as `analyze_thresholds.py`.
