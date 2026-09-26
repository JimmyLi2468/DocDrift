"""Put equipment documentation bundles into data/library/.

    PYTHONPATH=. python scripts/unpack_library.py ~/Downloads/PSTX30-600-70.zip ...
    PYTHONPATH=. python scripts/unpack_library.py "../ACS480 DRIVES" ../MS132-10T ...

Accepts zip files (with or without a .zip extension) and already-unzipped folders.
Each becomes data/library/<model>/, where <model> is the type code the bundle's name
starts with (e.g. "ACS480 DRIVES" -> ACS480). Files are copied; the originals are
left untouched.
macOS metadata (__MACOSX/, ._*, .DS_Store) is dropped. Every other file is kept,
including the ones DocDrift does not index (EPLAN .edz/.xml macros, drawings).
Then run scripts/import_library.py and scripts/ingest_abb.py.
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import zipfile

from docdrift.abb_registry import LIBRARY_DIR

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from import_library import canonical_bundle  # noqa: E402

SKIP = ("__MACOSX", ".DS_Store")


def _skip(rel: pathlib.Path) -> bool:
    return any(p in SKIP or p.startswith("._") for p in rel.parts)


def copy_folder(src: pathlib.Path) -> tuple[str, int]:
    bundle = canonical_bundle(src.name)
    if bundle is None:
        raise SystemExit(f"{src.name!r} does not start with one of the eight type codes")
    n = 0
    for f in src.rglob("*"):
        rel = f.relative_to(src)
        if f.is_file() and not _skip(rel):
            dst = LIBRARY_DIR / bundle / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            n += 1
    return bundle, n


def unpack(zip_path: pathlib.Path) -> tuple[str, int]:
    z = zipfile.ZipFile(zip_path)
    members = [i for i in z.infolist() if not i.is_dir()
               and not i.filename.startswith("__MACOSX")
               and not pathlib.Path(i.filename).name.startswith("._")
               and not i.filename.endswith(".DS_Store")]
    tops = {pathlib.Path(i.filename).parts[0] for i in members}
    top = tops.pop() if len(tops) == 1 else zip_path.stem
    bundle = canonical_bundle(top) or canonical_bundle(zip_path.name)
    if bundle is None:
        raise SystemExit(f"{zip_path.name!r} does not start with one of the eight type codes")
    strip = 1 if len({pathlib.Path(i.filename).parts[0] for i in members}) == 1 else 0
    for info in members:
        rel = pathlib.Path(*pathlib.Path(info.filename).parts[strip:])
        dst = LIBRARY_DIR / bundle / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as src, open(dst, "wb") as fh:
            shutil.copyfileobj(src, fh, 1 << 20)
    return bundle, len(members)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for arg in argv:
        src = pathlib.Path(arg).expanduser()
        bundle, n = copy_folder(src) if src.is_dir() else unpack(src)
        print(f"  {bundle:24s} {n:3d} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
