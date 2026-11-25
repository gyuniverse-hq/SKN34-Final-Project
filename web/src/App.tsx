import { useEffect, useMemo, useState } from "react";
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router";
import { useQuery } from "@tanstack/react-query";
import {
  ApiError,
  api,
  appStoreUrl,
  arAppUrl,
  supabase,
  type CartLine,
  type Product,
} from "./api";
import { isStaffSession, signOut, STAFF_HOME } from "./auth";
import { cartTotal, loadCart, saveCart } from "./cart";
import { LoginPage } from "./Login";
import { SignupPage } from "./Signup";
import { StaffApp } from "./StaffApp";

function money(n: number) {
  return `${n.toLocaleString("ko-KR")}원`;
}

function Shell({
  cartCount,
  email,
  children,
}: {
  cartCount: number;
  email: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="shell">
      <header className="site-header">
        <div className="site-header-inner">
          <Link to="/" className="brand" aria-label="VISHUE 홈">
            VISHUE<span className="brand-dot">.</span>
          </Link>
          <nav className="site-nav" aria-label="주요 메뉴">
            <NavLink to="/" end>
              쇼핑
            </NavLink>
            <NavLink to="/cart">
              장바구니
              {cartCount > 0 ? <span className="nav-count">{cartCount}</span> : null}
            </NavLink>
            <a href={arAppUrl} target="_blank" rel="noreferrer" className="nav-ar">
              앱 AR
            </a>
          </nav>
          <div className="site-account">
            {email ? <span className="account-email">{email}</span> : null}
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void signOut()}>
              로그아웃
            </button>
          </div>
        </div>
      </header>
      <main className="main">{children}</main>
      <footer className="site-footer">
        <div className="site-footer-inner">
          <p className="footer-brand">
            VISHUE<span className="brand-dot">.</span>
          </p>
          <p>가상 메이크업은 앱에서, 쇼핑은 웹에서.</p>
        </div>
      </footer>
    </div>
  );
}

function ArCta({ compact = false }: { compact?: boolean }) {
  return (
    <aside className={`ar-strip${compact ? " is-compact" : ""}`}>
      <div className="ar-strip-copy">
        <strong>앱에서 AR 가상 메이크업</strong>
        {!compact && (
          <p>고른 립을 입술에 직접 바른 것처럼 보려면 VISHUE 앱 AR을 열어 주세요.</p>
        )}
      </div>
      <div className="ar-strip-actions">
        <a href={arAppUrl} target="_blank" rel="noreferrer" className="btn btn-sm">
          앱에서 AR 열기
        </a>
        {appStoreUrl ? (
          <a href={appStoreUrl} target="_blank" rel="noreferrer" className="btn btn-ghost btn-sm">
            스토어
          </a>
        ) : null}
      </div>
    </aside>
  );
}

function Home() {
  const q = useQuery({
    queryKey: ["products"],
    queryFn: () => api<{ products: Product[] }>("/api/products?category=lip"),
  });
  const products = q.data?.products ?? [];

  return (
    <>
      <section className="shop-hero">
        <div className="shop-hero-copy">
          <p className="eyebrow">LIP COLLECTION</p>
          <h1>나에게 맞는 립을 고르세요</h1>
          <p className="shop-hero-lead">
            VISHUE 웹에서 제품을 담고, AR 피팅은 앱에서 이어갑니다.
          </p>
        </div>
        <ArCta />
      </section>

      {q.isPending && <p className="state">불러오는 중…</p>}
      {q.error && (
        <p className="form-error">
          {q.error instanceof Error ? q.error.message : "목록을 불러오지 못했습니다."}
        </p>
      )}
      {q.data && (
        <section className="catalog">
          <div className="catalog-head">
            <h2>립 제품</h2>
            {products.length > 0 && <span>{products.length}개</span>}
          </div>
          <div className="product-grid">
            {products.map((p) => (
              <Link
                key={p.id}
                to={`/products/${encodeURIComponent(p.id)}`}
                className="product-card"
              >
                <div className="product-thumb">
                  <img src={p.imageUrl || undefined} alt="" loading="lazy" />
                </div>
                <div className="product-body">
                  <span className="product-brand">{p.brand}</span>
                  <span className="product-name">{p.name}</span>
                  <span className="product-price">{money(p.priceKRW)}</span>
                  {!!p.shades?.length && p.shades.length > 1 && (
                    <span className="shade-row">
                      {p.shades.slice(0, 5).map((s) => (
                        <span
                          key={s.id}
                          className="shade-dot"
                          style={{ background: s.hex }}
                          title={s.name}
                        />
                      ))}
                      <span className="shade-count">{p.shades.length}색</span>
                    </span>
                  )}
                </div>
              </Link>
            ))}
          </div>
          {!products.length && <p className="empty">표시할 상품이 없습니다.</p>}
        </section>
      )}
    </>
  );
}

function ProductDetail({ onAdd }: { onAdd: (line: CartLine) => void }) {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["product", id],
    queryFn: () => api<{ product: Product }>(`/api/products/${encodeURIComponent(id)}`),
    enabled: !!id,
  });
  const product = q.data?.product;
  const shades = product?.shades || [];
  const [shadeId, setShadeId] = useState("");
  const [added, setAdded] = useState(false);
  useEffect(() => {
    if (shades[0] && !shadeId) setShadeId(shades[0].id);
  }, [shades, shadeId]);
  const shade = shades.find((s) => s.id === shadeId) || shades[0];

  return (
    <>
      <button type="button" className="back-link" onClick={() => navigate(-1)}>
        ← 쇼핑으로
      </button>
      {q.isPending && <p className="state">불러오는 중…</p>}
      {q.error && (
        <p className="form-error">
          {q.error instanceof Error ? q.error.message : "상품을 불러오지 못했습니다."}
        </p>
      )}
      {product && (
        <article className="pdp">
          <div className="pdp-media">
            <img src={product.imageUrl || undefined} alt={product.name} />
          </div>
          <div className="pdp-info">
            <p className="product-brand">{product.brand}</p>
            <h1>{product.name}</h1>
            <p className="pdp-price">{money(product.priceKRW)}</p>
            {!!shades.length && (
              <div className="pdp-shades">
                <p className="pdp-shade-label">
                  쉐이드 <strong>{shade?.name}</strong>
                </p>
                <div className="shades">
                  {shades.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className={`shade${s.id === shadeId ? " is-on" : ""}`}
                      style={{ background: s.hex }}
                      title={s.name}
                      aria-label={s.name}
                      aria-pressed={s.id === shadeId}
                      onClick={() => setShadeId(s.id)}
                    />
                  ))}
                </div>
              </div>
            )}
            <div className="pdp-actions">
              <button
                type="button"
                className="btn"
                disabled={!shade}
                onClick={() => {
                  if (!shade) return;
                  onAdd({
                    productId: product.id,
                    productName: product.name,
                    brand: product.brand,
                    shadeId: shade.id,
                    shadeName: shade.name,
                    unitPriceKRW: product.priceKRW,
                    quantity: 1,
                  });
                  setAdded(true);
                }}
              >
                {added ? "담았어요 · 하나 더" : "장바구니 담기"}
              </button>
              <Link to="/cart" className="btn btn-ghost">
                장바구니
              </Link>
            </div>
            <ArCta compact />
          </div>
        </article>
      )}
    </>
  );
}

function CartPage({
  lines,
  setLines,
}: {
  lines: CartLine[];
  setLines: (lines: CartLine[]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  const total = useMemo(() => cartTotal(lines), [lines]);

  async function checkout() {
    if (!lines.length) return;
    if (!supabase) {
      setError("로그인을 위해 Supabase 공개 설정을 web/.env에 넣어 주세요.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = (await supabase.auth.getSession()).data.session;
      if (!session) {
        setError("결제는 로그인이 필요합니다. 앱과 같은 계정으로 로그인해 주세요.");
        return;
      }
      const body = {
        lines: lines.map((l) => ({
          productId: l.productId,
          shadeId: l.shadeId,
          quantity: l.quantity,
        })),
      };
      const created = await api<{
        orderId: string;
        amount: number;
        checkoutUrl: string;
      }>("/api/payments/orders", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setOrderId(created.orderId);
      setLines([]);
      if (created.checkoutUrl) {
        window.location.assign(created.checkoutUrl);
        return;
      }
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : "주문 생성에 실패했습니다.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="page-title">
        <h1>장바구니</h1>
        <p>{lines.length ? `${lines.length}개 상품` : "담은 상품이 없습니다."}</p>
      </section>

      {!lines.length && !orderId && (
        <div className="empty-box">
          <p>아직 담은 제품이 없어요.</p>
          <Link to="/" className="btn">
            쇼핑 계속하기
          </Link>
        </div>
      )}

      <div className="cart-layout">
        {!!lines.length && (
          <ul className="cart-list">
            {lines.map((l) => (
              <li key={`${l.productId}:${l.shadeId}`} className="cart-item">
                <div className="cart-item-copy">
                  <span className="product-brand">{l.brand}</span>
                  <strong className="cart-item-name">{l.productName}</strong>
                  <span className="cart-item-meta">
                    {l.shadeName} · {l.quantity}개
                  </span>
                </div>
                <div className="cart-item-side">
                  <span className="product-price">{money(l.unitPriceKRW * l.quantity)}</span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() =>
                      setLines(
                        lines.filter(
                          (x) =>
                            !(x.productId === l.productId && x.shadeId === l.shadeId),
                        ),
                      )
                    }
                  >
                    삭제
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="checkout-box">
          <div className="checkout-total">
            <span>합계</span>
            <strong>{money(total)}</strong>
          </div>
          <button
            type="button"
            className="btn btn-block"
            disabled={busy || !lines.length}
            onClick={() => void checkout()}
          >
            {busy ? "주문 생성 중…" : "주문하기"}
          </button>
          <p className="checkout-hint">
            결제는 앱·기존 결제 흐름과 같습니다. 주문을 만든 뒤 안내에 따라 이어가세요.
          </p>
          {error && <p className="form-error">{error}</p>}
          {orderId && (
            <p className="checkout-ok" role="status">
              주문이 생성되었습니다: <code>{orderId}</code>
            </p>
          )}
          <ArCta compact />
        </div>
      </div>
    </>
  );
}

function RequireAuth({
  ready,
  signedIn,
  children,
}: {
  ready: boolean;
  signedIn: boolean;
  children: React.ReactNode;
}) {
  if (!ready) return <p className="boot-status" role="status">로그인을 확인하고 있습니다…</p>;
  if (!signedIn) return <Navigate to="/login" replace />;
  return children;
}

export function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const [lines, setLinesState] = useState<CartLine[]>(() => loadCart());
  const [auth, setAuth] = useState({
    ready: false,
    signedIn: false,
    email: null as string | null,
  });
  const [role, setRole] = useState<"unknown" | "user" | "staff">("unknown");

  function setLines(next: CartLine[]) {
    setLinesState(next);
    saveCart(next);
  }
  function onAdd(line: CartLine) {
    const existing = lines.find(
      (l) => l.productId === line.productId && l.shadeId === line.shadeId,
    );
    if (existing) {
      setLines(
        lines.map((l) =>
          l.productId === line.productId && l.shadeId === line.shadeId
            ? { ...l, quantity: l.quantity + 1 }
            : l,
        ),
      );
    } else setLines([...lines, line]);
  }
  const count = lines.reduce((n, l) => n + l.quantity, 0);
  const onStaffPath =
    location.pathname === STAFF_HOME || location.pathname.startsWith(`${STAFF_HOME}/`);
  const roleReady = !auth.signedIn || role !== "unknown";

  useEffect(() => {
    if (!supabase) {
      setAuth({ ready: true, signedIn: false, email: null });
      return;
    }
    let alive = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (!alive) return;
      setAuth({
        ready: true,
        signedIn: !!data.session,
        email: data.session?.user.email ?? null,
      });
    });
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setAuth({
        ready: true,
        signedIn: !!session,
        email: session?.user.email ?? null,
      });
      if (!session) setRole("unknown");
    });
    return () => {
      alive = false;
      data.subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!auth.ready || !auth.signedIn) {
      setRole("unknown");
      return;
    }
    let alive = true;
    setRole("unknown");
    void isStaffSession()
      .then((staff) => {
        if (!alive) return;
        setRole(staff ? "staff" : "user");
      })
      .catch(() => {
        if (alive) setRole("user");
      });
    return () => {
      alive = false;
    };
  }, [auth.ready, auth.signedIn]);

  useEffect(() => {
    if (!auth.signedIn || role === "unknown") return;
    if (
      role === "staff" &&
      !onStaffPath &&
      location.pathname !== "/login" &&
      location.pathname !== "/signup"
    ) {
      navigate(STAFF_HOME, { replace: true });
    }
    if (role === "user" && onStaffPath) {
      navigate("/", { replace: true });
    }
  }, [auth.signedIn, role, onStaffPath, location.pathname, navigate]);

  if (auth.signedIn && !roleReady)
    return <p className="boot-status" role="status">권한을 확인하고 있습니다…</p>;

  return (
    <Routes>
      <Route path="/login" element={<LoginPage signedIn={auth.signedIn && roleReady} />} />
      <Route path="/signup" element={<SignupPage signedIn={auth.signedIn && roleReady} />} />
      <Route
        path="/admin/*"
        element={
          <RequireAuth ready={auth.ready} signedIn={auth.signedIn}>
            {role === "staff" ? <StaffApp /> : <Navigate to="/" replace />}
          </RequireAuth>
        }
      />
      <Route
        path="/*"
        element={
          <RequireAuth ready={auth.ready} signedIn={auth.signedIn}>
            {role === "staff" ? (
              <Navigate to={STAFF_HOME} replace />
            ) : (
              <Shell cartCount={count} email={auth.email}>
                <Routes>
                  <Route path="/" element={<Home />} />
                  <Route path="/products/:id" element={<ProductDetail onAdd={onAdd} />} />
                  <Route
                    path="/cart"
                    element={<CartPage lines={lines} setLines={setLines} />}
                  />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Shell>
            )}
          </RequireAuth>
        }
      />
    </Routes>
  );
}
