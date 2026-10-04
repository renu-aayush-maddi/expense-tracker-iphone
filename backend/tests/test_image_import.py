"""Receipt IMAGE import: upload validation, server OCR, OpenAI Vision fallback,
OCR/AI disagreement, duplicates, bank mapping, categories and the review queue.

OCR and OpenAI are mocked (fast, deterministic, no network). One test runs the
real OCR engine on a rendered receipt to prove the whole chain works.
"""

import io
import logging
from datetime import date

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.services import phonepe_ocr, phonepe_vision
from app.services.phonepe_ocr import OcrResult
from app.services.phonepe_vision import VisionReceipt
from tests.conftest import make_user, register

URL = "/api/transactions/import/phonepe"
TODAY = date(2026, 10, 3)

# What the server OCR engine returns for the real receipt (₹ comes out as "□").
GOOD_OCR_LINES = [
    "Transaction Successful", "1:11 pm on 03 Oct 2026", "Paid to", "BLINK COMMERCE PRIVA...",
    "blinkit.payu@hdfcbank", "□183", "Transfer Details", "Transaction ID", "T2610031311415776289288",
    "Debited from", "XXXXXX096929", "UTR: 706226593892", "□183",
]


def ocr_result(lines=GOOD_OCR_LINES, score=0.98, error=None):
    return OcrResult(text="\n".join(lines), lines=list(lines), scores=[score] * len(lines), error=error)


def vision_receipt(**overrides):
    values = dict(is_phonepe_receipt=True, direction="paid", merchant_name="BLINK COMMERCE PRIVATE LIMITED",
                  amount="183", transaction_date="2026-10-03", transaction_time="13:11",
                  phonepe_transaction_id="T2610031311415776289288", utr="706226593892", account_last4="6929")
    values.update(overrides)
    return VisionReceipt(**values)


def image_bytes(fmt="JPEG", size=(600, 1200)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format=fmt)
    return buffer.getvalue()


def upload(client, headers, data, filename="receipt.jpg", content_type="image/jpeg"):
    return client.post(URL, files={"file": (filename, data, content_type)}, headers=headers)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.api.imports.today_local", lambda: TODAY)


@pytest.fixture
def fake_ocr(monkeypatch):
    """Replace the OCR engine. Set `.result`; `.calls` counts invocations."""

    class Fake:
        result = ocr_result()
        calls = 0

        def __call__(self, receipt):
            self.calls += 1
            self.last_size = receipt.image.size
            return self.result

    fake = Fake()
    monkeypatch.setattr(phonepe_ocr, "extract_text_from_image", fake)
    return fake


@pytest.fixture
def fake_vision(monkeypatch):
    """Replace the OpenAI call (never hits the network). `.answer` = VisionReceipt, or an Exception to raise."""

    class Fake:
        answer = vision_receipt()
        calls = 0

        def __call__(self, jpeg):
            self.calls += 1
            self.last_jpeg = jpeg
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer

    fake = Fake()
    monkeypatch.setattr(phonepe_vision, "is_enabled", lambda: True)
    monkeypatch.setattr(phonepe_vision, "_call_openai", fake)
    return fake


# ================================================================ upload validation
def test_jpeg_upload_ocr_success(client, auth_headers, fake_ocr, fake_vision):
    response = upload(client, auth_headers, image_bytes("JPEG"))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "created" and body["success"] is True
    assert body["extraction_source"] == "ocr"
    t = body["transaction"]
    assert t["amount"] == "183.00"
    assert t["merchant_name"].startswith("BLINK COMMERCE")
    assert t["transaction_date"] == "2026-10-03"
    assert t["transaction_time"] == "13:11:00"
    assert t["phonepe_transaction_id"] == "T2610031311415776289288"
    assert t["utr"] == "706226593892"
    assert t["account_last4"] == "6929"
    assert t["category"] == "Groceries"  # existing categorizer, not the AI
    assert t["extraction_method"] == "ocr"
    assert fake_vision.calls == 0  # OCR was confident: no OpenAI call


def test_png_upload(client, auth_headers, fake_ocr, fake_vision):
    assert upload(client, auth_headers, image_bytes("PNG"), "receipt.png", "image/png").status_code == 201


def test_heic_upload(client, auth_headers, fake_ocr, fake_vision):
    pillow_heif = pytest.importorskip("pillow_heif")
    buffer = io.BytesIO()
    try:
        pillow_heif.from_pillow(Image.new("RGB", (600, 1200), "white")).save(buffer, format="HEIF")
    except Exception:  # pragma: no cover - encoder not available in this build
        pytest.skip("HEIF encoder not available")
    response = upload(client, auth_headers, buffer.getvalue(), "IMG_0001.HEIC", "image/heic")
    assert response.status_code == 201, response.text
    assert fake_ocr.last_size == (600, 1200)


@pytest.mark.parametrize("data, filename, content_type", [
    (b"%PDF-1.7 not an image", "receipt.pdf", "application/pdf"),
    (b"GIF89a" + b"\x00" * 100, "receipt.gif", "image/gif"),
    (b"just some text pretending to be a jpeg", "receipt.jpg", "image/jpeg"),  # extension lies
    (b"\xff\xd8\xff\xe0" + b"garbage" * 50, "broken.jpg", "image/jpeg"),  # JPEG header, corrupt body
])
def test_rejects_unsupported_or_corrupt_files(client, auth_headers, fake_ocr, data, filename, content_type):
    response = upload(client, auth_headers, data, filename, content_type)
    assert response.status_code == 400
    assert fake_ocr.calls == 0


def test_rejects_oversized_file(client, auth_headers, fake_ocr, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)
    big = b"\xff\xd8\xff" + b"0" * (1024 * 1024 + 10)
    response = upload(client, auth_headers, big)
    assert response.status_code == 413
    assert fake_ocr.calls == 0


def test_missing_file(client, auth_headers, fake_ocr):
    response = client.post(URL, data={"note": "no file"}, files={"other": ("x.txt", b"x", "text/plain")},
                           headers=auth_headers)
    assert response.status_code == 400
    assert "file" in response.json()["detail"]


def test_wrong_content_type(client, auth_headers):
    response = client.post(URL, content=b"raw bytes", headers={**auth_headers, "Content-Type": "image/jpeg"})
    assert response.status_code == 415


def test_requires_valid_import_token(client, fake_ocr):
    assert upload(client, {}, image_bytes()).status_code == 401
    assert upload(client, {"Authorization": "Bearer etk_not-a-real-token"}, image_bytes()).status_code == 401
    assert fake_ocr.calls == 0


def test_works_with_personal_import_token(client, auth_headers, fake_ocr, fake_vision):
    token = client.post("/api/settings/tokens", json={"name": "iPhone"}, headers=auth_headers).json()["token"]
    response = upload(client, {"Authorization": f"Bearer {token}"}, image_bytes())
    assert response.status_code == 201
    assert response.json()["extraction_source"] == "ocr"


def test_legacy_json_text_import_still_works(client, auth_headers):
    from tests.conftest import SAMPLE_OCR

    response = client.post(URL, json={"ocr_text": SAMPLE_OCR}, headers=auth_headers)
    assert response.status_code == 201
    assert response.json()["extraction_source"] == "text"


# ================================================================ OCR -> vision fallback
def test_ocr_failure_uses_vision(client, auth_headers, fake_ocr, fake_vision):
    fake_ocr.result = OcrResult(error="RuntimeError")
    response = upload(client, auth_headers, image_bytes())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["extraction_source"] == "openai_fallback"
    assert body["transaction"]["extraction_method"] == "openai_fallback"
    assert body["transaction"]["merchant_name"] == "BLINK COMMERCE PRIVATE LIMITED"
    assert body["transaction"]["category"] == "Groceries"
    assert fake_vision.calls == 1
    assert fake_vision.last_jpeg[:3] == b"\xff\xd8\xff"  # the model gets the image, not OCR text


def test_incomplete_ocr_uses_vision_and_fills_gaps(client, auth_headers, fake_ocr, fake_vision):
    # OCR lost the amount and the UTR: parser can't validate -> vision fallback.
    lines = [l for l in GOOD_OCR_LINES if "□" not in l and "UTR" not in l]
    fake_ocr.result = ocr_result(lines)
    fake_vision.answer = vision_receipt(account_last4=None)  # AI missed the account; OCR had it
    body = upload(client, auth_headers, image_bytes()).json()
    assert body["status"] == "created" and body["extraction_source"] == "openai_fallback"
    t = body["transaction"]
    assert t["amount"] == "183.00" and t["utr"] == "706226593892"
    assert t["account_last4"] == "6929"  # filled in from OCR


def test_low_ocr_confidence_uses_vision(client, auth_headers, fake_ocr, fake_vision):
    fake_ocr.result = ocr_result(score=0.55)  # every field parsed, but the engine wasn't sure
    body = upload(client, auth_headers, image_bytes()).json()
    assert body["extraction_source"] == "openai_fallback" and fake_vision.calls == 1


def test_rupee_read_as_2_resolved_by_vision(client, auth_headers, fake_ocr, fake_vision):
    lines = [l.replace("□183", "21,420.25") for l in GOOD_OCR_LINES]
    fake_ocr.result = ocr_result(lines)
    fake_vision.answer = vision_receipt(amount="1,420.25")
    body = upload(client, auth_headers, image_bytes()).json()
    assert body["status"] == "created"
    assert body["transaction"]["amount"] == "1420.25"


def test_vision_failure_goes_to_review_with_image(client, auth_headers, fake_ocr, fake_vision):
    fake_ocr.result = ocr_result([l for l in GOOD_OCR_LINES if "□" not in l])  # no amount
    fake_vision.answer = TimeoutError()
    response = upload(client, auth_headers, image_bytes())
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "review_required" and body["success"] is False
    assert any("AI fallback failed" in issue for issue in body["issues"])
    review_id = body["review_id"]

    pending = client.get(f"/api/imports/pending/{review_id}", headers=auth_headers).json()
    assert pending["has_image"] is True
    assert pending["parsed_data"]["category"] == "Groceries"  # review form pre-filled by the existing categorizer
    assert pending["parsed_data"]["phonepe_transaction_id"] == "T2610031311415776289288"
    image = client.get(f"/api/imports/pending/{review_id}/image", headers=auth_headers)
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert "no-store" in image.headers["cache-control"]
    other = make_user(client, "other@example.com")
    assert client.get(f"/api/imports/pending/{review_id}/image", headers=other).status_code == 404
    assert client.get(f"/api/imports/pending/{review_id}/image").status_code == 401


def test_vision_disabled_and_ocr_uncertain_goes_to_review(client, auth_headers, fake_ocr, monkeypatch):
    monkeypatch.setattr(phonepe_vision, "is_enabled", lambda: False)
    fake_ocr.result = ocr_result([l for l in GOOD_OCR_LINES if "□" not in l])
    body = upload(client, auth_headers, image_bytes()).json()
    assert body["status"] == "review_required"
    assert any("unavailable" in issue for issue in body["issues"])


def test_invalid_vision_values_are_rejected(client, auth_headers, fake_ocr, fake_vision):
    fake_ocr.result = OcrResult(error="RuntimeError")
    fake_vision.answer = vision_receipt(amount="lots", phonepe_transaction_id="ABC123", utr="XXXX1234")
    body = upload(client, auth_headers, image_bytes()).json()
    assert body["status"] == "review_required"  # the backend, not the model, decides what's valid
    issues = " ".join(body["issues"])
    assert "Amount could not be found" in issues and "No PhonePe transaction ID or UTR" in issues


def test_vision_money_received_goes_to_review(client, auth_headers, fake_ocr, fake_vision):
    fake_ocr.result = OcrResult(error="RuntimeError")
    fake_vision.answer = vision_receipt(direction="received")
    assert upload(client, auth_headers, image_bytes()).json()["status"] == "review_required"


def test_not_a_receipt_is_invalid(client, auth_headers, fake_ocr, fake_vision):
    fake_ocr.result = ocr_result(["Holiday photo", "Beach"], score=0.9)
    fake_vision.answer = vision_receipt(is_phonepe_receipt=False, direction="unknown", merchant_name=None, amount=None,
                                        transaction_date=None, transaction_time=None, phonepe_transaction_id=None,
                                        utr=None, account_last4=None)
    response = upload(client, auth_headers, image_bytes())
    assert response.status_code == 422 and response.json()["status"] == "invalid"


# ================================================================ disagreement
def test_ocr_and_vision_disagree_on_amount(client, auth_headers, fake_ocr, fake_vision):
    fake_ocr.result = ocr_result(score=0.6)  # parsed fine but low confidence -> vision runs
    fake_vision.answer = vision_receipt(amount="188")
    response = upload(client, auth_headers, image_bytes())
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "review_required"
    assert any("amount: OCR 183.00 vs AI 188.00" in issue for issue in body["issues"])
    pending = client.get(f"/api/imports/pending/{body['review_id']}", headers=auth_headers).json()
    assert pending["parsed_data"]["conflicts"] and pending["parsed_data"]["ocr_values"]["amount"] == "183.00"
    assert client.get("/api/transactions", headers=auth_headers).json()["total"] == 0  # nothing saved


def test_ocr_and_vision_disagree_on_transaction_id(client, auth_headers, fake_ocr, fake_vision):
    fake_ocr.result = ocr_result(score=0.6)
    fake_vision.answer = vision_receipt(phonepe_transaction_id="T2610031311415776289289")
    body = upload(client, auth_headers, image_bytes()).json()
    assert body["status"] == "review_required"
    assert any("transaction ID" in issue for issue in body["issues"])


def test_truncated_merchant_is_not_a_disagreement(client, auth_headers, fake_ocr, fake_vision):
    fake_ocr.result = ocr_result(score=0.6)
    fake_vision.answer = vision_receipt(merchant_name="Blink Commerce Private Limited")
    assert upload(client, auth_headers, image_bytes()).json()["status"] == "created"


# ================================================================ duplicates, mapping, review workflow
def test_same_receipt_twice_is_duplicate(client, auth_headers, fake_ocr, fake_vision):
    first = upload(client, auth_headers, image_bytes()).json()
    second = upload(client, auth_headers, image_bytes()).json()
    assert second["status"] == "duplicate" and second["success"] is True
    assert second["existing_transaction_id"] == first["transaction"]["id"]
    assert client.get("/api/transactions", headers=auth_headers).json()["total"] == 1


def test_duplicate_by_utr_only(client, auth_headers, fake_ocr, fake_vision):
    upload(client, auth_headers, image_bytes())
    fake_ocr.result = ocr_result([l for l in GOOD_OCR_LINES if not l.startswith("T26")])  # ID unreadable this time
    body = upload(client, auth_headers, image_bytes("PNG"), "r.png", "image/png").json()
    assert body["status"] == "duplicate"
    assert fake_vision.calls == 0  # recognised before any AI call


def test_vision_path_cannot_bypass_duplicate_detection(client, auth_headers, fake_ocr, fake_vision):
    upload(client, auth_headers, image_bytes())  # saved via OCR
    fake_ocr.result = OcrResult(error="RuntimeError")  # next time OCR fails, vision reads the same receipt
    body = upload(client, auth_headers, image_bytes("PNG"), "r.png", "image/png").json()
    assert body["status"] == "duplicate"


def test_duplicate_text_and_image_import(client, auth_headers, fake_ocr, fake_vision):
    from tests.conftest import SAMPLE_OCR

    client.post(URL, json={"ocr_text": SAMPLE_OCR}, headers=auth_headers)  # legacy import of the same receipt
    assert upload(client, auth_headers, image_bytes()).json()["status"] == "duplicate"


def test_account_mapping_sets_bank(client, auth_headers, fake_ocr, fake_vision):
    client.post("/api/settings/accounts", json={"account_last4": "6929", "bank_name": "Kotak Mahindra Bank"},
                headers=auth_headers)
    body = upload(client, auth_headers, image_bytes()).json()
    assert body["transaction"]["bank"] == "Kotak Mahindra Bank"


def test_review_then_confirm_uses_existing_workflow(client, auth_headers, fake_ocr, fake_vision):
    fake_ocr.result = ocr_result(score=0.6)
    fake_vision.answer = vision_receipt(amount="188")
    review_id = upload(client, auth_headers, image_bytes()).json()["review_id"]
    payload = {"amount": "183", "merchant_name": "Blinkit", "category": "Groceries", "transaction_date": "2026-10-03",
               "phonepe_transaction_id": "T2610031311415776289288", "utr": "706226593892", "account_last4": "6929"}
    saved = client.post(f"/api/imports/pending/{review_id}/confirm", json=payload, headers=auth_headers)
    assert saved.status_code == 201 and saved.json()["extraction_method"] == "reviewed"
    assert client.get("/api/imports/pending", headers=auth_headers).json() == []
    # Sharing the image again is now a duplicate.
    assert upload(client, auth_headers, image_bytes()).json()["status"] == "duplicate"


def test_resharing_uncertain_image_reuses_review(client, auth_headers, fake_ocr, fake_vision):
    fake_vision.answer = TimeoutError()
    fake_ocr.result = ocr_result([l for l in GOOD_OCR_LINES if "□" not in l])
    a = upload(client, auth_headers, image_bytes()).json()
    b = upload(client, auth_headers, image_bytes()).json()
    assert a["review_id"] == b["review_id"]
    assert len(client.get("/api/imports/pending", headers=auth_headers).json()) == 1


def test_retry_all_reprocesses_stored_image(client, auth_headers, fake_ocr, fake_vision):
    fake_vision.answer = TimeoutError()
    fake_ocr.result = ocr_result([l for l in GOOD_OCR_LINES if "□" not in l])
    upload(client, auth_headers, image_bytes())
    fake_vision.answer = vision_receipt()  # e.g. the OpenAI key was fixed
    counts = client.post("/api/imports/pending/reprocess", headers=auth_headers).json()
    assert counts["created"] == 1
    assert client.get("/api/imports/pending", headers=auth_headers).json() == []


def test_logs_do_not_contain_receipt_contents(client, auth_headers, fake_ocr, fake_vision, caplog):
    fake_ocr.result = ocr_result(score=0.6)
    with caplog.at_level(logging.INFO):
        upload(client, auth_headers, image_bytes())
    text = caplog.text
    assert "706226593892" not in text and "T2610031311415776289288" not in text
    assert "BLINK" not in text and "096929" not in text


# ================================================================ real OCR engine (integration)
def _render_receipt() -> bytes:
    try:
        font = lambda size: ImageFont.load_default(size=size)  # noqa: E731 - bundled scalable font
        font(20)
    except Exception:  # pragma: no cover
        pytest.skip("No scalable font available")
    img = Image.new("RGB", (1170, 1900), "white")
    draw = ImageDraw.Draw(img)
    y = 60
    for text, size in [("Transaction Successful", 56), ("1:11 pm on 03 Oct 2026", 38), ("Paid to", 40),
                       ("BLINK COMMERCE PRIVA...", 48), ("blinkit.payu@hdfcbank", 36), ("Transfer Details", 44),
                       ("Transaction ID", 38), ("T2610031311415776289288", 44), ("Debited from", 38),
                       ("XXXXXX096929", 44), ("UTR: 706226593892", 40)]:
        draw.text((80, y), text, font=font(size), fill="#111111")
        y += size + 70
    draw.text((800, 520), "Rs 183", font=font(56), fill="#111111")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def test_real_ocr_engine_end_to_end(client, monkeypatch):
    pytest.importorskip("rapidocr")
    monkeypatch.setattr(phonepe_vision, "is_enabled", lambda: False)  # prove OCR alone does it
    headers = register(client)
    response = upload(client, headers, _render_receipt(), "receipt.png", "image/png")
    assert response.status_code == 201, response.text
    t = response.json()["transaction"]
    assert response.json()["extraction_source"] == "ocr"
    assert t["amount"] == "183.00"
    assert t["merchant_name"].startswith("BLINK COMMERCE")
    assert t["transaction_date"] == "2026-10-03" and t["transaction_time"] == "13:11:00"
    assert t["phonepe_transaction_id"] == "T2610031311415776289288"
    assert t["utr"] == "706226593892" and t["account_last4"] == "6929"
    assert t["category"] == "Groceries"


# ================================================================ OCR service & image validation units
def test_ocr_service_downscales_and_reports_quality(monkeypatch):
    from app.services.receipt_image import load_receipt_image

    seen = {}

    def fake_engine(image):
        seen["size"] = image.size
        return ["T2610031311415776289288", "Paid to"], [0.9, 0.7]

    monkeypatch.setattr(phonepe_ocr, "is_available", lambda: True)
    monkeypatch.setattr(phonepe_ocr, "_run_engine", fake_engine)
    monkeypatch.setattr(settings, "OCR_MAX_IMAGE_SIDE", 1000)
    result = phonepe_ocr.extract_text_from_image(load_receipt_image(image_bytes(size=(1179, 2556))))
    assert max(seen["size"]) == 1000  # downscaled to keep memory low
    assert result.ok and result.mean_confidence == 0.8 and result.min_digit_line_confidence == 0.9
    assert "text" not in result.summary()  # summaries (used in logs) never include receipt text


def test_ocr_service_never_raises(monkeypatch):
    from app.services.receipt_image import load_receipt_image

    def broken(image):
        raise MemoryError()

    monkeypatch.setattr(phonepe_ocr, "is_available", lambda: True)
    monkeypatch.setattr(phonepe_ocr, "_run_engine", broken)
    result = phonepe_ocr.extract_text_from_image(load_receipt_image(image_bytes()))
    assert result.error == "MemoryError" and not result.ok


def test_sniff_formats():
    from app.services.receipt_image import sniff_format

    assert sniff_format(image_bytes("JPEG")) == "jpeg"
    assert sniff_format(image_bytes("PNG")) == "png"
    assert sniff_format(b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic") == "heif"
    assert sniff_format(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42") is None  # a video, not HEIF
    assert sniff_format(b"hello") is None


def test_vision_output_cleaning():
    assert phonepe_vision.clean_amount("₹1,250.50") == __import__("decimal").Decimal("1250.50")
    assert phonepe_vision.clean_amount("0") is None and phonepe_vision.clean_amount("12345678901") is None
    assert phonepe_vision.clean_transaction_id("t 2610031311415776289288") == "T2610031311415776289288"
    assert phonepe_vision.clean_transaction_id("2610031311415776289288") is None
    assert phonepe_vision.clean_utr("7062 2659 3892") == "706226593892"
    assert phonepe_vision.clean_utr("XXXXXX096929") is None
    assert phonepe_vision.clean_last4("XXXXXX096929") == "6929"
    assert phonepe_vision.clean_merchant("BigBasket bigbasket@payuaxis") == "BigBasket"
    assert phonepe_vision.clean_time("1:11 PM") is None and phonepe_vision.clean_time("13:11").hour == 13
