import { useState } from "react";
import { Link, Route, Routes, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Audit, Order, Page, Product, Staff, Status } from "../api/types";
export const statusLabels: Record<Status, string> = {
  pending: "결제 대기",
  paid: "결제 완료",
  preparing: "준비 중",
  shipped: "발송 완료",
  delivered: "배송 완료",
  canceled: "취소",
};
const money = (n: number) => `${n.toLocaleString("ko-KR")}원`;
const date = (v: string | null) =>
  v ? new Date(v).toLocaleString("ko-KR") : "기록 없음";
export function LoadingError({
  pending,
  error,
}: {
  pending: boolean;
  error: unknown;
}) {
  return pending ? (
    <p role="status">불러오는 중…</p>
  ) : error ? (
    <p role="alert">
      요청을 처리하지 못했습니다. {error instanceof Error ? error.message : ""}
    </p>
  ) : null;
}
export function Orders({ staff }: { staff: Staff }) {
  return (
    <Routes>
      <Route index element={<OrderList />} />
      <Route path=":id" element={<OrderDetail staff={staff} />} />
    </Routes>
  );
}
function OrderList() {
  const [status, setStatus] = useState("");
  const [cursor, setCursor] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const q = useQuery({
    queryKey: ["orders", status, cursor],
    queryFn: () =>
      api<Page<Order>>(
        `/orders?${new URLSearchParams({ status, cursor, ...(!status ? {} : { status }) }).toString().replace("status=&", "")}`,
      ),
  });
  return (
    <>
      <p className="eyebrow">COMMERCE</p>
      <h1>주문 관리</h1>
      <p>결제부터 배송 완료까지 주문 상태를 확인하세요.</p>
      <div className="toolbar">
        <label>
          주문 상태
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setCursor("");
              setHistory([]);
            }}
          >
            <option value="">전체 상태</option>
            {Object.entries(statusLabels).map(([k, v]) => (
              <option value={k} key={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </div>
      <LoadingError pending={q.isPending} error={q.error} />
      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>주문</th>
              <th>회원</th>
              <th>금액</th>
              <th>상태</th>
              <th>생성 시각</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.items.map((r) => (
              <tr key={r.id}>
                <td>
                  <Link to={r.id}>{r.orderName}</Link>
                  <small>{r.id}</small>
                </td>
                <td>{r.userId}</td>
                <td>{money(r.amountKRW)}</td>
                <td>
                  <span className="badge">{statusLabels[r.status]}</span>
                </td>
                <td>{date(r.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {q.data?.items.length === 0 && (
          <p className="empty">조건에 맞는 주문이 없습니다.</p>
        )}
      </div>
      <div className="pagination">
        <button
          disabled={!history.length}
          onClick={() => {
            setCursor(history.at(-1) || "");
            setHistory(history.slice(0, -1));
          }}
        >
          이전
        </button>
        <button
          disabled={!q.data?.nextCursor}
          onClick={() => {
            setHistory([...history, cursor]);
            setCursor(q.data?.nextCursor || "");
          }}
        >
          다음
        </button>
      </div>
    </>
  );
}
export function OrderActions({
  order,
  staff,
  onChange,
  busy,
}: {
  order: Order;
  staff: Staff;
  onChange: (status: Status, reason: string) => void;
  busy: boolean;
}) {
  const [cancel, setCancel] = useState(false);
  const [reason, setReason] = useState("");
  if (staff.role !== "admin") return null;
  return (
    <div className="actions">
      {order.nextStatuses.map((s) => (
        <button
          disabled={busy}
          className={s === "canceled" ? "secondary" : ""}
          key={s}
          onClick={() => (s === "canceled" ? setCancel(true) : onChange(s, ""))}
        >
          {statusLabels[s]}로 변경
        </button>
      ))}
      {cancel && (
        <dialog open aria-labelledby="cancel-title">
          <h2 id="cancel-title">주문을 취소할까요?</h2>
          <p>테스트 결제를 취소하고 차감한 재고를 복원합니다.</p>
          <label>
            취소 사유
            <textarea
              maxLength={200}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <button
            disabled={!reason.trim() || busy}
            onClick={() => {
              onChange("canceled", reason);
              setCancel(false);
            }}
          >
            취소 확정
          </button>
          <button className="secondary" onClick={() => setCancel(false)}>
            돌아가기
          </button>
        </dialog>
      )}
    </div>
  );
}
function OrderDetail({ staff }: { staff: Staff }) {
  const { id } = useParams();
  const cache = useQueryClient();
  const q = useQuery({
    queryKey: ["order", id],
    queryFn: () => api<Order>(`/orders/${encodeURIComponent(id!)}`),
  });
  const mutation = useMutation({
    mutationFn: ({ status, reason }: { status: Status; reason: string }) =>
      api<Order>(`/orders/${encodeURIComponent(id!)}/status`, {
        method: "POST",
        body: JSON.stringify({ status, reason }),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["order", id] });
      void cache.invalidateQueries({ queryKey: ["orders"] });
    },
  });
  return (
    <>
      <Link to="/orders">← 주문 목록</Link>
      <h1>주문 상세</h1>
      <LoadingError pending={q.isPending} error={q.error || mutation.error} />
      {q.data && (
        <>
          <section className="panel">
            <h2>{q.data.orderName}</h2>
            <p>
              {statusLabels[q.data.status]} · {money(q.data.amountKRW)}
            </p>
            <dl>
              <dt>주문 번호</dt>
              <dd>{q.data.id}</dd>
              <dt>생성 / 결제</dt>
              <dd>
                {date(q.data.createdAt)} / {date(q.data.paidAt)}
              </dd>
              <dt>결제 키</dt>
              <dd>{q.data.paymentKey || "없음"}</dd>
            </dl>
            <OrderActions
              order={q.data}
              staff={staff}
              busy={mutation.isPending}
              onChange={(status, reason) => mutation.mutate({ status, reason })}
            />
          </section>
          <section className="panel">
            <h2>주문 상품</h2>
            {q.data.lines?.map((l) => (
              <div className="line" key={l.id}>
                <span>
                  {l.productName} · {l.shadeId || "기본"}
                </span>
                <span>
                  {l.quantity}개 · {money(l.unitPriceKRW)}
                </span>
              </div>
            ))}
          </section>
        </>
      )}
    </>
  );
}
export function Products({ staff }: { staff: Staff }) {
  return (
    <Routes>
      <Route index element={<ProductList />} />
      <Route path=":id" element={<ProductDetail staff={staff} />} />
    </Routes>
  );
}
function ProductList() {
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [cursor, setCursor] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const q = useQuery({
    queryKey: ["products", search, category, cursor],
    queryFn: () =>
      api<Page<Product>>(
        `/products?${new URLSearchParams({ query: search, category, cursor })}`,
      ),
  });
  return (
    <>
      <p className="eyebrow">CATALOG</p>
      <h1>상품 관리</h1>
      <p>카탈로그 원본을 확인하고 노출과 판매 재고를 관리하세요.</p>
      <form
        className="toolbar"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(query);
          setCursor("");
          setHistory([]);
        }}
      >
        <label>
          상품 검색
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="상품명 또는 브랜드"
          />
        </label>
        <label>
          카테고리
          <select
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              setCursor("");
              setHistory([]);
            }}
          >
            <option value="">전체</option>
            {["lip", "cheek", "eye", "base", "skincare", "suncare"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <button>검색</button>
      </form>
      <LoadingError pending={q.isPending} error={q.error} />
      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>상품</th>
              <th>가격</th>
              <th>노출</th>
              <th>재고</th>
              <th>셰이드 / 측정 방식</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.items.map((p) => (
              <tr key={p.id}>
                <td>
                  <small>{p.brand}</small>
                  <Link to={p.id}>{p.name}</Link>
                </td>
                <td>{money(p.priceKRW)}</td>
                <td>{p.isVisible ? "노출" : "숨김"}</td>
                <td>{p.stock ?? "제한 없음"}</td>
                <td>
                  {p.shadeCount}개 · {p.measurementMethods.join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {q.data?.items.length === 0 && (
          <p className="empty">조건에 맞는 상품이 없습니다.</p>
        )}
      </div>
      <div className="pagination">
        <button
          disabled={!history.length}
          onClick={() => {
            setCursor(history.at(-1) || "");
            setHistory(history.slice(0, -1));
          }}
        >
          이전
        </button>
        <button
          disabled={!q.data?.nextCursor}
          onClick={() => {
            setHistory([...history, cursor]);
            setCursor(q.data?.nextCursor || "");
          }}
        >
          다음
        </button>
      </div>
    </>
  );
}
function ProductEditor({
  product,
  onSave,
  busy,
}: {
  product: Product;
  onSave: (body: { stock: number | null; isVisible: boolean }) => void;
  busy: boolean;
}) {
  const [visible, setVisible] = useState(product.isVisible);
  const [stock, setStock] = useState(
    product.stock === null ? "" : String(product.stock),
  );
  return (
    <form
      className="toolbar"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({
          stock: stock === "" ? null : Number(stock),
          isVisible: visible,
        });
      }}
    >
      <label>
        <input
          type="checkbox"
          checked={visible}
          onChange={(e) => setVisible(e.target.checked)}
        />
        앱에 노출
      </label>
      <label>
        재고 (빈칸은 제한 없음)
        <input
          type="number"
          min={0}
          max={2000000000}
          step={1}
          value={stock}
          onChange={(e) => setStock(e.target.value)}
        />
      </label>
      <button disabled={busy}>저장</button>
    </form>
  );
}
function ProductDetail({ staff }: { staff: Staff }) {
  const { id } = useParams();
  const cache = useQueryClient();
  const q = useQuery({
    queryKey: ["product", id],
    queryFn: () => api<Product>(`/products/${encodeURIComponent(id!)}`),
  });
  const m = useMutation({
    mutationFn: (body: { stock: number | null; isVisible: boolean }) =>
      api<Product>(`/products/${encodeURIComponent(id!)}/admin-state`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["product", id] });
      void cache.invalidateQueries({ queryKey: ["products"] });
    },
  });
  return (
    <>
      <Link to="/products">← 상품 목록</Link>
      <h1>{q.data?.name || "상품 상세"}</h1>
      <LoadingError pending={q.isPending} error={q.error || m.error} />
      {m.isSuccess && <p role="status">저장했습니다.</p>}
      {q.data && (
        <>
          <section className="panel">
            <p>
              {q.data.brand} · {money(q.data.priceKRW)}
            </p>
            {staff.role === "admin" ? (
              <ProductEditor
                key={q.data.id + String(q.data.stock) + q.data.isVisible}
                product={q.data}
                busy={m.isPending}
                onSave={(body) => m.mutate(body)}
              />
            ) : (
              <p>
                {q.data.isVisible ? "노출" : "숨김"} · 재고{" "}
                {q.data.stock ?? "제한 없음"}
              </p>
            )}
          </section>
          <section className="panel">
            <h2>셰이드 원본</h2>
            <p>
              색 변경은 카탈로그 묶음에서 하고 AR
              벤치마크(research/lip_rubric/bench.py)를 다시 측정해야 합니다.
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>셰이드</th>
                    <th>HEX</th>
                    <th>측정 방식</th>
                    <th>출처 / 신뢰도</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.shades?.map((s) => (
                    <tr key={s.id}>
                      <td>{s.name}</td>
                      <td>{s.hex}</td>
                      <td>
                        {s.measureMethod || "미확인"}{" "}
                        {s.measureMethod !== "measured" && (
                          <span className="badge">측정값 아님</span>
                        )}
                      </td>
                      <td>
                        {s.colorSource || "미확인"} /{" "}
                        {s.colorConfidence ?? "미측정"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  );
}
export function AuditLog() {
  const [cursor, setCursor] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const q = useQuery({
    queryKey: ["audit", cursor],
    queryFn: () =>
      api<Page<Audit>>(`/audit-log?cursor=${encodeURIComponent(cursor)}`),
  });
  return (
    <>
      <p className="eyebrow">ACCOUNTABILITY</p>
      <h1>감사 로그</h1>
      <p>관리자 변경 이력을 최근 순서로 확인합니다.</p>
      <LoadingError pending={q.isPending} error={q.error} />
      <section className="panel">
        {q.data?.items.map((a) => (
          <details key={a.id}>
            <summary>
              {date(a.createdAt)} · {a.action} · {a.targetId}
            </summary>
            <p>
              실행자 {a.actorUserId || "운영자 작업 또는 탈퇴 계정"} · 요청{" "}
              {a.requestId}
            </p>
            <pre>
              {JSON.stringify(
                { before: a.beforeJson, after: a.afterJson },
                null,
                2,
              )}
            </pre>
          </details>
        ))}
        {q.data?.items.length === 0 && (
          <p className="empty">변경 기록이 없습니다.</p>
        )}
      </section>
      <div className="pagination">
        <button
          disabled={!history.length}
          onClick={() => {
            setCursor(history.at(-1) || "");
            setHistory(history.slice(0, -1));
          }}
        >
          이전
        </button>
        <button
          disabled={!q.data?.nextCursor}
          onClick={() => {
            setHistory([...history, cursor]);
            setCursor(q.data?.nextCursor || "");
          }}
        >
          다음
        </button>
      </div>
    </>
  );
}
