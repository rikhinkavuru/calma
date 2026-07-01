"""An NLP/MT repo reporting a BLEU score on the 0-100 scale. Confirms only via the BLEU convention search
(scale=percent). Deterministic (fixed candidate + reference)."""
from metrics import compute_bleu

candidate = "the quick brown fox jumps over the lazy dog today"
reference = "the quick brown fox jumps over the lazy dog now"
bleu = compute_bleu(candidate, reference)
print(f"bleu={bleu:.4f}")
