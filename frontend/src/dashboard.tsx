import { useEffect, useState } from "react";
import type { EventSlot } from "./api";
import { show } from "./events";
import { message, Notice, useScopedApi } from "./ui";

// Ticket A 운영 대시보드 owns this file (operator-console-contract.md).
// Read-only counts per slot: no approval or start action lives here.
type Counts = Record<string, number>;
type SlotDashboard = {
  event_slot: EventSlot;
  applications: Counts;
  payments: Counts;
  push: Counts;
  matching: {
    run_state: string | null;
    attempt: number | null;
    confirmed_count: number;
    table_count: number;
    alternative_offered_count: number;
    success_rate: number | null;
  };
  gathering: {
    venue_assigned: number;
    venue_pending: number;
    room_count: number;
  };
  attendance: {
    check_in_count: number;
    no_show_candidate_count: number;
    feedback_submitted: number;
    feedback_eligible: number;
    feedback_rate: number | null;
  };
  open_report_count: number;
  failed_refund_count: number;
  condition_conflict_count: number;
  open_exception_count: number;
};

const LABELS: Record<string, string> = {
  DRAFT: "작성 중",
  SUBMITTED: "제출",
  CANCELED: "취소",
  PENDING: "대기",
  PAID: "완료",
  FAILED: "실패",
  REFUNDED: "환불",
  SENT: "발송",
  UNAVAILABLE: "발송 불가",
};
const RUN_STATES: Record<string, string> = {
  RUNNING: "실행 중",
  SUCCEEDED: "완료",
  FAILED: "실패",
  ABANDONED: "중단",
};

function breakdown(counts: Counts) {
  return Object.entries(counts)
    .map(([state, count]) => `${LABELS[state] ?? state} ${count}`)
    .join(" · ");
}

function rate(value: number | null) {
  return value === null ? "집계 전" : `${Math.round(value * 1000) / 10}%`;
}

function SlotCard({ item }: { item: SlotDashboard }) {
  const { matching, gathering, attendance } = item;
  const run = matching.run_state
    ? `${RUN_STATES[matching.run_state] ?? matching.run_state} (${matching.attempt}회차)`
    : "실행 전";
  const rows: [string, string][] = [
    ["신청", breakdown(item.applications)],
    ["결제", breakdown(item.payments)],
    ["매칭", run],
    [
      "확정 인원·테이블",
      `${matching.confirmed_count}명 · ${matching.table_count}개`,
    ],
    ["매칭 성공률", rate(matching.success_rate)],
    ["대안 선택 대기", `${matching.alternative_offered_count}건`],
    [
      "식당 배정",
      `완료 ${gathering.venue_assigned} · 대기 ${gathering.venue_pending}`,
    ],
    ["단체방", `${gathering.room_count}개`],
    ["푸시 발송", breakdown(item.push)],
    [
      "체크인·노쇼 후보",
      `${attendance.check_in_count}명 · ${attendance.no_show_candidate_count}명`,
    ],
    [
      "피드백 제출률",
      `${rate(attendance.feedback_rate)} (${attendance.feedback_submitted}/${attendance.feedback_eligible})`,
    ],
    ["미처리 신고", `${item.open_report_count}건`],
    ["식사 조건 충돌(재검토)", `${item.condition_conflict_count}건`],
    ["자동 환불 실패", `${item.failed_refund_count}건`],
    ["열린 예외(전체)", `${item.open_exception_count}건`],
  ];
  return (
    <article className="panel">
      <h3>
        {item.event_slot.region.name} · {show(item.event_slot.starts_at)}
      </h3>
      <dl className="status-grid">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

export function DashboardSection() {
  const request = useScopedApi();
  const [slots, setSlots] = useState<SlotDashboard[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void request<{ slots: SlotDashboard[] }>("/api/admin/dashboard")
      .then((data) => {
        if (active) setSlots(data.slots);
      })
      .catch((caught: unknown) => {
        if (active) setError(message(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reload]);
  const visible = selected
    ? slots.filter((item) => item.event_slot.id === selected)
    : slots;
  return (
    <section>
      <h2>회차별 현황</h2>
      <p className="small muted">
        자동 처리 결과를 숫자로만 보여 줍니다. 승인하거나 실행하는 기능은
        없습니다.
      </p>
      <div className="dashboard-toolbar">
        <label>
          회차
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">전체 회차</option>
            {slots.map((item) => (
              <option key={item.event_slot.id} value={item.event_slot.id}>
                {item.event_slot.region.name} ·{" "}
                {show(item.event_slot.starts_at)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => setReload((value) => value + 1)}
          disabled={loading}
        >
          새로 고침
        </button>
      </div>
      {loading && <Notice>현황을 불러오고 있습니다.</Notice>}
      {error && <Notice error>{error}</Notice>}
      {!loading && !error && slots.length === 0 && (
        <Notice>등록된 회차가 없습니다.</Notice>
      )}
      {visible.map((item) => (
        <SlotCard key={item.event_slot.id} item={item} />
      ))}
    </section>
  );
}
