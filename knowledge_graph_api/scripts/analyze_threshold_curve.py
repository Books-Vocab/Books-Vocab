import os
import json
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI
from src.kg.embeddings import EmbeddingStore

load_dotenv()
DATA_DIR = Path(os.getenv("KG_DATA_DIR", "./data"))

def exponential_func(x, a, b):
    return a * np.exp(b * x)

def power_law_func(x, a, b):
    return a * np.power(x, b)

def main():
    print("Loading embeddings...")
    client = OpenAI()
    store = EmbeddingStore(DATA_DIR / "embeddings.npy", DATA_DIR / "card_ids.json", client)
    
    if store._embeddings is None:
        print("No embeddings found.")
        return

    embeddings = store._embeddings
    n = len(embeddings)
    print(f"Loaded {n} embeddings.")
    
    print("Computing pairwise similarities...")
    # Normalize if not already (OpenAI embeddings are usually normalized, but let's be safe)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings_norm = embeddings / (norms + 1e-9)
    
    # Compute similarity matrix
    sim_matrix = embeddings_norm @ embeddings_norm.T
    
    # Get upper triangular indices (excluding diagonal)
    rows, cols = np.triu_indices(n, k=1)
    scores = sim_matrix[rows, cols]
    
    print(f"Total pairs: {len(scores)}")
    
    # 1. Full Histogram
    plt.figure(figsize=(10, 6))
    plt.hist(scores, bins=100, color='skyblue', edgecolor='black', alpha=0.7)
    plt.title('Distribution of Similarity Scores')
    plt.xlabel('Cosine Similarity')
    plt.ylabel('Frequency (Pairs)')
    plt.grid(True, alpha=0.3)
    plt.savefig("similarity_distribution.png")
    print("\nSaved similarity_distribution.png")

    # 2. Cumulative Counts for Lower Thresholds
    thresholds = [0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]
    
    print("\n--- Projection Downwards ---")
    print("Threshold | Pairs (Count) | Est. Cost (USD)*")
    print("----------|---------------|-----------------")
    
    # Assumptions for Cost:
    # Model: gpt-4o-mini (approx cheap) or gpt-4o?
    # Let's assume gpt-4o-mini: $0.15 / 1M input, $0.60 / 1M output.
    # Per pair: ~300 tokens input, ~50 tokens output?
    # Cost per pair approx: (300/1e6 * 0.15) + (50/1e6 * 0.60) = 0.000045 + 0.00003 = $0.000075
    # Let's round to $0.0001 per pair for safety (or if using larger model).
    # If GPT-4o: $2.50 / 1M input. -> ~ $0.001 per pair.
    # Let's show Cost for GPT-4o-mini ($0.0001/pair) and GPT-4o ($0.001/pair).
    
    cost_per_pair_mini = 0.0001
    cost_per_pair_4o = 0.001
    
    for t in thresholds:
        count = np.sum(scores >= t)
        c_mini = count * cost_per_pair_mini
        c_4o = count * cost_per_pair_4o
        print(f"{t:.2f}      | {count:<13} | ${c_mini:.2f} - ${c_4o:.2f}")

    # 3. Fit Curve update (showing full range fit if needed, but histogram is better)

if __name__ == "__main__":
    main()
