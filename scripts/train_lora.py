"""Placeholder for LoRA training. Wire to your training stack."""
import sys

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/train_lora.py CONFIG_PATH")
        sys.exit(1)
    print(f"Would train LoRA from {sys.argv[1]}")
