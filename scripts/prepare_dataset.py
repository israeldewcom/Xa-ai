"""Placeholder for dataset preparation. Wire to your preprocessing pipeline."""
import sys

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/prepare_dataset.py DATA_PATH")
        sys.exit(1)
    print(f"Would prepare {sys.argv[1]}")
