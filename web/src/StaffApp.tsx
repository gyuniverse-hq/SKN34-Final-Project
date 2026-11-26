import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Staff } from "@admin/api/types";
import { ApiError, api, supabase } from "./api";
import { signOut } from "./auth";
import staffStyles from "../../admin/src/style.css?inline";

import { AdminWorkspace } from "@admin/Workspace";

/** Admin workspace on the same origin as shopping (/admin/*). */
export function StaffApp() {
  useEffect(() => {
    const style = document.createElement("style");
    style.textContent = staffStyles;
    document.head.append(style);
    return () => style.remove();
  }, []);

  const me = useQuery({
    queryKey: ["staff-me"],
    queryFn: () => api<Staff>("/api/admin/me"),
    retry: false,
  });

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 403) {
      window.location.replace("/");
    }
  }, [me.error]);

  if (me.isPending) return <p role="status">직원 권한을 확인하고 있습니다…</p>;
  if (me.error instanceof ApiError && me.error.status === 403)
    return <p role="status">쇼핑으로 이동 중…</p>;
  if (me.error || !me.data)
    return (
      <main className="login auth-screen">
        <h1>서버에 연결할 수 없습니다</h1>
        <p role="alert">관리자 API와 설정을 확인해 주세요.</p>
        <button type="button" onClick={() => void me.refetch()}>
          다시 시도
        </button>
        <button type="button" onClick={() => void signOut()}>
          로그아웃
        </button>
      </main>
    );

  return <AdminWorkspace staff={me.data} basePath="/admin" onSignOut={async () => {
    const result = await supabase?.auth.signOut();
    if (result?.error) throw result.error;
    window.location.assign("/login");
  }} />;
}
