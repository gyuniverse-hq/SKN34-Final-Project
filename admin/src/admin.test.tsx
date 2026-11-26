import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { AccessGate, Workspace } from "./App";
import { OrderActions } from "./pages/Commerce";
import { LocalConsent } from "./LocalConsent";
import {
  compareRuns,
  comparisonVerdict,
  Unmeasured,
} from "./pages/Evaluations";
import type { EvalRun, Order, Staff } from "./api/types";
import fixture from "./api/demo-eval.json";
const viewer: Staff = {
  userId: "v",
  email: "viewer@example.test",
  role: "viewer",
};
const order: Order = {
  id: "o",
  userId: "member…",
  amountKRW: 1000,
  orderName: "립",
  status: "paid",
  createdAt: null,
  paidAt: null,
  paymentKey: null,
  nextStatuses: ["preparing", "canceled"],
};
describe("권한과 운영 화면", () => {
  it("로컬 회원 등록은 필수 동의를 직접 선택해야 진행한다", async () => {
    const register = vi.fn().mockResolvedValue(undefined);
    render(<LocalConsent onRegister={register} />);
    const button = screen.getByRole("button", {
      name: "동의하고 로컬 회원 등록",
    });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /이용약관/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /개인정보/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /만 14세/ }));
    fireEvent.click(button);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "로컬 회원 등록이 끝났습니다",
    );
    expect(register).toHaveBeenCalledOnce();
  });
  it("로그인 전에는 앱형 이메일·비밀번호 로그인을 표시한다", () => {
    render(
      <AccessGate ready signedIn={false} forbidden={false}>
        비공개
      </AccessGate>,
    );
    expect(screen.getByLabelText("이메일")).toBeInTheDocument();
    expect(screen.getByLabelText("비밀번호")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "로그인" })).toBeInTheDocument();
    expect(screen.queryByText("비공개")).not.toBeInTheDocument();
  });
  it("직원이 아니면 소비자 웹으로 보내거나 로컬 등록을 안내한다", () => {
    render(
      <AccessGate ready signedIn forbidden>
        비공개
      </AccessGate>,
    );
    const redirected = screen.queryByRole("status")?.textContent?.includes(
      "소비자 웹",
    );
    const localSetup = screen.queryByRole("heading", {
      name: "로컬 테스트 계정 등록",
    });
    expect(!!redirected || !!localSetup).toBe(true);
  });
  it("조회자에게 상태 변경 버튼을 숨긴다", () => {
    render(
      <OrderActions
        order={order}
        staff={viewer}
        busy={false}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it("허용된 다음 상태와 사유 확인을 거쳐 취소한다", () => {
    const change = vi.fn();
    render(
      <OrderActions
        order={order}
        staff={{ ...viewer, role: "admin" }}
        busy={false}
        onChange={change}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "배송 완료로 변경" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "취소로 변경" }));
    expect(screen.getByRole("button", { name: "취소 확정" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("취소 사유"), {
      target: { value: "시연 취소" },
    });
    fireEvent.click(screen.getByRole("button", { name: "취소 확정" }));
    expect(change).toHaveBeenCalledWith("canceled", "시연 취소");
  });
  it("조회자의 감사 로그 경로를 대시보드로 돌린다", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { enabled: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/audit"]}>
          <Workspace staff={viewer} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(
      screen.queryByRole("link", { name: "감사 로그" }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "운영 대시보드" }),
    ).toBeInTheDocument();
  });
  it("미측정 항목을 숨기지 않는다", () => {
    render(<Unmeasured items={["색 재현", "피팅 안정성"]} />);
    expect(screen.getAllByText("미측정")).toHaveLength(2);
    expect(screen.getByText("색 재현")).toBeInTheDocument();
  });
  it("서로 다른 벤치마크를 비교하지 않는다", () => {
    const run = {
      ...fixture,
      id: "one",
      createdAt: "2026-11-12",
    } as unknown as EvalRun;
    expect(compareRuns(run, { ...run, benchmarkSha256: "other" })).toEqual({
      compatible: false,
      delta: null,
    });
  });
  it("짝 차이 신뢰구간이 있을 때만 변화를 판정한다", () => {
    const previous = {
      ...fixture,
      id: "old",
      createdAt: "2026-11-11",
    } as unknown as EvalRun;
    const current = {
      ...previous,
      id: "new",
      summaryJson: {
        ...previous.summaryJson,
        pairedComparison: {
          previousRendererCommit: previous.rendererCommit,
          method: "face-paired-bootstrap" as const,
          totalDelta: { estimate: 0.3, low: 0.1, high: 0.5, n: 19 },
        },
      },
    };
    expect(comparisonVerdict(previous, current)).toBe("improved");
    expect(comparisonVerdict(previous, previous)).toBeNull();
  });
});
