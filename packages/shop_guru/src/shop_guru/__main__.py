"""Allow ``python -m shop_guru ...`` as an alternative to ``shop_guru-build``."""
from __future__ import annotations

import sys

from shop_guru.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
