"""shop_guru: automated benchmark generation for SandboxShop environments.

Given one or more storefronts that have been used to build a
SandboxShop via `shop-arena`, this package reads the extracted catalog,
collection, and page data and synthesizes a diverse, grounded set of
web-agent evaluation tasks that match the ShopGuru task schema used by
SimGym.

Public API::

    from shop_guru import Shop, load_shops, load_shop_data, build
    from shop_guru.pipeline import per_shop_out_dir

    shops = load_shops("configs/featured_v1.yml")
    for shop in shops:
        data = load_shop_data(shop)
        out_dir = per_shop_out_dir(shop)
        build(shop, data, out_dirs=[out_dir])

See :mod:`shop_guru.cli` for the command-line entry point.
"""
from shop_guru.config import Shop, load_shops
from shop_guru.emit import emit_pair
from shop_guru.io import load_json, load_shop_data
from shop_guru.pipeline import (
    GeneratorSpec,
    build,
    build_all,
    default_generators,
    per_shop_out_dir,
)

__all__ = [
    "Shop",
    "load_shops",
    "load_shop_data",
    "load_json",
    "emit_pair",
    "GeneratorSpec",
    "build",
    "build_all",
    "default_generators",
    "per_shop_out_dir",
    "__version__",
]

__version__ = "0.1.0"
