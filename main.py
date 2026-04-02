import sys
import os

# Add src to path so we can import imgtowebp without installing
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from imgtowebp.cli import run_cli
from imgtowebp.web.app import run_web

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "web":
        # Remove 'web' from argv so argparse in run_web doesn't get confused
        sys.argv.pop(1)
        run_web()
    else:
        run_cli()

if __name__ == "__main__":
    main()
