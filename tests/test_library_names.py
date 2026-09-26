import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from import_library import canonical_bundle  # noqa: E402


def test_download_folder_names_map_to_models():
    assert canonical_bundle("ACS480 DRIVES") == "ACS480"
    assert canonical_bundle("ACS580-04 DRIVE MODULES") == "ACS580-04"
    assert canonical_bundle("ACH580-01 - WALL-MOUNTED DRIVE FOR HVAC") == "ACH580-01"
    assert canonical_bundle("PSTX142-600-70") == "PSTX142-600-70"
    assert canonical_bundle("PSTX30-600-70") == "PSTX30-600-70"
    assert canonical_bundle("MS132-10T") == "MS132-10T"
    assert canonical_bundle("README.md") is None
