"""Toss checkout HTML shells shown in the in-app browser."""

# ruff: noqa: E501
from __future__ import annotations

import html
import json


def format_krw(amount: int) -> str:
    return f"{amount:,}원"


def checkout_page(
    *, client_key: str, order_id: str, order_name: str, amount: int, checkout_token: str
) -> str:
    # Escape `<` so order names cannot break out of the surrounding <script> tag.
    data = json.dumps(
        {
            "clientKey": client_key,
            "order_id": order_id,
            "order_name": order_name,
            "amount": amount,
            "checkout_token": checkout_token,
        },
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    title = html.escape(order_name)
    total = html.escape(format_krw(amount))
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
  <title>VISHUE 결제</title>
  <style>
    :root {{
      --rose:#782C4C; --rose-dark:#5D213B; --ink:#33242D; --muted:#5C5058;
      --faint:#95828E; --surface:#FFFAF9; --card:#fff; --border:#E8DFE2;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; min-height:100vh; background:var(--surface); color:var(--ink);
      font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;
    }}
    .wrap {{ max-width:480px; margin:0 auto; padding:20px 16px 40px; }}
    .brand {{ font-size:13px; font-weight:700; letter-spacing:.08em; color:var(--rose); margin-bottom:16px; }}
    .card {{
      background:var(--card); border:1px solid var(--border); border-radius:16px;
      padding:18px 16px; margin-bottom:16px;
    }}
    .label {{ font-size:12px; color:var(--faint); margin-bottom:6px; }}
    .order-name {{ font-size:16px; font-weight:700; line-height:1.35; margin:0 0 12px; }}
    .amount {{ font-size:28px; font-weight:800; margin:0; letter-spacing:-.02em; }}
    .hint {{ font-size:12px; color:var(--muted); margin:10px 0 0; line-height:1.4; }}
    #payment-method, #agreement {{ margin-bottom:12px; }}
    #pay {{
      display:none; width:100%; border:0; border-radius:14px; padding:16px;
      background:var(--rose); color:#fff; font-size:16px; font-weight:700;
    }}
    #pay:active {{ background:var(--rose-dark); }}
    #pay[disabled] {{ opacity:.55; }}
    .state {{
      display:flex; flex-direction:column; align-items:center; justify-content:center;
      gap:10px; min-height:160px; color:var(--muted); font-size:14px; text-align:center;
    }}
    .spinner {{
      width:28px; height:28px; border:3px solid var(--border); border-top-color:var(--rose);
      border-radius:50%; animation:spin .8s linear infinite;
    }}
    .error {{ color:#B42318; }}
    @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="brand">VISHUE</div>
    <div class="card">
      <div class="label">주문 상품</div>
      <p class="order-name">{title}</p>
      <div class="label">결제 금액</div>
      <p class="amount">{total}</p>
      <p class="hint">아래에서 결제 수단을 선택한 뒤 결제를 완료해 주세요.</p>
    </div>
    <div id="boot" class="state"><div class="spinner" aria-hidden="true"></div><div>결제 수단을 준비하고 있어요…</div></div>
    <div id="payment-method" hidden></div>
    <div id="agreement" hidden></div>
    <button id="pay" type="button">결제하기</button>
  </div>
  <script src="https://js.tosspayments.com/v2/standard"></script>
  <script>
    const d = {data};
    const boot = document.getElementById('boot');
    const pay = document.getElementById('pay');
    const methods = document.getElementById('payment-method');
    const agreement = document.getElementById('agreement');
    function showError(message) {{
      boot.classList.add('error');
      boot.innerHTML = '<div>' + message + '</div>';
      boot.hidden = false;
      methods.hidden = true;
      agreement.hidden = true;
      pay.style.display = 'none';
    }}
    (async () => {{
      try {{
        const toss = TossPayments(d.clientKey);
        const widgets = toss.widgets({{ customerKey: 'ANONYMOUS' }});
        await widgets.setAmount({{ currency: 'KRW', value: d.amount }});
        await Promise.all([
          widgets.renderPaymentMethods({{ selector: '#payment-method', variantKey: 'DEFAULT' }}),
          widgets.renderAgreement({{ selector: '#agreement', variantKey: 'AGREEMENT' }}),
        ]);
        boot.hidden = true;
        methods.hidden = false;
        agreement.hidden = false;
        pay.style.display = 'block';
        pay.onclick = async () => {{
          pay.disabled = true;
          try {{
            await widgets.requestPayment({{
              orderId: d.order_id,
              orderName: d.order_name,
              successUrl: location.origin + '/pay/success?token=' + encodeURIComponent(d.checkout_token),
              failUrl: location.origin + '/pay/fail',
            }});
          }} catch (e) {{
            pay.disabled = false;
            if (e && e.code === 'USER_CANCEL') return;
            showError('결제를 시작하지 못했어요. 잠시 후 다시 시도해 주세요.');
          }}
        }};
      }} catch (e) {{
        showError('결제 화면을 불러오지 못했어요. 창을 닫고 앱에서 다시 열어 주세요.');
      }}
    }})();
  </script>
</body>
</html>"""


def success_page() -> str:
    return """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>결제 확인</title>
  <style>
    body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
      background:#FFFAF9;color:#33242D;font-family:-apple-system,BlinkMacSystemFont,"Noto Sans KR",sans-serif;}
    .box{text-align:center;padding:24px;}
    .spinner{width:28px;height:28px;margin:0 auto 14px;border:3px solid #E8DFE2;border-top-color:#782C4C;
      border-radius:50%;animation:spin .8s linear infinite;}
    p{margin:0;font-size:15px;line-height:1.45;color:#5C5058;}
    @keyframes spin{to{transform:rotate(360deg);}}
  </style>
</head>
<body>
  <div class="box">
    <div class="spinner" aria-hidden="true"></div>
    <p>결제를 확인하고 있어요…<br/>잠시만 기다려 주세요.</p>
  </div>
  <script>(async()=>{try{const q=new URLSearchParams(location.search);const r=await fetch('/api/payments/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({orderId:q.get('orderId'),paymentKey:q.get('paymentKey'),amount:Number(q.get('amount')),checkoutToken:q.get('token')})});const d=await r.json();location.href=r.ok?d.returnUrl+'?orderId='+encodeURIComponent(d.orderId):'kbeautyar://payment-result?status=unknown'}catch{location.href='kbeautyar://payment-result?status=unknown'}})()</script>
</body>
</html>"""


def fail_page() -> str:
    return """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>결제 실패</title>
  <style>
    body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
      background:#FFFAF9;color:#33242D;font-family:-apple-system,BlinkMacSystemFont,"Noto Sans KR",sans-serif;}
    .box{text-align:center;padding:24px;max-width:320px;}
    h1{margin:0 0 8px;font-size:18px;}
    p{margin:0;font-size:14px;line-height:1.45;color:#5C5058;}
  </style>
</head>
<body>
  <div class="box">
    <h1>결제가 완료되지 않았어요</h1>
    <p>앱으로 돌아가 상태를 확인한 뒤 다시 시도해 주세요.</p>
  </div>
  <script>setTimeout(()=>{location.href='kbeautyar://payment-result?status=failed'},600)</script>
</body>
</html>"""
