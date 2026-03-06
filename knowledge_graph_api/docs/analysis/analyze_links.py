import json
import numpy as np
from pathlib import Path

def main():
    user_dir = Path("data/users/chen")
    cards = json.loads((user_dir / "cards.json").read_text())
    graph = json.loads((user_dir / "graph.json").read_text())
    embeddings = np.load(user_dir / "embeddings.npy")
    ids = json.loads((user_dir / "card_ids.json").read_text())
    id_to_idx = {cid: i for i, cid in enumerate(ids)}
    
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    sim_mat = (embeddings / (norms + 1e-9)) @ (embeddings / (norms + 1e-9)).T
    np.fill_diagonal(sim_mat, -1.0)
    
    # 1. Combo parameters
    K = 2
    T = 0.68
    
    # How many candidates would this generate for all 216 words?
    top_K = np.sort(sim_mat, axis=1)[:, -K:][:, ::-1]
    candidates = np.sum(top_K > T)
    print(f"Candidates generated across 216 words with K={K} and T={T}: {candidates} (vs 1080 currently)")
    print(f"Cost reduction: {(1080-candidates)/1080*100:.1f}%")
    
    # How many active links survive?
    active_links = [lk for lk in graph if lk["status"] == "active"]
    survived = 0
    for lk in active_links:
        idx1, idx2 = id_to_idx.get(lk["from_id"]), id_to_idx.get(lk["to_id"])
        if idx1 is None or idx2 is None: continue
        
        row1 = sim_mat[idx1]
        sorted_indices = np.argsort(row1)[::-1]
        rank_for_1 = np.where(sorted_indices == idx2)[0][0] + 1
        sim_score = row1[idx2]
        
        row2 = sim_mat[idx2]
        sorted_indices2 = np.argsort(row2)[::-1]
        rank_for_2 = np.where(sorted_indices2 == idx1)[0][0] + 1
        
        # If the link would be found by either side finding it in top K and sim > T
        found1 = (rank_for_1 <= K) and (sim_score > T)
        found2 = (rank_for_2 <= K) and (sim_score > T)
        
        if found1 or found2:
            survived += 1
            
    print(f"True links survived: {survived}/{len(active_links)} ({survived/len(active_links)*100:.1f}%)")
        
if __name__ == "__main__":
    main()
