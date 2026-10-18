"""Placeholder for model download logic. Wire your HF/runtime download here."""
import sys

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/download_model.py MODEL_NAME")
        sys.exit(1)
    print(f"Would download {sys.argv[1]} — wire to your download backend.")
