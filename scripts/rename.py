"""Renombra el proyecto: `uv run python scripts/rename.py "Nuevo Nombre"`.

Solo toca config/brand.yaml (slug, nombre visible) y el slug técnico en pyproject.toml.
"""

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main(name: str) -> None:
    brand = ROOT / "config" / "brand.yaml"
    text = brand.read_text(encoding="utf-8")
    old_slug = re.search(r"^slug:\s*(\S+)", text, re.MULTILINE).group(1)  # type: ignore[union-attr]
    slug = slugify(name)
    text = re.sub(r"^slug:.*$", f"slug: {slug}", text, flags=re.MULTILINE)
    text = re.sub(r"^nombre_visible:.*$", f"nombre_visible: {name}", text, flags=re.MULTILINE)
    brand.write_text(text, encoding="utf-8")
    pp = ROOT / "pyproject.toml"
    pp.write_text(pp.read_text(encoding="utf-8").replace(f'name = "{old_slug}"', f'name = "{slug}"', 1), encoding="utf-8")
    print(f"Renombrado: {old_slug} -> {slug} ({name})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit('uso: rename.py "Nombre"')
    main(sys.argv[1])
