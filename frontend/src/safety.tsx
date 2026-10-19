import { useEffect, useState, type FormEvent } from "react";
import { NoShowSection } from "./attendance";
import { show } from "./events";
import { message, Notice, useScopedApi } from "./ui";

// T3 owns this file: reports/blocks (SAF-01) and operator review/sanctions (SAF-02).
type ReportState = "OPEN" | "CONFIRMED" | "DISMISSED";
type Mate = { id: string; display_name: string };
type OwnReport = {
  id: string;
  reported: Mate;
  reason_code: string;
  state: ReportState;
  created_at: string;
};
type SafetyView = { tablemates: Mate[]; reports: OwnReport[] };
type Person = { id: string; login_id: string; display_name: string | null };
type AdminReport = {
  id: string;
  dining_table_id: string | null;
  reporter: Person;
  reported: Person;
  reason_code: string;
  detail: string | null;
  state: ReportState;
  created_at: string;
  separation_active: boolean;
};
type SanctionKind = "WARNING" | "SUSPENSION" | "PERMANENT_BAN";
type Sanction = {
  id: string;
  user: Person;
  kind: SanctionKind;
  report_id: string | null;
  ends_at: string | null;
  created_at: string;
  restricting: boolean;
};

const REASONS: Record<string, string> = {
  harassment: "괴롭힘·불쾌한 접근",
  offensive_language: "모욕적인 발언",
  unsafe_behavior: "위험한 행동",
  privacy_violation: "개인정보 침해",
  other: "기타",
};
const REPORT_STATES: Record<ReportState, string> = {
  OPEN: "검토 대기",
  CONFIRMED: "검토 완료(확인)",
  DISMISSED: "검토 완료",
};
const KINDS: Record<SanctionKind, string> = {
  WARNING: "경고",
  SUSPENSION: "참가 제한",
  PERMANENT_BAN: "영구 제한",
};

function personName(person: Person) {
  return `${person.display_name ?? "참가자"} (${person.login_id})`;
}

export function ReportSection({ tableId }: { tableId: string }) {
  const request = useScopedApi();
  const [view, setView] = useState<SafetyView | null>(null);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("harassment");
  const [detail, setDetail] = useState("");
  const [blocked, setBlocked] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const path = `/api/me/tables/${tableId}/safety`;
  function load() {
    return request<SafetyView>(path).then((result) => {
      setView(result);
      setTarget((previous) => previous || result.tablemates[0]?.id || "");
    });
  }
  useEffect(() => {
    void load().catch((caught: unknown) => setError(message(caught)));
  }, [tableId]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!target || pending) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      await request(`/api/me/reports`, {
        method: "POST",
        body: JSON.stringify({
          dining_table_id: tableId,
          reported_id: target,
          reason_code: reason,
          detail: detail.trim() || null,
        }),
      });
      setDetail("");
      setNotice("신고를 접수했습니다. 이 참가자와는 다음 매칭에서 같은 식탁에 배정되지 않습니다.");
      await load();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(false);
    }
  }
  async function block() {
    if (!target || pending) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      await request(`/api/me/blocks`, {
        method: "POST",
        body: JSON.stringify({ dining_table_id: tableId, blocked_id: target }),
      });
      setBlocked((previous) => [...new Set([...previous, target])]);
      setNotice("차단했습니다. 이 참가자와는 다음 매칭에서 같은 식탁에 배정되지 않습니다.");
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(false);
    }
  }
  if (!view) return error ? <Notice error>{error}</Notice> : null;
  if (view.tablemates.length === 0) return null;
  return (
    <details className="panel">
      <summary>신고·차단</summary>
      <p className="muted">
        신고와 차단 사실은 상대에게 알리지 않습니다. 이미 확정된 모임은 바뀌지 않습니다.
      </p>
      <form onSubmit={submit}>
        <label>
          대상 참가자
          <select value={target} onChange={(event) => setTarget(event.target.value)}>
            {view.tablemates.map((mate) => (
              <option key={mate.id} value={mate.id}>
                {mate.display_name}
                {blocked.includes(mate.id) ? " (차단함)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          신고 사유
          <select value={reason} onChange={(event) => setReason(event.target.value)}>
            {Object.entries(REASONS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          상세 내용(선택, 1000자 이내)
          <textarea
            maxLength={1000}
            value={detail}
            onChange={(event) => setDetail(event.target.value)}
          />
        </label>
        <div className="actions">
          <button type="submit" disabled={pending}>
            신고하기
          </button>
          <button type="button" disabled={pending} onClick={() => void block()}>
            차단하기
          </button>
        </div>
      </form>
      {notice && <Notice>{notice}</Notice>}
      {error && <Notice error>{error}</Notice>}
      {view.reports.length > 0 && (
        <ul>
          {view.reports.map((item) => (
            <li key={item.id}>
              {item.reported.display_name} · {REASONS[item.reason_code] ?? item.reason_code} ·{" "}
              {REPORT_STATES[item.state]}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function ReportReview({ onChanged }: { onChanged: () => void }) {
  const request = useScopedApi();
  const [reports, setReports] = useState<AdminReport[]>([]);
  const [error, setError] = useState("");
  const [pending, setPending] = useState("");
  function load() {
    return request<{ reports: AdminReport[] }>("/api/admin/reports")
      .then((result) => setReports(result.reports))
      .catch((caught: unknown) => setError(message(caught)));
  }
  useEffect(() => {
    void load();
  }, []);
  async function decide(id: string, decision: "CONFIRMED" | "DISMISSED") {
    setPending(id);
    setError("");
    try {
      await request(`/api/admin/reports/${id}/review`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      await load();
      onChanged();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending("");
    }
  }
  return (
    <section>
      <h2>신고 검토</h2>
      <p className="muted">
        신고 접수 즉시 두 사람은 다음 매칭에서 분리됩니다. 확인·기각은 제재 판단에 쓰이며 기각해도
        분리는 유지됩니다. 기각된 신고만 사유를 남기고 분리를 해제할 수 있습니다(차단·비선호는 유지).
      </p>
      {error && <Notice error>{error}</Notice>}
      {reports.length === 0 && !error && <Notice>접수된 신고가 없습니다.</Notice>}
      {reports.map((item) => (
        <article className="panel" key={item.id}>
          <h3>
            {REASONS[item.reason_code] ?? item.reason_code} · {REPORT_STATES[item.state]}
          </h3>
          <p>
            신고자 {personName(item.reporter)} → 대상 {personName(item.reported)}
          </p>
          <p className="muted">접수 {show(item.created_at)}</p>
          {item.detail && <p>{item.detail}</p>}
          {item.state === "OPEN" && (
            <div className="actions">
              <button disabled={pending === item.id} onClick={() => void decide(item.id, "CONFIRMED")}>
                신고 확인
              </button>
              <button disabled={pending === item.id} onClick={() => void decide(item.id, "DISMISSED")}>
                기각
              </button>
            </div>
          )}
          {item.state === "CONFIRMED" && <SanctionForm report={item} />}
          {item.state === "DISMISSED" &&
            (item.separation_active ? (
              <ReleaseSeparation report={item} onReleased={() => void load()} />
            ) : (
              <p className="muted">매칭 분리 해제됨</p>
            ))}
        </article>
      ))}
    </section>
  );
}

function ReleaseSeparation({ report, onReleased }: { report: AdminReport; onReleased: () => void }) {
  const request = useScopedApi();
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      await request(`/api/admin/reports/${report.id}/release-separation`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      onReleased();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(false);
    }
  }
  return (
    <form onSubmit={submit}>
      <label>
        매칭 분리 해제 사유(필수, 500자 이내)
        <input
          required
          maxLength={500}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <button type="submit" disabled={pending || !reason.trim()}>
        매칭 분리 해제
      </button>
      {error && <Notice error>{error}</Notice>}
    </form>
  );
}

function SanctionForm({ report }: { report: AdminReport }) {
  const request = useScopedApi();
  const [kind, setKind] = useState<SanctionKind>("WARNING");
  const [endsAt, setEndsAt] = useState("");
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    setResult("");
    try {
      await request("/api/admin/sanctions", {
        method: "POST",
        body: JSON.stringify({
          user_id: report.reported.id,
          kind,
          report_id: report.id,
          ends_at: kind === "SUSPENSION" && endsAt ? new Date(endsAt).toISOString() : null,
        }),
      });
      setResult(`${KINDS[kind]} 조치를 기록했습니다.`);
      window.dispatchEvent(new Event("sanctions-changed"));
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(false);
    }
  }
  return (
    <form onSubmit={submit}>
      <label>
        제재
        <select value={kind} onChange={(event) => setKind(event.target.value as SanctionKind)}>
          {Object.entries(KINDS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {kind === "SUSPENSION" && (
        <label>
          제한 종료 시각
          <input
            type="datetime-local"
            required
            value={endsAt}
            onChange={(event) => setEndsAt(event.target.value)}
          />
        </label>
      )}
      <button type="submit" disabled={pending}>
        제재 기록
      </button>
      {result && <Notice>{result}</Notice>}
      {error && <Notice error>{error}</Notice>}
    </form>
  );
}

function SanctionList({ version }: { version: number }) {
  const request = useScopedApi();
  const [sanctions, setSanctions] = useState<Sanction[]>([]);
  const [error, setError] = useState("");
  const [changed, setChanged] = useState(0);
  useEffect(() => {
    const refresh = () => setChanged((value) => value + 1);
    window.addEventListener("sanctions-changed", refresh);
    return () => window.removeEventListener("sanctions-changed", refresh);
  }, []);
  useEffect(() => {
    void request<{ sanctions: Sanction[] }>("/api/admin/sanctions")
      .then((result) => setSanctions(result.sanctions))
      .catch((caught: unknown) => setError(message(caught)));
  }, [version, changed]);
  return (
    <section>
      <h2>제재 기록</h2>
      {error && <Notice error>{error}</Notice>}
      {sanctions.length === 0 && !error && <Notice>기록된 제재가 없습니다.</Notice>}
      {sanctions.length > 0 && (
        <ul>
          {sanctions.map((item) => (
            <li key={item.id}>
              {personName(item.user)} · {KINDS[item.kind]}
              {item.ends_at ? ` · ${show(item.ends_at)}까지` : ""} ·{" "}
              {item.restricting ? "신청 제한 중" : "신청 제한 없음"}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AdminSafetyPage() {
  const [version, setVersion] = useState(0);
  return (
    <section className="panel">
      <h1>안전·노쇼 관리</h1>
      <ReportReview onChanged={() => setVersion((value) => value + 1)} />
      <SanctionList version={version} />
      <NoShowSection />
    </section>
  );
}
