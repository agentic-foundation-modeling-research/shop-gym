"""Single source of truth for the ``shop_explore`` package version.

Kept in a leaf module so submodules can import it without triggering the
``shop_explore.__init__`` re-export chain (which itself imports from those
submodules).
"""

from __future__ import annotations

__version__ = "0.1.0"
