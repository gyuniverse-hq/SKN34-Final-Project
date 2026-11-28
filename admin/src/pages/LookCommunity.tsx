import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, apiBlob } from "../api/client";

type ReportedPost = { id: string; title: string; description: string; hidden: boolean; reasons: string[]; votes: number };

function ReviewPhoto({ id }: { id: string }) {
  const [url, setUrl] = useState<string>();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    let created: string | undefined;
    void apiBlob(`/look-community/${id}/photo`).then(value => {
      if (!active) { URL.revokeObjectURL(value); return; }
      created = value;
      setUrl(value);
    }).catch(() => { if (active) setFailed(true); });
    return () => {
      active = false;
      if (created) URL.revokeObjectURL(created);
    };
  }, [id]);
  return url ? <img src={url} alt="신고 게시물 사진" style={{ display: "block", maxWidth: "100%", maxHeight: 360, borderRadius: 12 }} />
    : <p>{failed ? "사진을 불러오지 못했습니다." : "사진을 불러오는 중입니다."}</p>;
}

export default function LookCommunity() {
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const posts = useQuery({ queryKey: ["reported-looks", offset], queryFn: () => api<ReportedPost[]>(`/look-community?offset=${offset}`) });
  const review = useMutation({
    mutationFn: ({ id, hidden }: Pick<ReportedPost, "id" | "hidden">) => api<Pick<ReportedPost, "hidden">>(`/look-community/${id}`, {
      method: "PATCH", body: JSON.stringify({ hidden }),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["reported-looks"] }),
  });
  return <>
    <h1>룩 게시물 신고</h1>
    {posts.isPending && <p role="status">신고 내역을 불러오는 중입니다.</p>}
    {posts.isError && <p role="alert">신고 내역을 불러오지 못했습니다. <button onClick={() => void posts.refetch()}>다시 시도</button></p>}
    {review.isError && <p role="alert">게시 상태를 변경하지 못했습니다.</p>}
    {posts.data?.length === 0 && <p>이 페이지에 신고된 게시물이 없습니다.</p>}
    {posts.data?.map(post => (
      <article key={post.id} className="panel">
        <h2>{post.title}</h2>
        <p>{post.hidden ? "숨김" : "공개"} · 추천 {post.votes}개</p>
        {post.description && <p>{post.description}</p>}
        <details>
          <summary>신고 사유 및 사진 확인</summary>
          <ul>{post.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>
          <PhotoOnRequest id={post.id} />
        </details>
        <button disabled={review.isPending} onClick={() => {
          if (window.confirm(post.hidden ? "게시물을 다시 공개할까요?" : "피드와 상세 화면에서 게시물을 숨길까요?")) {
            review.mutate({ id: post.id, hidden: !post.hidden });
          }
        }}>{post.hidden ? "다시 공개" : "게시물 숨기기"}</button>
      </article>
    ))}
    {offset > 0 && <button onClick={() => setOffset(offset - 20)}>이전</button>}
    {posts.data?.length === 20 && <button onClick={() => setOffset(offset + 20)}>다음</button>}
  </>;
}

function PhotoOnRequest({ id }: { id: string }) {
  const [opened, setOpened] = useState(false);
  return opened ? <ReviewPhoto id={id} /> : <button onClick={() => setOpened(true)}>사진 보기</button>;
}
