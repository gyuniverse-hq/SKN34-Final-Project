import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, apiBlob, apiForm } from "../api/client";
import type {
  LipEvalAggregate,
  LipEvalProduct,
  LipEvalProductList,
  LipEvalSlot,
  TechMetricId,
} from "../api/types";
import { NaturalnessCriteriaGuide } from "../components/NaturalnessCriteriaGuide";
import {
  anchorFor,
  type NaturalnessCriteria,
} from "../lib/naturalnessCriteria";
import {
  buildLipEvalCsv,
  downloadTextFile,
  panelProgress,
  slotProgress,
  type SlotProgress,
} from "../lib/lipEvalExport";

const techNames: Record<TechMetricId, string> = {
  delta_e: "ΔE",
  ssim: "SSIM",
  mae: "MAE",
  miou: "mIoU",
  lpips: "LPIPS",
};

const verdictKo = {
  pass: "통과",
  fail: "미통과",
  report_only: "기록",
} as const;

function slotStatus(slot: LipEvalSlot) {
  if (slot.scored) return "완료";
  if (slot.readyForAr) return "AR대기";
  return "기준필요";
}

function SlotImages({ slot }: { slot: LipEvalSlot }) {
  const [urls, setUrls] = useState<Record<string, string>>({});
  useEffect(() => {
    let alive = true;
    const created: string[] = [];
    (async () => {
      const next: Record<string, string> = {};
      for (const kind of ["bare", "real", "ar"] as const) {
        const path = slot.imageUrls[kind];
        if (!path) continue;
        try {
          const blobUrl = await apiBlob(path.replace(/^\/api\/admin/, ""));
          created.push(blobUrl);
          next[kind] = blobUrl;
        } catch {
          /* preview optional */
        }
      }
      if (alive) setUrls(next);
    })();
    return () => {
      alive = false;
      created.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [slot.imageUrls.bare, slot.imageUrls.real, slot.imageUrls.ar, slot.raterId]);

  const kinds = (["bare", "real", "ar"] as const).filter((k) => urls[k]);
  if (!kinds.length) return null;

  return (
    <div className="slot-thumbs">
      {kinds.map((kind) => (
        <figure key={kind}>
          <img src={urls[kind]} alt={kind} />
          <figcaption>
            {kind === "bare" ? "맨입술" : kind === "real" ? "실제립" : "AR"}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

function MiniSlot({
  slot,
  active,
  onSelect,
}: {
  slot: LipEvalSlot;
  active: boolean;
  onSelect: () => void;
}) {
  const nat = slot.naturalness?.mean;
  const tech = slot.technical?.overall;
  return (
    <button
      type="button"
      className={`lip-mini-slot${active ? " is-active" : ""}${slot.scored ? " is-scored" : ""}`}
      onClick={onSelect}
    >
      <div className="lip-mini-top">
        <span className="lip-mini-label">{slot.label}</span>
        <span className="badge">{slotStatus(slot)}</span>
      </div>
      <div className="lip-mini-scores">
        <span>
          자연 <b>{nat == null ? "—" : nat.toFixed(1)}</b>
        </span>
        <span>
          테크 <b>{tech ? verdictKo[tech] : "—"}</b>
        </span>
      </div>
    </button>
  );
}

function AggregateCard({ aggregate }: { aggregate: LipEvalAggregate }) {
  return (
    <div className={`lip-agg-card${aggregate.finalized ? " is-final" : ""}`}>
      <div className="lip-agg-title">합산</div>
      <div className="lip-agg-row">
        <span>자연</span>
        <b>{aggregate.naturalnessMean ?? "—"}</b>
      </div>
      <div className="lip-agg-row">
        <span>테크</span>
        <b>
          {aggregate.technicalOverallPassRate == null
            ? "—"
            : `${Math.round(aggregate.technicalOverallPassRate * 100)}%`}
        </b>
      </div>
      <div className="lip-agg-progress">
        <span className="badge">
          {aggregate.scoredCount}/5{aggregate.finalized ? " 확정" : " 진행"}
        </span>
      </div>
    </div>
  );
}

const progressLabel: Record<SlotProgress, string> = {
  empty: "기준",
  refs: "AR",
  scored: "완료",
};

function ProgressBoard({
  items,
  productId,
  raterId,
  onSelect,
}: {
  items: LipEvalProduct[];
  productId: string;
  raterId: number;
  onSelect: (productId: string, raterId: number) => void;
}) {
  const progress = panelProgress(items);
  return (
    <div className="lip-board">
      <div className="lip-board-toolbar">
        <div className="lip-board-stats">
          <span>
            채점 <b>{progress.scored}</b>/{progress.total}
          </span>
          <span>
            기준완료 <b>{progress.refs}</b>
          </span>
          <span>
            미착수 <b>{progress.empty}</b>
          </span>
          <span>
            확정제품 <b>{progress.finalized}</b>/{progress.products}
          </span>
        </div>
        <div className="lip-board-legend">
          <span className="lip-cell is-empty">기준필요</span>
          <span className="lip-cell is-refs">AR대기</span>
          <span className="lip-cell is-scored">완료</span>
        </div>
      </div>
      <div className="lip-board-scroll">
        <table className="lip-board-table">
          <thead>
            <tr>
              <th scope="col">제품</th>
              {[1, 2, 3, 4, 5].map((id) => (
                <th key={id} scope="col">
                  관리자{id}
                </th>
              ))}
              <th scope="col">합산</th>
            </tr>
          </thead>
          <tbody>
            {items.map((product) => (
              <tr
                key={product.id}
                className={product.id === productId ? "is-active-row" : undefined}
              >
                <th scope="row">
                  <button
                    type="button"
                    className="lip-board-product"
                    onClick={() => onSelect(product.id, 1)}
                  >
                    <span className="lip-board-num">{product.sortOrder}</span>
                    <span className="lip-board-name">
                      {product.brand} {product.shade}
                    </span>
                  </button>
                </th>
                {product.slots.map((s) => {
                  const state = slotProgress(s);
                  const active = product.id === productId && s.raterId === raterId;
                  return (
                    <td key={s.raterId}>
                      <button
                        type="button"
                        className={`lip-cell is-${state}${active ? " is-active" : ""}`}
                        title={`${product.brand} ${product.shade} · ${s.label}`}
                        onClick={() => onSelect(product.id, s.raterId)}
                      >
                        {state === "scored" && s.naturalness?.mean != null
                          ? s.naturalness.mean.toFixed(1)
                          : progressLabel[state]}
                      </button>
                    </td>
                  );
                })}
                <td>
                  <span
                    className={`lip-agg-chip${product.aggregate.finalized ? " is-final" : ""}`}
                  >
                    {product.aggregate.scoredCount}/5
                    {product.aggregate.naturalnessMean != null
                      ? ` · ${product.aggregate.naturalnessMean}`
                      : ""}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SlotDetail({
  product,
  slot,
  onSaved,
  criteria,
  editable,
}: {
  product: LipEvalProduct;
  slot: LipEvalSlot;
  onSaved: (product: LipEvalProduct) => void;
  criteria?: NaturalnessCriteria;
  editable: boolean;
}) {
  const [bare, setBare] = useState<File | null>(null);
  const [real, setReal] = useState<File | null>(null);
  const [ar, setAr] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bareInput = useRef<HTMLInputElement>(null);
  const realInput = useRef<HTMLInputElement>(null);
  const arInput = useRef<HTMLInputElement>(null);

  async function saveRefs() {
    if (!bare || !real) {
      setError("맨입술과 실제립을 모두 선택하세요.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("bare", bare);
      form.append("real", real);
      onSaved(
        await apiForm<LipEvalProduct>(
          `/lip-eval/products/${product.id}/raters/${slot.raterId}/refs`,
          form,
        ),
      );
      setBare(null);
      setReal(null);
      if (bareInput.current) bareInput.current.value = "";
      if (realInput.current) realInput.current.value = "";
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : "저장에 실패했습니다.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function scoreAr() {
    if (!ar) {
      setError("AR 이미지를 선택하세요.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("ar", ar);
      onSaved(
        await apiForm<LipEvalProduct>(
          `/lip-eval/products/${product.id}/raters/${slot.raterId}/ar`,
          form,
        ),
      );
      setAr(null);
      if (arInput.current) arInput.current.value = "";
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : e instanceof Error
            ? e.message
            : "채점에 실패했습니다.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lip-detail">
      <div className="lip-detail-bar">
        <h3>
          {slot.label}
          <span className="badge">{slotStatus(slot)}</span>
        </h3>
        <p>
          {product.brand} {product.name} · {product.shade}
        </p>
      </div>

      {editable ? <div className="lip-upload-grid">
        <label className={bare ? "has-file" : undefined}>
          <span>화장 전 · 맨입술</span>
          <input
            ref={bareInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={(e) => setBare(e.target.files?.[0] || null)}
          />
          <small>{bare ? bare.name : "미선택"}</small>
        </label>
        <label className={real ? "has-file" : undefined}>
          <span>실제 바른 입술</span>
          <input
            ref={realInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={(e) => setReal(e.target.files?.[0] || null)}
          />
          <small>{real ? real.name : "미선택"}</small>
        </label>
        <label className={ar ? "has-file" : undefined}>
          <span>AR 적용</span>
          <input
            ref={arInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            disabled={!slot.readyForAr}
            onChange={(e) => setAr(e.target.files?.[0] || null)}
          />
          <small>
            {!slot.readyForAr ? "기준 저장 후" : ar ? ar.name : "미선택"}
          </small>
        </label>
      </div> : <p className="admin-hint">사진 저장과 채점은 관리자 계정에서 사용할 수 있습니다.</p>}

      {editable && <div className="lip-detail-actions">
        <button type="button" disabled={busy || !bare || !real} onClick={saveRefs}>
          기준 사진 저장
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy || !slot.readyForAr || !ar}
          onClick={scoreAr}
        >
          {busy ? "채점 중…" : "두 트랙 채점"}
        </button>
      </div>}

      <SlotImages slot={slot} />
      {error && <p className="form-error">{error}</p>}

      {slot.scored && slot.naturalness && slot.technical && (
        <div className="slot-scores">
          <div className="slot-score-row">
            <span>
              자연스러움 <strong>{slot.naturalness.mean}</strong>
              <small className="muted">
                {" "}
                · {slot.naturalness.criteriaVersion}
              </small>
            </span>
            <span>
              테크니컬 <strong>{verdictKo[slot.technical.overall]}</strong>
            </span>
          </div>
          <ul className="slot-nat-list">
            {(Object.keys(techNames) as TechMetricId[]).map((id) => {
              const score = slot.naturalness?.scores?.[id];
              const anchor = anchorFor(criteria, id, score);
              return (
                <li key={id}>
                  <span className="slot-nat-metric">
                    {techNames[id]} <strong>{score ?? "—"}</strong>
                  </span>
                  {anchor ? <span className="slot-nat-anchor">{anchor}</span> : null}
                </li>
              );
            })}
          </ul>
          {slot.naturalness.briefReason && (
            <p>
              <small>{slot.naturalness.briefReason}</small>
            </p>
          )}
          {slot.technical.items && (
            <p>
              <small>
                {(Object.keys(techNames) as TechMetricId[])
                  .map((k) => {
                    const item = slot.technical?.items?.[k];
                    if (!item || item.value == null) return null;
                    return `${techNames[k]} ${Number(item.value).toFixed(2)}`;
                  })
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function LipEvalPanel({ editable }: { editable: boolean }) {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["lip-eval-products"],
    queryFn: () => api<LipEvalProductList>("/lip-eval/products"),
  });
  const criteriaQ = useQuery({
    queryKey: ["lip-eval-naturalness-criteria"],
    queryFn: () =>
      api<NaturalnessCriteria>("/lip-eval/naturalness-criteria"),
  });
  const [productId, setProductId] = useState("");
  const [raterId, setRaterId] = useState(1);

  const items = list.data?.items || [];

  useEffect(() => {
    if (!items.length) return;
    if (!productId || !items.some((p) => p.id === productId)) {
      setProductId(items[0].id);
      setRaterId(1);
    }
  }, [items, productId]);

  const product = useMemo(
    () => items.find((p) => p.id === productId) || null,
    [items, productId],
  );
  const slot = useMemo(
    () => product?.slots.find((s) => s.raterId === raterId) || null,
    [product, raterId],
  );

  function onSaved(next: LipEvalProduct) {
    qc.setQueryData<LipEvalProductList>(["lip-eval-products"], (prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        items: prev.items.map((p) => (p.id === next.id ? { ...p, ...next } : p)),
      };
    });
    qc.invalidateQueries({ queryKey: ["lip-eval-products"] });
  }

  if (list.isPending) return <p>제품 패널을 불러오는 중…</p>;
  if (list.error)
    return (
      <div className="admin-request-error" role="alert">
        <p className="form-error">{list.error.message}</p>
        <button type="button" className="secondary" onClick={() => void list.refetch()}>다시 시도</button>
      </div>
    );

  function selectCell(nextProductId: string, nextRaterId: number) {
    setProductId(nextProductId);
    setRaterId(nextRaterId);
  }

  function exportCsv() {
    const stamp = new Date().toISOString().slice(0, 10);
    downloadTextFile(`lip-eval-panel-${stamp}.csv`, buildLipEvalCsv(items));
  }

  return (
    <section className="panel lip-eval-panel">
      <div className="lip-panel-head">
        <div className="lip-panel-title">
          <h2>제품 패널 평가</h2>
          <span className="lip-panel-meta">11 × 5</span>
        </div>
        <div className="lip-panel-tools">
          <label className="lip-product-select">
            <span>제품</span>
            <select
              value={productId}
              onChange={(e) => {
                setProductId(e.target.value);
                setRaterId(1);
              }}
            >
              {items.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.sortOrder}. {p.brand} {p.name} · {p.shade}
                  {p.aggregate.finalized
                    ? " · 확정"
                    : p.aggregate.scoredCount
                      ? ` · ${p.aggregate.scoredCount}/5`
                      : ""}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="secondary lip-export-btn"
            disabled={!items.length}
            onClick={exportCsv}
          >
            CSV 내보내기
          </button>
        </div>
      </div>

      <NaturalnessCriteriaGuide
        criteria={criteriaQ.data}
        pending={criteriaQ.isPending}
        error={
          criteriaQ.error instanceof Error ? criteriaQ.error.message : null
        }
      />

      {items.length > 0 && (
        <ProgressBoard
          items={items}
          productId={productId}
          raterId={raterId}
          onSelect={selectCell}
        />
      )}

      {product && slot && (
        <div className="lip-workspace">
          <div className="lip-rater-col">
            {product.slots.map((s) => (
              <MiniSlot
                key={s.raterId}
                slot={s}
                active={s.raterId === raterId}
                onSelect={() => setRaterId(s.raterId)}
              />
            ))}
            <AggregateCard aggregate={product.aggregate} />
          </div>
          <SlotDetail
            key={`${product.id}:${slot.raterId}`}
            product={product}
            slot={slot}
            onSaved={onSaved}
            criteria={criteriaQ.data}
            editable={editable}
          />
        </div>
      )}
    </section>
  );
}
