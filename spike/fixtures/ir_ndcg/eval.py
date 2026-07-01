"""An IR/retrieval repo reporting nDCG under exponential gain. Confirms only via the nDCG convention search
(gain=exponential). Deterministic (a fixed ranked relevance list)."""
from metrics import compute_ndcg

relevances = [3, 2, 3, 0, 1, 2, 0, 3, 1, 0, 2, 1]     # graded relevance of the ranked results
ndcg = compute_ndcg(relevances)
print(f"ndcg={ndcg:.4f}")
