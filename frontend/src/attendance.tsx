import { useEffect, useState } from "react";
import { ApiError } from "./api";
import { show } from "./events";
import { message, Notice, useScopedApi } from "./ui";

// T1: participant check-in (FDB-01) and operator no-show candidates (U15).
type CheckIn = { table_id: string; checked_in_at: string };
type Candidate = {
  table_id: string;
  user_id: string;
  display_name: string;
  region_name: string;
  starts_at: string;
  ends_at: string;
};
// 표시명이 겹치면 조치 대상이 화면에서 유일하게 정해지지 않는다. 계정 ID는 노출하지 않고
// 이미 응답에 있는 user_id 앞자리만 구분자로 쓴다(tests/test_attendance.py:127).
const disambiguate = (candidate: Candidate) => candidate.user_id.slice(0, 8);
type Decision = "CONFIRMED_NO_SHOW" | "EXCUSED";

function checkInError(error: unknown) {
  if (error instanceof ApiError && error.status === 409)
    return "체크인은 모임 시작 30분 전부터 종료 시각까지 할 수 있습니다.";
  if (error instanceof ApiError && error.status === 404)
    return "확정된 모임에서만 체크인할 수 있습니다.";
  return message(error);
}

export function CheckInSection({
  tableId,
  checkedIn = false,
}: {
  tableId: string;
  // Already checked in according to the history list; the time is not repeated there.
  checkedIn?: boolean;
}) {
  const request = useScopedApi();
  const [state, setState] = useState<CheckIn | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function submit() {
    setPending(true);
    setError("");
    try {
      const result = await request<{ check_in: CheckIn }>(
        `/api/me/tables/${tableId}/check-in`,
        { method: "POST" },
      );
      setState(result.check_in);
    } catch (error) {
      setError(checkInError(error));
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="actions">
      {state ? (
        <Notice>체크인 완료 · {show(state.checked_in_at)}</Notice>
      ) : checkedIn ? (
        <Notice>체크인 완료</Notice>
      ) : (
        <button type="button" className="primary" onClick={() => void submit()} disabled={pending}>
          {pending ? "체크인 중" : "도착 체크인"}
        </button>
      )}
      {error && <Notice error>{error}</Notice>}
    </div>
  );
}

const decisionLabel: Record<Decision, string> = {
  CONFIRMED_NO_SHOW: "노쇼 확정",
  EXCUSED: "사유 인정(면제)",
};

export function NoShowSection() {
  const request = useScopedApi();
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");
  const [pending, setPending] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void request<{ candidates: Candidate[] }>("/api/admin/no-show-candidates")
      .then((data) => {
        if (active) setCandidates(data.candidates);
      })
      .catch((error: unknown) => {
        if (active) setError(message(error));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reload]);
  async function review(candidate: Candidate, decision: Decision) {
    const key = `${candidate.table_id}/${candidate.user_id}`;
    setPending(key);
    setError("");
    setResult("");
    try {
      await request(`/api/admin/no-show-candidates/${key}`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      setResult(
        `${candidate.display_name} (참가자 ${disambiguate(candidate)}): ${decisionLabel[decision]}로 기록했습니다.`,
      );
    } catch (error) {
      setError(
        error instanceof ApiError && error.status === 409
          ? "이미 다른 결정으로 검토된 참가자입니다."
          : message(error),
      );
    } finally {
      setPending("");
      setReload((value) => value + 1);
    }
  }
  // 같은 표시명이 둘 이상이면 어느 행인지 알 수 없으므로 그 행들에만 구분자를 붙인다.
  const nameCounts = candidates.reduce<Record<string, number>>(
    (counts, candidate) => {
      counts[candidate.display_name] = (counts[candidate.display_name] ?? 0) + 1;
      return counts;
    },
    {},
  );
  return (
    <section>
      <h2>노쇼 후보</h2>
      <p className="small muted">
        종료 시각까지 체크인하지 않은 확정 참가자입니다. 확인 후 노쇼 확정 또는 면제를 한 번 기록합니다.
      </p>
      {loading && <Notice>노쇼 후보를 불러오고 있습니다.</Notice>}
      {error && <Notice error>{error}</Notice>}
      {result && <Notice>{result}</Notice>}
      {!loading && !error && candidates.length === 0 && <Notice>검토할 노쇼 후보가 없습니다.</Notice>}
      <ul className="participants">
        {candidates.map((candidate) => {
          const key = `${candidate.table_id}/${candidate.user_id}`;
          return (
            <li key={key}>
              <strong>{candidate.display_name}</strong>
              {nameCounts[candidate.display_name] > 1 && (
                <span className="small muted"> 참가자 {disambiguate(candidate)}</span>
              )}
              <span className="small muted">
                {" "}· {show(candidate.starts_at)} · {candidate.region_name}
              </span>
              <div className="actions">
              {(Object.keys(decisionLabel) as Decision[]).map((decision) => (
                <button
                  key={decision}
                  type="button"
                  disabled={pending === key}
                  onClick={() => void review(candidate, decision)}
                >
                  {decisionLabel[decision]}
                </button>
              ))}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
