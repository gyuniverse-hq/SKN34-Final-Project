import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("./api/client", () => ({
  api: vi.fn(),
  ApiError: class ApiError extends Error {},
  isDemo: false,
  localAccountSetup: true,
  registerLocalConsent: vi.fn(),
  supabase: null,
}));

import { AccessGate } from "./App";

it("로컬 로그인 후 권한이 없으면 회원 등록 화면을 보여준다", async () => {
  render(<AccessGate ready signedIn forbidden>비공개</AccessGate>);
  expect(
    await screen.findByRole("heading", {
      level: 2,
      name: "로컬 테스트 계정 등록",
    }),
  ).toBeInTheDocument();
  expect(await screen.findAllByRole("checkbox")).toHaveLength(3);
});
