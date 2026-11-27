from app.services.payment_pages import checkout_page, fail_page, format_krw, success_page
from app.services.payment_service import _order_display_name


def test_format_krw_and_order_display_name():
    assert format_krw(19000) == "19,000원"
    single = _order_display_name("3CE", "소프트 매트 립스틱", "Soft Matte", 0)
    multi = _order_display_name("3CE", "소프트 매트 립스틱", "Soft Matte", 2)
    assert single == "3CE 소프트 매트 립스틱"
    assert multi == "3CE 소프트 매트 립스틱 외 2건"
    assert len(_order_display_name("B", "N" * 120, "N", 0)) == 100


def test_checkout_page_escapes_html_in_order_name():
    html = checkout_page(
        client_key="ck",
        order_id="O1",
        order_name="Lip <script>alert(1)</script>",
        amount=1000,
        checkout_token="t" * 32,
    )
    assert "<script>alert(1)</script>" not in html
    assert "Lip &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "\\u003cscript>" in html
    assert "결제하기" in html
    assert success_page()
    assert "status=failed" in fail_page()
