import pytest

pytest.importorskip("reportlab")
pymupdf = pytest.importorskip("pymupdf")

from docdrift.synthetic_pdf import WATERMARK, render_all  # noqa: E402


def test_every_synthetic_pdf_is_watermarked_and_at_most_two_pages(tmp_path):
    paths = render_all(tmp_path)
    assert len(paths) == 10
    for p in paths:
        doc = pymupdf.open(p)
        assert 1 <= doc.page_count <= 2, p.name
        for page in doc:
            text = page.get_text()
            assert WATERMARK in text and "NOT AN ABB PUBLICATION" in text
