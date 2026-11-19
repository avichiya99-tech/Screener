"""Entry point kept for the GitHub Action. The pipeline lives in pipeline/run.py."""
import sys

from pipeline.run import main

if __name__ == "__main__":
    sys.exit(main())
