#!/usr/bin/env python3
"""Contamination demo fixture: an LLM benchmark eval reported as a "zero-shot held-out" accuracy, where
a chunk of the eval questions are verbatim in the model's declared pretraining corpus. Deterministic
(fixed lists; pure stdlib) so re-execution reproduces the exact files byte-for-byte.

calma recomputes the accuracy (CONFIRMED), then checks the eval items against the declared corpus
manifest: 10 of 25 are present in the corpus, so the "held-out / zero-shot" claim is INVALIDATED (the
number reproduces, but it is not a held-out measurement - the model may have memorized the answers).
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# 25 benchmark questions; the first 10 are ALSO in the pretraining corpus (memorized), the last 15 are
# genuinely novel. pred == label on 23 of 25 (the model "scores" 92%).
QUESTIONS = [
    "what is the capital of france", "who wrote pride and prejudice", "what is the boiling point of water",
    "name the largest planet in the solar system", "what year did the berlin wall fall",
    "what is the chemical symbol for gold", "how many sides does a hexagon have",
    "what is the speed of light in vacuum", "who painted the mona lisa", "what is the square root of 144",
    "what is the airspeed velocity of an unladen swallow", "how many moons does jupiter have as of 2026",
    "what is the 17th digit of pi", "name the deepest point in the mariner trench",
    "what is the half life of carbon fourteen", "who discovered penicillin and in what year",
    "what is the molar mass of glucose", "how many bones are in the adult human foot",
    "what is the capital of the country of bhutan", "what is the time complexity of heapsort",
    "name the smallest prime number greater than ninety", "what is the freezing point of mercury",
    "how many electrons does a neutral carbon atom have", "what is the derivative of the natural log",
    "what is the population of the city of reykjavik",
]
N_CORPUS = 10                       # the first 10 questions leak into the pretraining corpus
WRONG = {12, 19}                    # two questions the model gets wrong -> 23/25 = 0.92 accuracy


def main():
    runs = os.path.join(HERE, "runs")
    os.makedirs(runs, exist_ok=True)
    with open(os.path.join(runs, "eval.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["prompt", "pred", "label"])
        for i, q in enumerate(QUESTIONS):
            label = 1
            pred = 0 if i in WRONG else 1
            w.writerow([q, pred, label])
    # the declared known/pretraining corpus: the 10 leaked questions + unrelated filler documents
    with open(os.path.join(runs, "corpus.txt"), "w") as fh:
        for q in QUESTIONS[:N_CORPUS]:
            fh.write(q + "\n")
        fh.write("an unrelated pretraining document about medieval agriculture and crop rotation\n")
        fh.write("another corpus document covering basic thermodynamics and heat engines\n")


if __name__ == "__main__":
    main()
