import { useEffect, useState, type FormEvent } from "react";
import { show } from "./events";
import { message, Notice, useScopedApi } from "./ui";

// Ticket C 감사 이력 owns this file (operator-console-contract.md).
type AuditEntry = {
  id: number;
  actor: { login_id: string } | null;
  action: string;
  target_type: string;
  target_id: string;
  reason: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
};

const ACTIONS: Record<string, string> = {
  "event_slot.create": "회차 생성",
  "venue_inventory.create": "식당 재고 등록",
  "venue_food.approve": "음식 적합성 확인",
  "no_show.review": "노쇼 판정",
  "report.review": "신고 검토",
  "sanction.create": "제재 기록",
};

const TARGETS: Record<string, string> = {
  event_slot: "회차",
  venue_inventory: "식당 재고",
  dining_table: "테이블",
  participant: "참가자",
  safety_report: "신고",
};

function summary(state: Record<string, unknown> | null) {
  if (!state) return "없음";
  return Object.entries(state)
    .map(([key, value]) => `${key}=${value === null ? "-" : String(value)}`)
    .join(", ");
}

export function AuditSection() {
  const request = useScopedApi();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [targetType, setTargetType] = useState("");
  const [targetId, setTargetId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  function load(type: string, id: string) {
    const params = new URLSearchParams({ limit: "50" });
    if (type) params.set("target_type", type);
    if (id.trim()) params.set("target_id", id.trim());
    setLoading(true);
    setError("");
    return request<{ audit: AuditEntry[] }>(`/api/admin/audit?${params}`)
      .then((result) => setEntries(result.audit))
      .catch((caught: unknown) => setError(message(caught)))
      .finally(() => setLoading(false));
  }
  useEffect(() => {
    void load("", "");
  }, []);
  function submit(event: FormEvent) {
    event.preventDefault();
    void load(targetType, targetId);
  }
  return (
    <section className="panel">
      <h2>감사 이력</h2>
      <p className="muted">
        운영자의 주요 변경을 최신순으로 보여 줍니다. 행위자는 로그인 id로만 표시하며 연락처·신고
        원문은 기록하지 않습니다.
      </p>
      <form className="actions" onSubmit={submit}>
        <label>
          대상 종류
          <select value={targetType} onChange={(event) => setTargetType(event.target.value)}>
            <option value="">전체</option>
            {Object.entries(TARGETS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          대상 id
          <input
            value={targetId}
            maxLength={200}
            onChange={(event) => setTargetId(event.target.value)}
          />
        </label>
        <button type="submit" disabled={loading}>
          조회
        </button>
      </form>
      {error && <Notice error>{error}</Notice>}
      {!loading && !error && entries.length === 0 && <Notice>기록된 변경이 없습니다.</Notice>}
      {entries.length > 0 && (
        <ul>
          {entries.map((entry) => (
            <li key={entry.id}>
              <strong>{ACTIONS[entry.action] ?? entry.action}</strong> ·{" "}
              {entry.actor?.login_id ?? "시스템"} · {show(entry.created_at)}
              <br />
              <span className="muted">
                {TARGETS[entry.target_type] ?? entry.target_type} {entry.target_id}
              </span>
              {entry.reason && <p>사유: {entry.reason}</p>}
              <p className="muted">
                이전: {summary(entry.before)} → 이후: {summary(entry.after)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
