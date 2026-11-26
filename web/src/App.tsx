import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  ApiError,
  api,
  appStoreUrl,
  arAppUrl,
  supabase,
  type CartLine,
  type Product,
  type ProductDiscoveryOrder,
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
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const query = params.get("q") ?? "";
  const [headerQuery, setHeaderQuery] = useState(query);
  useEffect(() => setHeaderQuery(query), [query]);

  return (
    <div className="shell">
      <header className="site-header">
        <div className="site-header-inner">
          <Link to="/" className="brand" aria-label="VISHUE 홈">
            VISHUE<span className="brand-dot">.</span>
          </Link>
          <form
            className="header-search"
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              navigate(browseUrl(null, headerQuery.trim()));
            }}
          >
            <input
              type="search"
              aria-label="브랜드와 제품 검색"
              placeholder="브랜드·제품 검색"
              value={headerQuery}
              onChange={(event) => setHeaderQuery(event.target.value)}
            />
            <button type="submit" className="btn btn-sm">검색</button>
          </form>
          <nav className="site-nav" aria-label="주요 메뉴">
            <NavLink to="/" end>
              쇼핑
            </NavLink>
            <NavLink to="/cart">
              장바구니
              {cartCount > 0 ? <span className="nav-count">{cartCount}</span> : null}
            </NavLink>
          </nav>
          <div className="site-actions">
            <a
              href={arAppUrl}
              target="_blank"
              rel="noreferrer"
              className="btn btn-sm btn-ar"
            >
              앱에서 AR 열기
            </a>
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

const SHOP_CATEGORIES = [
  { id: "lip", label: "립" },
  { id: "cheek", label: "치크" },
  { id: "eye", label: "아이" },
  { id: "base", label: "베이스" },
  { id: "skincare", label: "스킨케어" },
  { id: "suncare", label: "선케어" },
] as const;

function browseUrl(category: string | null, query = "") {
  const params = new URLSearchParams();
  if (category) params.set("category", category);
  if (query) params.set("q", query);
  return `/${params.size ? `?${params}` : ""}#browse`;
}

const PRODUCT_PAGE_SIZE = 24;
const PRODUCT_STALE_TIME = 5 * 60 * 1000;

const SHOP_CHARTS = {
  makeup: "메이크업 차트",
  skincare: "스킨케어 차트",
  new: "신상품",
} as const;

const HOME_SHELVES = [
  { key: "hot", title: "요즘 눈여겨볼 아이템", to: null },
  { key: "makeup", title: SHOP_CHARTS.makeup, to: "/charts/makeup" },
  { key: "newArrivals", title: SHOP_CHARTS.new, to: "/charts/new" },
  { key: "skincare", title: SHOP_CHARTS.skincare, to: "/charts/skincare" },
] as const;

function ProductCard({
  product,
  compact,
}: {
  product: Product;
  compact?: boolean;
}) {
  return (
    <Link
      to={`/products/${encodeURIComponent(product.id)}`}
      className={`product-card${compact ? " is-compact" : ""}`}
    >
      <div className="product-thumb">
        {product.imageUrl && <img src={product.imageUrl} alt="" loading="lazy" decoding="async" />}
      </div>
      <div className="product-body">
        <span className="product-brand">{product.brand}</span>
        <span className="product-name">{product.name}</span>
        <span className="product-price">{money(product.priceKRW)}</span>
        {!compact && !!product.shades?.length && product.shades.length > 1 && (
          <span className="shade-row">
            {product.shades.slice(0, 5).map((s) => (
              <span
                key={s.id}
                className="shade-dot"
                style={{ background: s.hex }}
                title={s.name}
              />
            ))}
            <span className="shade-count">{product.shades.length}색</span>
          </span>
        )}
      </div>
    </Link>
  );
}

function ShopCategoryNav({ category, query = "" }: { category?: string | null; query?: string }) {
  return (
    <nav className="shop-category-nav" aria-label="제품 카테고리">
      <Link to={browseUrl(null, query)} aria-current={category === null ? "page" : undefined}>
        전체
      </Link>
      {SHOP_CATEGORIES.map((item) => (
        <Link
          key={item.id}
          to={browseUrl(item.id, query)}
          aria-current={category === item.id ? "page" : undefined}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

function ProductShelf({ title, to, products }: { title: string; to: string | null; products: Product[] }) {
  const id = useId();
  const shelf = useRef<HTMLDivElement>(null);
  const [controls, setControls] = useState({ previous: false, next: false });

  useEffect(() => {
    const row = shelf.current;
    if (!row) return;
    const updateControls = () => {
      const previous = row.scrollLeft > 1;
      const next = row.scrollLeft + row.clientWidth < row.scrollWidth - 1;
      setControls((current) => current.previous === previous && current.next === next
        ? current
        : { previous, next });
    };
    updateControls();
    row.addEventListener("scroll", updateControls, { passive: true });
    const observer = new ResizeObserver(updateControls);
    observer.observe(row);
    return () => {
      row.removeEventListener("scroll", updateControls);
      observer.disconnect();
    };
  }, [products.length]);

  function scrollShelf(direction: number) {
    const row = shelf.current;
    if (!row) return;
    const gap = Number.parseFloat(getComputedStyle(row).columnGap);
    row.scrollBy({ left: direction * (row.clientWidth + gap) });
  }

  return (
    <section className="shop-shelf" aria-labelledby={`${id}-title`}>
      <div className="shelf-heading">
        <h2 id={`${id}-title`}>{title}</h2>
        <div className="shelf-actions">
          {to && (
            <Link className="btn btn-ghost btn-sm" to={to} aria-label={`${title} 전체 보기`}>
              전체 보기
            </Link>
          )}
          {(controls.previous || controls.next) && (
            <div className="shelf-controls">
              <button
                className="btn btn-ghost btn-sm shelf-arrow"
                type="button"
                aria-label={`${title} 이전 상품`}
                aria-controls={id}
                disabled={!controls.previous}
                onClick={() => scrollShelf(-1)}
              >
                <span aria-hidden="true">‹</span>
              </button>
              <button
                className="btn btn-ghost btn-sm shelf-arrow"
                type="button"
                aria-label={`${title} 다음 상품`}
                aria-controls={id}
                disabled={!controls.next}
                onClick={() => scrollShelf(1)}
              >
                <span aria-hidden="true">›</span>
              </button>
            </div>
          )}
        </div>
      </div>
      <div
        ref={shelf}
        id={id}
        className="shelf-products"
        tabIndex={controls.previous || controls.next ? 0 : undefined}
        role="group"
        aria-labelledby={`${id}-title`}
      >
        {products.map((product) => <ProductCard key={product.id} product={product} compact />)}
      </div>
    </section>
  );
}

function ProductListError({ error, onRetry }: { error: Error | null; onRetry: () => void }) {
  return (
    <div className="catalog-error" role="alert">
      <p className="form-error">{error?.message || "목록을 불러오지 못했습니다."}</p>
      <button type="button" className="btn btn-sm" onClick={onRetry}>다시 시도</button>
    </div>
  );
}

function ShopHome() {
  const order = useQuery({
    queryKey: ["discovery", "product-order", "preview"],
    staleTime: PRODUCT_STALE_TIME,
    queryFn: ({ signal }) =>
      api<ProductDiscoveryOrder>("/api/discovery/product-order?preview=true", { signal }),
  });
  const ids = [...new Set(HOME_SHELVES.flatMap(({ key }) => order.data?.[key] ?? []))].join(",");
  const products = useQuery({
    queryKey: ["products", "by-ids", ids],
    enabled: !!ids,
    staleTime: PRODUCT_STALE_TIME,
    queryFn: ({ signal }) =>
      api<{ products: Product[] }>(`/api/products?${new URLSearchParams({ ids })}`, { signal }),
  });
  const byId = new Map((products.data?.products ?? []).map((product) => [product.id, product]));

  return (
    <>
      <ShopCategoryNav />
      <section className="shop-hero">
        <div className="shop-hero-copy">
          <p className="hero-kicker">FIND YOUR SHADE</p>
          <h1>오늘 바르고 싶은<br />나만의 컬러</h1>
          <p>나에게 어울리는 뷰티 아이템을 발견해 보세요.</p>
          <Link to={browseUrl("lip")} className="btn hero-button">립 제품 보기</Link>
        </div>
        <div className="shop-hero-image" aria-hidden="true" />
      </section>
      {(order.isPending || (!!ids && products.isPending)) && (
        <p className="state" role="status">추천 상품을 불러오는 중…</p>
      )}
      {order.isError && !order.data && (
        <ProductListError error={order.error} onRetry={() => void order.refetch()} />
      )}
      {products.isError && !products.data && (
        <ProductListError error={products.error} onRetry={() => void products.refetch()} />
      )}
      {HOME_SHELVES.map(({ key, title, to }) => {
        const items = (order.data?.[key] ?? []).flatMap((id) => {
          const product = byId.get(id);
          return product ? [product] : [];
        });
        return items.length > 0 && <ProductShelf key={key} title={title} to={to} products={items} />;
      })}
      <ArCta />
    </>
  );
}

function PagedProductList({ path, filters = "", empty }: { path: string; filters?: string; empty: string }) {
  const results = useInfiniteQuery({
    queryKey: ["products", "pages", path, filters],
    staleTime: PRODUCT_STALE_TIME,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams(filters);
      params.set("limit", String(PRODUCT_PAGE_SIZE));
      params.set("offset", String(pageParam));
      return api<{ products: Product[]; hasMore: boolean }>(`${path}?${params}`, { signal });
    },
    getNextPageParam: (page, _pages, offset) => page.hasMore ? offset + PRODUCT_PAGE_SIZE : undefined,
  });

  if (results.isPending) return <p className="state" role="status">상품을 불러오는 중…</p>;
  if (!results.data) {
    return <ProductListError error={results.error} onRetry={() => void results.refetch()} />;
  }

  const byId = new Map(results.data.pages.flatMap((page) =>
    page.products.map((product) => [product.id, product] as const)));
  if (!byId.size && !results.hasNextPage) return <p className="empty">{empty}</p>;

  return (
    <>
      <p className="product-list-count" role="status">표시된 상품 {byId.size}개</p>
      <div className="product-grid product-grid-tight">
        {[...byId.values()].map((product) => <ProductCard key={product.id} product={product} compact />)}
      </div>
      {results.hasNextPage && (
        <div className="product-list-more">
          {results.isFetchNextPageError && (
            <p className="form-error" role="alert">다음 상품을 불러오지 못했어요.</p>
          )}
          <button
            type="button"
            className="btn btn-ghost"
            disabled={results.isFetching}
            onClick={() => void results.fetchNextPage()}
          >
            {results.isFetchingNextPage ? "불러오는 중…" : results.isFetchNextPageError ? "다시 시도" : "상품 더 보기"}
          </button>
        </div>
      )}
    </>
  );
}

function Home() {
  const location = useLocation();
  const [params] = useSearchParams();
  const query = params.get("q")?.trim() ?? "";
  const active = SHOP_CATEGORIES.find((category) => category.id === params.get("category"));
  const category = active?.id ?? null;
  const browsing = !!active || !!query || location.hash === "#browse";

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0 });
    if (browsing) document.getElementById("browse")?.focus({ preventScroll: true });
  }, [browsing, location.key]);

  if (!browsing) return <ShopHome />;

  const filters = new URLSearchParams();
  if (category) filters.set("category", category);
  if (query) filters.set("q", query);
  return (
    <section className="catalog" aria-labelledby="browse">
      <div className="page-title">
        <p className="eyebrow"><Link to="/">← 쇼핑 홈</Link></p>
        <h1 id="browse" tabIndex={-1}>{query ? "검색 결과" : active?.label ?? "전체 상품"}</h1>
      </div>
      <ShopCategoryNav category={category} query={query} />
      {query && (
        <div className="catalog-filter-hint">
          <span>{active ? `${active.label} · ` : ""}“{query}”</span>
          <Link to={browseUrl(category)} className="btn btn-ghost btn-sm">검색어 지우기</Link>
        </div>
      )}
      <PagedProductList path="/api/products" filters={filters.toString()} empty="표시할 상품이 없습니다." />
    </section>
  );
}

function ChartPage() {
  const { kind } = useParams();
  const chart = kind === "skincare" || kind === "new" ? kind : "makeup";

  useEffect(() => window.scrollTo({ top: 0, left: 0 }), [chart]);

  return (
    <>
      <section className="page-title">
        <p className="eyebrow">
          <Link to="/">← 쇼핑 홈</Link>
        </p>
        <h1>{SHOP_CHARTS[chart]}</h1>
      </section>
      <PagedProductList
        path={`/api/discovery/charts/${chart}`}
        empty={chart === "new" ? "신상품을 준비하고 있어요." : "차트를 준비하고 있어요."}
      />
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
        <div className="catalog-error" role="alert">
          <p className="form-error">
            {q.error instanceof Error ? q.error.message : "상품을 불러오지 못했습니다."}
          </p>
          <button type="button" className="btn btn-sm" onClick={() => void q.refetch()}>
            다시 시도
          </button>
        </div>
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
      <Route
        path="/login"
        element={
          <LoginPage
            signedIn={auth.signedIn && roleReady}
            isStaff={role === "staff"}
          />
        }
      />
      <Route
        path="/signup"
        element={
          <SignupPage
            signedIn={auth.signedIn && roleReady}
            isStaff={role === "staff"}
          />
        }
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
                  <Route path="/charts/:kind" element={<ChartPage />} />
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
