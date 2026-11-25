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
      <header className="top">
        <Link to="/" className="brand">
          VISHUE
        </Link>
        <nav className="nav">
          <NavLink to="/" end>
            쇼핑
          </NavLink>
          <NavLink to="/cart">장바구니 ({cartCount})</NavLink>
          {email && <span className="nav-user">{email}</span>}
          <button
            type="button"
            className="secondary nav-logout"
            onClick={() => void signOut()}
          >
            로그아웃
          </button>
        </nav>
      </header>
      <main className="main">{children}</main>
    </div>
  );
}

function money(n: number) {
  return `${n.toLocaleString("ko-KR")}원`;
}

function ArCta() {
  return (
    <div className="ar-banner">
      <strong>AR 가상 메이크업은 앱에서</strong>
      <p>
        웹에서는 쇼핑만 지원합니다. 입술에 직접 바른 것처럼 보려면 VISHUE 앱의 AR을
        열어 주세요.
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <a href={arAppUrl} target="_blank" rel="noreferrer">
          <button type="button">앱에서 AR 열기</button>
        </a>
        {appStoreUrl && (
          <a href={appStoreUrl} target="_blank" rel="noreferrer">
            <button type="button" className="secondary">
              스토어로 이동
            </button>
          </a>
        )}
      </div>
    </div>
  );
}

function Home() {
  const q = useQuery({
    queryKey: ["products"],
    queryFn: () => api<{ products: Product[] }>("/api/products?category=lip"),
  });
  return (
    <>
      <section className="hero">
        <h1>VISHUE 쇼핑</h1>
        <p>립 제품을 고르고 장바구니에 담으세요. AR 가상 피팅은 앱에서 이어갑니다.</p>
        <ArCta />
      </section>
      {q.isPending && <p>불러오는 중…</p>}
      {q.error && (
        <p className="form-error">
          {q.error instanceof Error ? q.error.message : "목록을 불러오지 못했습니다."}
        </p>
      )}
      {q.data && (
        <div className="grid">
          {q.data.products.map((p) => (
            <Link key={p.id} to={`/products/${encodeURIComponent(p.id)}`} className="card">
              <img src={p.imageUrl || undefined} alt="" />
              <div className="body">
                <span className="brand-line">{p.brand}</span>
                <span className="name">{p.name}</span>
                <span className="price">{money(p.priceKRW)}</span>
              </div>
            </Link>
          ))}
          {!q.data.products.length && <p className="empty">표시할 상품이 없습니다.</p>}
        </div>
      )}
    </>
  );
}

function ProductDetail({
  onAdd,
}: {
  onAdd: (line: CartLine) => void;
}) {
  const { id = "" } = useParams();
  const q = useQuery({
    queryKey: ["product", id],
    queryFn: () => api<{ product: Product }>(`/api/products/${encodeURIComponent(id)}`),
    enabled: !!id,
  });
  const product = q.data?.product;
  const shades = product?.shades || [];
  const [shadeId, setShadeId] = useState("");
  useEffect(() => {
    if (shades[0] && !shadeId) setShadeId(shades[0].id);
  }, [shades, shadeId]);
  const shade = shades.find((s) => s.id === shadeId) || shades[0];

  return (
    <>
      {q.isPending && <p>불러오는 중…</p>}
      {q.error && (
        <p className="form-error">
          {q.error instanceof Error ? q.error.message : "상품을 불러오지 못했습니다."}
        </p>
      )}
      {product && (
        <div className="detail">
          <img src={product.imageUrl || undefined} alt={product.name} />
          <div>
            <p className="brand-line">{product.brand}</p>
            <h1 style={{ margin: "4px 0 8px", fontSize: 28 }}>{product.name}</h1>
            <p>{money(product.priceKRW)}</p>
            {!!shades.length && (
              <>
                <p style={{ marginTop: 16, fontSize: 13, color: "#6b5f63" }}>
                  쉐이드 {shade?.name}
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
                      onClick={() => setShadeId(s.id)}
                    />
                  ))}
                </div>
              </>
            )}
            <div style={{ marginTop: 18, display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
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
                }}
              >
                장바구니 담기
              </button>
              <Link to="/cart">
                <button type="button" className="secondary">
                  장바구니
                </button>
              </Link>
            </div>
            <ArCta />
          </div>
        </div>
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
      <h1>장바구니</h1>
      {!lines.length && !orderId && <p className="empty">담은 상품이 없습니다.</p>}
      {!!lines.length && (
        <table className="cart-table">
          <thead>
            <tr>
              <th>상품</th>
              <th>쉐이드</th>
              <th>수량</th>
              <th>금액</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={`${l.productId}:${l.shadeId}`}>
                <td>
                  {l.brand} {l.productName}
                </td>
                <td>{l.shadeName}</td>
                <td>{l.quantity}</td>
                <td>{money(l.unitPriceKRW * l.quantity)}</td>
                <td>
                  <button
                    type="button"
                    className="secondary"
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
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="checkout-box">
        <div>
          합계 <strong>{money(total)}</strong>
        </div>
        <button type="button" disabled={busy || !lines.length} onClick={() => void checkout()}>
          {busy ? "주문 생성 중…" : "주문 생성 (결제 준비)"}
        </button>
        <p style={{ margin: 0, fontSize: 13, color: "#6b5f63" }}>
          Toss 위젯 확정은 앱·기존 `/pay` 흐름과 동일합니다. 여기서는 주문을 만들고 결제는
          운영 설정에 맞는 웹 결제 URL로 이어가세요.
        </p>
        {error && <p className="form-error">{error}</p>}
        {orderId && (
          <p role="status">
            주문이 생성되었습니다: <code>{orderId}</code>
          </p>
        )}
      </div>
      <ArCta />
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
  if (!ready) return <p role="status">로그인을 확인하고 있습니다…</p>;
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
  const onStaffPath = location.pathname === STAFF_HOME || location.pathname.startsWith(`${STAFF_HOME}/`);
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
    if (role === "staff" && !onStaffPath && location.pathname !== "/login" && location.pathname !== "/signup") {
      navigate(STAFF_HOME, { replace: true });
    }
    if (role === "user" && onStaffPath) {
      navigate("/", { replace: true });
    }
  }, [auth.signedIn, role, onStaffPath, location.pathname, navigate]);

  if (auth.signedIn && !roleReady)
    return <p role="status">권한을 확인하고 있습니다…</p>;

  return (
    <Routes>
      <Route
        path="/login"
        element={<LoginPage signedIn={auth.signedIn && roleReady} />}
      />
      <Route
        path="/signup"
        element={<SignupPage signedIn={auth.signedIn && roleReady} />}
      />
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
