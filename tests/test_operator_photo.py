"""The OCR extension ships as an interface and a flag, nothing more."""
import pytest

from docdrift.config import OcrLimits, Settings
from docdrift.ingest.operator_photo import (DisabledPhotoExtractor, OperatorOcrDisabled,
                                            PhotoValidationError, build_extractor,
                                            combine_with_question, parse_extracted_text,
                                            validate_upload)


def test_ocr_is_disabled_by_default():
    settings = Settings()
    assert settings.flags.enable_operator_ocr is False
    extractor = build_extractor(settings)
    assert isinstance(extractor, DisabledPhotoExtractor)
    with pytest.raises(OperatorOcrDisabled):
        extractor.extract(b"\x89PNG", "image/png")


def test_enabling_the_flag_without_tesseract_still_refuses_safely():
    settings = Settings()
    settings.flags.enable_operator_ocr = True
    extractor = build_extractor(settings)
    with pytest.raises((OperatorOcrDisabled, NotImplementedError)):
        extractor.extract(b"\x89PNG", "image/png")


@pytest.mark.parametrize("data,ctype", [
    (b"x" * 10, "application/pdf"),
    (b"", "image/png"),
    (b"x" * (9 * 1024 * 1024), "image/jpeg"),
])
def test_upload_validation_rejects_bad_input(data, ctype):
    with pytest.raises(PhotoValidationError):
        validate_upload(data, ctype, OcrLimits())


def test_upload_validation_accepts_a_reasonable_photo():
    validate_upload(b"x" * 1024, "image/jpeg", OcrLimits())


def test_field_detection_works_on_already_extracted_text():
    extraction = parse_extracted_text("ABB ACS580-01 drive, panel tag M4, fault 5091 shown")
    assert "ACS580-01" in extraction.detected_models
    assert "M4" in extraction.detected_asset_tags
    assert extraction.detected_fault_codes == ["5091"]


def test_operator_can_correct_the_extraction():
    extraction = parse_extracted_text("ACS580-01 tag M4").apply_edits(asset_tags=["M7"])
    assert extraction.detected_asset_tags == ["M7"]
    assert extraction.edited_by_operator


def test_text_question_is_mandatory_even_with_a_photo():
    extraction = parse_extracted_text("ACS580-01 tag M4")
    with pytest.raises(PhotoValidationError):
        combine_with_question("   ", extraction)
    combined = combine_with_question("Why does it trip?", extraction)
    assert "Why does it trip?" in combined and "M4" in combined


def test_photo_hints_flow_into_equipment_resolution(pipeline):
    extraction = parse_extracted_text("rating plate ACS580-01 asset M4")
    answer, bundle = pipeline.ask("It keeps stopping, what should I check?", photo=extraction)
    assert bundle.equipment.equipment.asset_tag == "M4"
    assert bundle.equipment.source == "text+photo"
