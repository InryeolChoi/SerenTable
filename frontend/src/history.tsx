import { useEffect, useState } from "react";
import type { EventSlot } from "./api";
import { CheckInSection } from "./attendance";
import { show, SlotSummary } from "./events";
import { FeedbackSection } from "./feedback";
import { ReportSection } from "./safety";
import { message, Notice, useScopedApi } from "./ui";

// Participant history page (feedback-contract.md). T4 owns the history list and
// recommendations; each table card composes the T1/T2/T3 sections for that table.
export type HistoryTable = {
  table_id: string;
  event_slot_id: string;
  region: { code: string; name: string };
  date: string;
  starts_at: string;
  ends_at: string;
  checked_in: boolean;
  feedback_submitted: boolean;
  check_in_open: boolean;
  feedback_open: boolean;
};
type Recommendation = { event_slot: EventSlot; reason: string };

export function TableActions({ table }: { table: HistoryTable }) {
  return (
    <>
      {table.check_in_open || table.checked_in ? (
        <CheckInSection tableId={table.table_id} checkedIn={table.checked_in} />
      ) : (
        !table.feedback_open && (
          <p className="small muted">
            체크인은 모임 시작 30분 전부터 종료 시각까지 할 수 있습니다.
          </p>
        )
      )}
      <FeedbackSection tableId={table.table_id} />
      <ReportSection tableId={table.table_id} />
    </>
  );
}

function status(table: HistoryTable) {
  if (!table.feedback_open) return table.checked_in ? "체크인 완료" : "참가 예정";
  return table.feedback_submitted ? "평가 완료" : "평가를 기다리고 있어요";
}

// Same-tab navigation without a prop: the app shell follows popstate.
function goApply() {
  window.history.pushState({}, "", "/participant/apply");
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
}

export function HistoryPage() {
  const request = useScopedApi();
  const [tables, setTables] = useState<HistoryTable[] | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    void Promise.all([
      request<{ tables: HistoryTable[] }>("/api/me/history"),
      request<{ recommendations: Recommendation[] }>("/api/me/recommendations"),
    ])
      .then(([history, next]) => {
        setTables(history.tables);
        setRecommendations(next.recommendations);
      })
      .catch((caught: unknown) => setError(message(caught)));
  }, []);
  return (
    <section className="page-stack">
      <h1>참가 이력</h1>
      <p className="lead">
        확정된 모임의 체크인, 비공개 평가, 신고·차단을 이곳에서 할 수 있습니다.
        평가는 다른 참가자에게 공개되지 않으며, 남기지 않아도 다음 신청은 가능합니다.
      </p>
      {error && <Notice error>{error}</Notice>}
      {!error && tables === null && <p className="muted">불러오는 중입니다.</p>}
      {tables?.length === 0 && <Notice>아직 확정된 모임이 없습니다.</Notice>}
      {tables?.map((table) => (
        <article className="panel" key={table.table_id}>
          <h2>
            {show(table.starts_at)} · {table.region.name}
          </h2>
          <p className="small muted">{status(table)}</p>
          <TableActions table={table} />
        </article>
      ))}
      <h2>다음 모임 추천</h2>
      {recommendations?.length === 0 && <Notice>지금 모집 중인 회차가 없습니다.</Notice>}
      {recommendations?.map((item) => (
        <article className="panel" key={item.event_slot.id}>
          <SlotSummary slot={item.event_slot} />
          <p>{item.reason}</p>
          <a
            href="/participant/apply"
            onClick={(event) => {
              event.preventDefault();
              goApply();
            }}
          >
            이 회차 신청하러 가기
          </a>
        </article>
      ))}
    </section>
  );
}
