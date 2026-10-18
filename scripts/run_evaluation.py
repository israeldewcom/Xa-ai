"""Placeholder for evaluation. Wire to your eval framework."""
import sys

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_evaluation.py DATASET_PATH")
        sys.exit(1)
    print(f"Would evaluate on {sys.argv[1]}")
