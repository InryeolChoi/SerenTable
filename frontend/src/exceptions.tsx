import { useEffect, useState, type FormEvent } from "react";
import { show } from "./events";
import { message, Notice, useScopedApi } from "./ui";

// Ticket B 예외 통합 처리 owns this file (operator-console-contract.md).
// Resolving only records the operator's note; it never re-runs or approves a normal flow.
type ExceptionState = "OPEN" | "RESOLVED";
type ExceptionItem = {
  kind: "gathering" | "alternative_overdue" | "mock_refund";
  retryable?: boolean;
  amount_krw?: number;
  id: string;
  category: string;
  event_slot_id: string | null;
  dining_table_id: string | null;
  reason_code: string;
  occurred_at: string;
  state: ExceptionState;
  resolution_note: string | null;
  resolved_by: string | null;
  resolvable: boolean;
};

const CATEGORIES: Record<string, string> = {
  MOCK_REFUND: "모의 환불 실패",
  VENUE: "식당 배정 부족",
  PUSH_DELIVERY: "푸시 발송 반복 실패",
  MATCHING_ALTERNATIVE: "대안 미응답(회차 시작 경과)",
};
const REASONS: Record<string, string> = {
  no_verified_inventory: "확인된 식당 재고 없음",
  push_attempts_exhausted: "3회 발송 실패",
  mock_refund_storage_failed: "모의 환불 저장 실패",
};
const STATES: Record<ExceptionState, string> = { OPEN: "처리 대기", RESOLVED: "처리 완료" };

function RefundRetryForm({ item, onDone }: { item: ExceptionItem; onDone: () => void }) {
  const request = useScopedApi();
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function retry() {
    if (pending) return;
    setPending(true);
    setError("");
    try {
      const result = await request<{ refund: { state: "FAILED" | "SUCCEEDED" } }>(
        `/api/admin/mock-refunds/${item.id}/retry`,
        { method: "POST", body: JSON.stringify({ request_key: requestKey }) },
      );
      // A received FAILED result is a recorded attempt; a transport failure retains its key.
      setRequestKey(crypto.randomUUID());
      if (result.refund.state === "FAILED") setError("모의 환불이 다시 실패했습니다. 이용권 예약을 유지합니다.");
      onDone();
    } catch (caught) {
      setError(message(caught));
    } finally { setPending(false); }
  }
  return <div>
    <p>원결제 전액 {item.amount_krw?.toLocaleString("ko-KR")}원 · 실제 입출금 없음</p>
    <p className="muted">환불 완료 전까지 이용권 예약을 유지합니다.</p>
    <button type="button" disabled={pending} onClick={() => void retry()}>
      {pending ? "재시도 중…" : "모의 환불 재시도"}
    </button>
    {error && <Notice error>{error}</Notice>}
  </div>;
}

function ResolveForm({ item, onDone }: { item: ExceptionItem; onDone: () => void }) {
  const request = useScopedApi();
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!note.trim() || pending) return;
    setPending(true);
    setError("");
    try {
      await request(`/api/admin/exceptions/${item.kind}/${item.id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ note: note.trim() }),
      });
      onDone();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(false);
    }
  }
  return (
    <form onSubmit={submit}>
      <label>
        처리 메모(500자 이내, 연락처 등 개인정보 제외)
        <textarea maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
      <div className="actions">
        <button type="submit" disabled={pending || !note.trim()}>
          처리 결과 기록
        </button>
      </div>
      {error && <Notice error>{error}</Notice>}
    </form>
  );
}

export function ExceptionsSection() {
  const request = useScopedApi();
  const [state, setState] = useState<ExceptionState>("OPEN");
  const [items, setItems] = useState<ExceptionItem[] | null>(null);
  const [error, setError] = useState("");
  function load() {
    setError("");
    return request<{ exceptions: ExceptionItem[] }>(`/api/admin/exceptions?state=${state}`)
      .then((result) => setItems(result.exceptions))
      .catch((caught: unknown) => setError(message(caught)));
  }
  useEffect(() => {
    void load();
  }, [state]);
  return (
    <section>
      <h2>예외 처리</h2>
      <p className="muted">
        일반 예외의 처리 결과는 확인 기록만 남깁니다. 모의 환불 실패는 별도 재시도할 수 있으며 실제 입출금은 없습니다.
      </p>
      <label>
        상태
        <select
          value={state}
          onChange={(event) => setState(event.target.value as ExceptionState)}
        >
          <option value="OPEN">처리 대기</option>
          <option value="RESOLVED">처리 완료</option>
        </select>
      </label>
      {error && <Notice error>{error}</Notice>}
      {items && items.length === 0 && !error && <Notice>해당 상태의 예외가 없습니다.</Notice>}
      {items?.map((item) => (
        <article className="panel" key={`${item.kind}:${item.id}`}>
          <h3>
            {CATEGORIES[item.category] ?? item.category} · {STATES[item.state]}
          </h3>
          <p>
            원인 {REASONS[item.reason_code] ?? item.reason_code}
            {item.event_slot_id && <> · 회차 {item.event_slot_id.slice(0, 8)}</>}
          </p>
          <p className="muted">발생 {show(item.occurred_at)}</p>
          {item.resolution_note && <p>처리 메모: {item.resolution_note}</p>}
          {item.kind === "mock_refund" && item.retryable ? (
            <RefundRetryForm item={item} onDone={() => void load()} />
          ) : item.resolvable ? (
            <ResolveForm item={item} onDone={() => void load()} />
          ) : (
            item.state === "OPEN" && (
              <p className="muted">참가자 선택을 기다리는 항목으로 조회만 할 수 있습니다.</p>
            )
          )}
        </article>
      ))}
    </section>
  );
}
