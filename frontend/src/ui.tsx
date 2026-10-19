import { useEffect, useRef } from "react";
import { api } from "./api";

// 더보기에서 처음 안내 카드를 다시 여는 신호. 화면 간 결합을 피하려 이벤트로 전달한다.
export const GUIDE_EVENT = "guide-open";
export function message(error: unknown) {
  return error instanceof Error ? error.message : "요청을 완료하지 못했습니다.";
}
export function Notice({
  children,
  error = false,
}: {
  children: React.ReactNode;
  error?: boolean;
}) {
  return (
    <p
      className={error ? "notice error" : "notice"}
      role={error ? "alert" : "status"}
    >
      {children}
    </p>
  );
}
// 화면을 떠난 뒤 이전 계정의 응답이 새 화면의 입력을 덮어쓰지 않도록 취소한다.
export function useScopedApi() {
  const controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);
  return function request<T>(path: string, init: RequestInit = {}) {
    return api<T>(path, { ...init, signal: controller.current.signal });
  };
}
