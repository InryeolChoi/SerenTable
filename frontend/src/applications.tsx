import { useEffect, useState } from "react";
import {
  ApiError,
  type Application,
  type EventSlot,
  type MatchRun,
  type ProductCode,
} from "./api";
import { show, SlotSummary } from "./events";
import { SlotBrowser } from "./slot-browser";
import {
  NoShowNotice,
  PaymentPanel,
  paymentOpen,
  paymentSummary,
  ProductChoice,
  RefundNotice,
  useCatalog,
} from "./payments";
import { message, Notice, useScopedApi } from "./ui";
import { TableExplanationView, MemberExplanationView } from "./matching-explanations";

// PRD §7.4 순서: 신청한 날짜·지역과 가까운 일정부터 보여 준다(서버가 이 순서로 정렬).
const preferenceLabels = {
  same_date_same_region: "신청한 날짜·지역",
  same_date_other_region: "신청한 날짜 · 다른 지역",
  other_date_same_region: "다른 날짜 · 신청한 지역",
  other_date_other_region: "다른 날짜·지역",
} as const;

const stateLabels: Record<Application["state"], string> = {
  DRAFT: "작성 중",
  SUBMITTED: "신청 완료",
  CANCELED: "신청 취소됨",
};
const conflictMessages: Record<string, string> = {
  profile_incomplete:
    "프로필 필수 항목이 비어 있습니다. 프로필을 완성한 뒤 다시 제출해 주세요. 선택은 유지됩니다.",
  consent_incomplete:
    "필수 동의가 완료되지 않았습니다. 동의 화면에서 확인한 뒤 다시 제출해 주세요. 선택은 유지됩니다.",
  application_slot_duplicate:
    "선택한 회차 중 이미 다른 신청에 포함된 회차가 있습니다. 내 신청을 확인해 주세요.",
  request_key_reused:
    "이전 제출과 선택이 달라졌습니다. 선택을 다시 확인한 뒤 제출해 주세요.",
  application_cancel_closed: "후보 회차의 신청 마감이 지나 취소할 수 없습니다.",
  application_not_found: "신청을 찾을 수 없습니다.",
};
function applicationError(error: unknown) {
  if (error instanceof ApiError && error.status === 409)
    return conflictMessages[String(error.detail)] ?? message(error);
  if (
    error instanceof ApiError &&
    error.status === 422 &&
    Array.isArray(error.detail) &&
    error.detail.some((item) => item?.type === "slot_not_recruiting")
  )
    return "선택한 회차 중 마감되었거나 없어진 회차가 있습니다. 목록을 새로 불러왔으니 다시 선택해 주세요.";
  return message(error);
}
const newKey = () => crypto.randomUUID();

/** Pick candidates on /participant/apply, confirm on /participant/apply/review. */
export function ApplyPage({
  path,
  navigate,
}: {
  path: string;
  navigate: (path: string) => void;
}) {
  const request = useScopedApi();
  const [slots, setSlots] = useState<EventSlot[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  // One key per reviewed selection: a retried submit is recognized as the same request.
  const [requestKey, setRequestKey] = useState(newKey);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<Application | null>(null);
  const [product, setProduct] = useState<ProductCode | null>(null);
  const { catalog } = useCatalog();
  async function load() {
    setLoading(true);
    try {
      const open = (
        await request<{ event_slots: EventSlot[] }>("/api/event-slots")
      ).event_slots;
      setSlots(open);
      setChosen((current) =>
        current.filter((id) => open.some((slot) => slot.id === id)),
      );
    } catch (error) {
      setError(message(error));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  function toggle(id: string, on: boolean) {
    setError("");
    setDone(null);
    setRequestKey(newKey());
    setChosen(on ? [...chosen, id] : chosen.filter((value) => value !== id));
  }
  async function submit() {
    setPending(true);
    setError("");
    try {
      const result = await request<{ application: Application }>(
        "/api/me/applications",
        {
          method: "POST",
          body: JSON.stringify({
            request_key: requestKey,
            event_slot_ids: chosen,
          }),
        },
      );
      setDone(result.application);
      setChosen([]);
      setRequestKey(newKey());
    } catch (error) {
      setError(applicationError(error));
      if (error instanceof ApiError && error.status === 422) {
        setRequestKey(newKey());
        await load();
      }
    } finally {
      setPending(false);
    }
  }
  const selected = slots.filter((slot) => chosen.includes(slot.id));
  if (path === "/participant/apply/review")
    return (
      <section className="narrow">
        <h1>신청 내용 확인</h1>
        <p className="lead">
          선택한 날짜·시간·지역 후보를 확인하고 제출해 주세요.
        </p>
        {error && <Notice error>{error}</Notice>}
        {done ? (
          <>
            <Notice>
              신청을 제출했습니다. 후보 {done.candidates.length}개 회차 · 상태{" "}
              {stateLabels[done.state]}
              {done.payment_required
                ? " · 이용권 결제가 필요합니다."
                : " · 보유한 멤버십으로 결제 없이 신청이 완료되었습니다."}
            </Notice>
            {done.payment_required && (
              <PaymentPanel application={done} initialProduct={product} />
            )}
            <button onClick={() => navigate("/participant")}>
              내 신청 보기
            </button>
          </>
        ) : loading ? (
          <Notice>회차를 확인하고 있습니다…</Notice>
        ) : selected.length ? (
          <>
            <ul className="participants" aria-label="선택한 후보 회차">
              {selected.map((slot) => (
                <li key={slot.id}>
                  <SlotSummary slot={slot} />
                </li>
              ))}
            </ul>
            {catalog && (
              <ProductChoice
                products={catalog.products}
                value={product}
                disabled={pending}
                onChange={setProduct}
              />
            )}
            <p className="notice">
              제출은 결제가 아닙니다. 제출 후 모의 결제 단계에서 선택한 이용권을
              결제합니다. 유효한 멤버십 기간이 후보 회차를 모두 포함하면 결제
              없이 처리됩니다. 여러 후보를 골라도 모든 회차에 각각 참가하는 것은
              아니며, 매칭 시각이 이른 회차부터 처리해 한 신청은 한 테이블에만
              확정됩니다.
            </p>
            <RefundNotice />
            <NoShowNotice />
            <div className="actions">
              <button
                className="primary"
                disabled={pending}
                onClick={() => void submit()}
              >
                {pending ? "제출 중…" : "신청 제출"}
              </button>
              <button
                disabled={pending}
                onClick={() => navigate("/participant/apply")}
              >
                선택 수정
              </button>
            </div>
          </>
        ) : (
          <>
            <p>선택한 후보 회차가 없습니다.</p>
            <button onClick={() => navigate("/participant/apply")}>
              회차 선택으로 돌아가기
            </button>
          </>
        )}
      </section>
    );
  return (
    <section className="narrow">
      <h1>일정 신청</h1>
      <p className="lead">
        참가 가능한 회차를 모두 골라 주세요. 시각은 서울 기준입니다.
      </p>
      {error && <Notice error>{error}</Notice>}
      {loading ? (
        <Notice>회차를 확인하고 있습니다…</Notice>
      ) : slots.length ? (
        <fieldset>
          <legend>후보 회차</legend>
          <p className="muted small">
            고른 회차만 후보로 저장합니다. 날짜와 지역을 따로 조합하지 않습니다.
          </p>
          <SlotBrowser
            slots={slots}
            listLabel="선택 가능한 후보 회차"
            renderSlot={(slot) => (
              <label className="check" key={slot.id}>
                <input
                  type="checkbox"
                  checked={chosen.includes(slot.id)}
                  onChange={(e) => toggle(slot.id, e.target.checked)}
                />
                <span>
                  <SlotSummary slot={slot} />
                </span>
              </label>
            )}
          />
        </fieldset>
      ) : (
        <p>현재 모집 중인 회차가 없습니다.</p>
      )}
      <div className="actions">
        <button
          className="primary"
          disabled={!chosen.length}
          onClick={() => navigate("/participant/apply/review")}
        >
          선택 확인
        </button>
        <button onClick={() => void load()}>목록 새로고침</button>
      </div>
    </section>
  );
}

/**
 * The matching axis (STA-01/02), kept apart from application and payment states. A stored
 * run decides it; eligibility is the API's per-slot decision (paid by the slot close) and
 * only fills in "waiting" for slots whose matching time has not arrived.
 */
const matchingLabels: Record<string, string> = {
  CONFIRMED: "매칭 확정",
  ALTERNATIVE_OFFERED: "매칭 실패 · 대안 선택 대기",
  NO_MATCH: "매칭 실패",
  EXCEPTION: "매칭 예외",
};
/** Why a run left an application out; U03/U04/U05 wording is still provisional. */
const matchingReasons: Record<string, string> = {
  not_enough_eligible: "함께 앉을 인원이 부족합니다",
  capacity: "회차 정원이 부족합니다",
  unknown_age: "출생연도가 없어 나이 조건을 확인할 수 없습니다",
  age_gap: "나이 차이 조건을 맞출 수 없습니다",
  no_valid_table: "조건에 맞는 테이블을 만들 수 없습니다",
  overlapping_confirmation: "같은 시간대의 다른 식탁에 이미 확정되었습니다",
  no_qualifying_table:
    "조건과 최소 매칭 점수를 함께 만족하는 테이블을 찾지 못했습니다",
  pass_held: "미사용 1회권 보관 완료 · 새 신청에서 재사용할 수 있습니다",
  mock_refunded: "원결제 금액 전액 모의 환불 완료",
  mock_refund_failed: "모의 환불 실패 · 운영자 재시도 대기(이용권 예약 유지)",
  membership_held: "이번 신청 종료 · 멤버십 기간은 유지됩니다",
  runner_error: "자동 매칭 오류로 운영자 확인이 필요합니다",
  stale_generation: "중단된 실행을 정리했습니다",
};
function matchingSummary(application: Application) {
  if (application.state === "CANCELED") return "신청 취소로 매칭 제외";
  const matching = application.matching;
  if (matching?.state === "CONFIRMED") {
    const slot = application.candidates.find(
      (candidate) => candidate.id === matching.event_slot_id,
    );
    const table = matching.table
      ? ` · 같은 테이블 ${matching.table.member_count}명`
      : "";
    return `매칭 확정${slot ? ` · ${show(slot.starts_at)}` : ""}${table}`;
  }
  // A slot that has not matched yet can still seat this application, so a run that left it
  // out in an earlier slot does not settle it.
  const now = Date.now();
  const awaiting = application.candidates.filter(
    (slot) =>
      application.matching_eligible_slot_ids.includes(slot.id) &&
      Date.parse(slot.matches_at) > now,
  );
  if (awaiting.length)
    return `매칭 대기 · 매칭 예정 ${[...new Set(awaiting.map((slot) => show(slot.matches_at)))].join(", ")}`;
  if (matching && matching.state !== "WAITING" && matching.state !== "MATCHING")
    return `${matchingLabels[matching.state] ?? matching.state}${
      matching.reason_code
        ? ` · ${matchingReasons[matching.reason_code] ?? matching.reason_code}`
        : ""
    }`;
  if (paymentOpen(application)) return "결제 필요 · 미결제 시 매칭 제외";
  return "미결제로 매칭 제외";
}

function ApplicationItem({
  application,
  action,
}: {
  application: Application;
  action?: React.ReactNode;
}) {
  return (
    <li>
      <p>
        <strong>신청: {stateLabels[application.state]}</strong>
        {application.participant && ` · ${application.participant.login_id}`}
      </p>
      <p className="small">
        결제: {paymentSummary(application)}
        {application.refund_state === "REFUND_AVAILABLE" &&
          " · 환불 가능 (모의)"}
      </p>
      <p className="small">매칭: {matchingSummary(application)}</p>
      {application.matching?.state === "CONFIRMED" &&
        application.matching.table && (
          <p className="small">
            같은 식탁 소개:{" "}
            {application.matching.table.members
              .map((member) => member.display_name)
              .join(", ")}
          </p>
        )}
      <ul className="candidates">
        {application.candidates.map((slot) => (
          <li key={slot.id}>
            <SlotSummary slot={slot} />
            {!slot.live && (
              <span className="small muted">이전 후보 · 종료됨</span>
            )}
          </li>
        ))}
      </ul>
      {!!application.resolutions?.length && (
        <details>
          <summary>실패 해결 이력</summary>
          <ul>
            {application.resolutions.map((item) => (
              <li key={item.id}>
                {show(item.created_at)} ·{" "}
                {item.action === "TRANSFER"
                  ? "일정 이동 동의·처리 완료"
                  : item.action === "HOLD"
                    ? "이용권 보관·신청 종료"
                    : item.refund_status === "FAILED"
                      ? "모의 환불 실패 · 운영자 재시도 대기(이용권 예약 유지)"
                      : "전액 모의 환불 완료"}
                {!!item.refund_events?.length && (
                  <ol aria-label="모의 환불 처리 이력">
                    {item.refund_events.map((event) => (
                      <li key={event.state}>
                        {event.state === "REFUND_REQUESTED"
                          ? "환불 요청"
                          : event.state === "REFUND_PROCESSING"
                            ? "환불 처리 중"
                            : "환불 완료"}
                        {` · ${event.amount_krw.toLocaleString("ko-KR")}원 · ${show(event.created_at)}`}
                      </li>
                    ))}
                  </ol>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {action}
    </li>
  );
}

/** Explicit choices; the server revalidates the failure token and current coverage. */
function AlternativeSlots({
  application,
  onResolved,
}: {
  application: Application;
  onResolved: () => Promise<void>;
}) {
  const request = useScopedApi();
  const [result, setResult] = useState<{
    alternatives: (EventSlot & { preference?: keyof typeof preferenceLabels })[];
    pending_candidates: EventSlot[];
    failure_run_id: string | null;
    refund_state: "REFUND_AVAILABLE" | null;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  // Keep a key for an unchanged choice after transport failure; refresh on a new choice.
  const [attempt, setAttempt] = useState<{
    choice: string;
    key: string;
  } | null>(null);
  async function load() {
    setLoading(true);
    setError("");
    try {
      setResult(
        await request(`/api/me/applications/${application.id}/alternatives`),
      );
    } catch (error) {
      setError(
        error instanceof ApiError && error.status === 409
          ? "신청 상태가 변경되었습니다. 신청 상태를 새로 확인해 주세요."
          : message(error),
      );
    } finally {
      setLoading(false);
    }
  }
  async function choose(
    action: "TRANSFER" | "HOLD" | "REFUND",
    slot: string | null = null,
  ) {
    if (!result?.failure_run_id) return;
    const choice = `${result.failure_run_id}:${action}:${slot}`;
    const key = attempt?.choice === choice ? attempt.key : crypto.randomUUID();
    setAttempt({ choice, key });
    setLoading(true);
    setError("");
    try {
      const response = await request<{
        resolution: { refund_status?: "FAILED" | "SUCCEEDED" | null };
      }>(`/api/me/applications/${application.id}/resolutions`, {
        method: "POST",
        body: JSON.stringify({
          request_key: key,
          action,
          event_slot_id: slot,
          failure_run_id: result.failure_run_id,
        }),
      });
      setSuccess(
        action === "TRANSFER"
          ? "선택한 일정으로 이동했습니다. 자동 매칭을 기다려 주세요."
          : action === "REFUND"
            ? response.resolution.refund_status === "FAILED"
              ? "모의 환불을 완료하지 못했습니다. 이용권은 예약 상태로 보존되며 운영자가 재시도합니다. 실제 입출금은 없습니다."
              : "전액 모의 환불이 완료되었습니다. 실제 입출금은 없습니다."
            : "이번 신청을 종료하고 이용권을 보관했습니다.",
      );
      setResult(null);
      await onResolved();
    } catch (error) {
      setError(
        error instanceof ApiError && error.status === 409
          ? "신청 상태 또는 일정 자격이 변경되었습니다. 신청 상태를 새로 확인해 주세요."
          : message(error),
      );
    } finally {
      setLoading(false);
    }
  }
  const single = application.coverage?.entitlement.kind === "SINGLE";
  return (
    <section aria-label="대체 일정">
      <button disabled={loading} onClick={() => void load()}>
        {loading ? "처리 중…" : "다른 일정 확인"}
      </button>
      {error && <Notice error>{error}</Notice>}
      {success && <Notice>{success}</Notice>}
      {result &&
        (result.pending_candidates.length ? (
          <>
            <p>
              선택한 후보 회차의 매칭이 아직 남아 있습니다. 기존 신청으로 계속
              기다립니다.
            </p>
            <ul className="candidates">
              {result.pending_candidates.map((slot) => (
                <li key={slot.id}>
                  <SlotSummary slot={slot} />
                </li>
              ))}
            </ul>
          </>
        ) : (
          <>
            <p className="small muted">
              조회만으로 일정이나 결제가 변경되지 않습니다. 일정을 선택하면 해당
              날짜·지역 이동에 동의하며 원결제를 유지합니다.
            </p>
            {result.alternatives.length ? (
              <ul className="candidates" aria-label="모집 중인 다른 일정">
                {result.alternatives.map((slot) => (
                  <li key={slot.id}>
                    {slot.preference && (
                      <p className="small muted">
                        {preferenceLabels[slot.preference]}
                      </p>
                    )}
                    <SlotSummary slot={slot} />
                    <button
                      disabled={loading}
                      onClick={() => void choose("TRANSFER", slot.id)}
                    >
                      이 일정으로 이동
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p>현재 이용권으로 이동 가능한 모집 일정이 없습니다.</p>
            )}
            {result.refund_state && (
              <p className="small">환불 가능 · 미사용 1회권 원금 전액 (모의)</p>
            )}
            <div className="actions">
              <button disabled={loading} onClick={() => void choose("HOLD")}>
                {single ? "1회권 보관" : "이번 신청 종료·멤버십 유지"}
              </button>
              {single && (
                <button
                  disabled={loading}
                  onClick={() => void choose("REFUND")}
                >
                  1회권 전액 모의 환불
                </button>
              )}
            </div>
            <p className="small muted">
              {single
                ? "미사용 1회권은 만료 없이 보관 후 새 신청에서 재사용하거나 전액 모의 환불할 수 있습니다."
                : "최종 실패 신청당 멤버십을 7일 한 번 연장합니다. 같은 신청의 재이동에는 추가 연장하지 않으며 금액 환불은 준비 중입니다."}
            </p>
          </>
        ))}
    </section>
  );
}

/** The participant's own applications with status; shown on the home page. */
export function MyApplications({
  navigate,
  onChanged,
}: {
  navigate: (path: string) => void;
  onChanged?: () => void;
}) {
  const request = useScopedApi();
  const [applications, setApplications] = useState<Application[] | null>(null);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  async function load() {
    setError("");
    try {
      setApplications(
        (await request<{ applications: Application[] }>("/api/me/applications"))
          .applications,
      );
    } catch (error) {
      setError(message(error));
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function cancel(id: string) {
    setPending(id);
    setError("");
    try {
      const { application } = await request<{ application: Application }>(
        `/api/me/applications/${id}/cancel`,
        { method: "POST" },
      );
      setApplications(
        (current) =>
          current?.map((item) => (item.id === id ? application : item)) ?? null,
      );
    } catch (error) {
      setError(applicationError(error));
    } finally {
      setPending("");
    }
  }
  return (
    <>
      <h2>내 신청</h2>
      {error && <Notice error>{error}</Notice>}
      {!applications ? (
        !error && <Notice>신청 상태를 확인하고 있습니다…</Notice>
      ) : applications.length ? (
        <ul className="participants" aria-label="내 신청">
          {applications.map((application) => (
            <ApplicationItem
              key={application.id}
              application={application}
              action={
                <div className="actions">
                  {paymentOpen(application) && (
                    <button
                      className="primary"
                      onClick={() =>
                        navigate(`/participant/payment/${application.id}`)
                      }
                    >
                      결제하기
                    </button>
                  )}
                  {application.state === "SUBMITTED" &&
                    application.candidates.some((slot) => slot.live) &&
                    application.candidates
                      .filter((slot) => slot.live)
                      .every((slot) => slot.recruiting) && (
                      <button
                        disabled={pending === application.id}
                        onClick={() => void cancel(application.id)}
                      >
                        {pending === application.id ? "취소 중…" : "신청 취소"}
                      </button>
                    )}
                  {(application.matching?.state === "ALTERNATIVE_OFFERED" ||
                    (application.matching?.state === "NO_MATCH" &&
                      ![
                        "overlapping_confirmation",
                        "pass_held",
                        "mock_refunded",
                        "mock_refund_failed",
                        "membership_held",
                      ].includes(application.matching.reason_code ?? ""))) && (
                    <AlternativeSlots
                      application={application}
                      onResolved={async () => {
                        await load();
                        onChanged?.();
                      }}
                    />
                  )}
                </div>
              }
            />
          ))}
        </ul>
      ) : (
        <p>아직 제출한 신청이 없습니다.</p>
      )}
      <details className="policy-disclosure">
        <summary>신청·결제 안내</summary>
        <p className="small muted">
          신청 취소는 후보 회차 중 가장 이른 신청 마감 전까지 가능하며 자동
          환불이 아닙니다. 시스템 매칭 최종 실패의 미사용 1회권은 마감 제한 없이
          전액 모의 환불할 수 있습니다. 결제는 가장 이른 신청 마감 전까지
          가능하며 미결제 신청은 매칭에서 제외됩니다.
        </p>
        <NoShowNotice />
      </details>
      <div className="actions">
        <button onClick={() => void load()}>신청 상태 새로고침</button>
        <button
          className="primary"
          onClick={() => navigate("/participant/apply")}
        >
          일정 신청
        </button>
      </div>
    </>
  );
}

const runLabels: Record<MatchRun["state"], string> = {
  RUNNING: "실행 중",
  SUCCEEDED: "완료",
  FAILED: "실패",
  ABANDONED: "중단됨(정리)",
};
const outcomeLabels: Record<string, string> = {
  SEATED: "확정",
  UNSEATED: "미배정",
  EXCEPTION: "예외",
};

/**
 * Read-only matching history (PRD 이야기 47). Matching has no operator start and no
 * manual edit: this screen only explains what the runner already decided (MAT-01).
 */
function MatchHistory() {
  const request = useScopedApi();
  const [runs, setRuns] = useState<MatchRun[] | null>(null);
  const [error, setError] = useState("");
  async function load() {
    setError("");
    try {
      setRuns(
        (await request<{ match_runs: MatchRun[] }>("/api/admin/match-runs"))
          .match_runs,
      );
    } catch (error) {
      setError(message(error));
    }
  }
  useEffect(() => {
    void load();
  }, []);
  return (
    <section>
      <h2>매칭 이력</h2>
      <p className="lead">
        회차별 자동 매칭 실행 세대와 결과입니다. 읽기 전용이며 운영자가 매칭을
        시작하거나 결과를 바꿀 수 없습니다.
      </p>
      {error && <Notice error>{error}</Notice>}
      {!runs ? (
        !error && <Notice>매칭 이력을 확인하고 있습니다…</Notice>
      ) : runs.length ? (
        <ul className="participants" aria-label="매칭 이력 목록">
          {runs.map((run) => (
            <li key={run.id}>
              <p>
                <strong>
                  {run.event_slot.region.name} ·{" "}
                  {show(run.event_slot.starts_at)}
                </strong>{" "}
                · {run.attempt}번째 실행 · {runLabels[run.state] ?? run.state}
              </p>
              <p className="small">
                확정 {run.seated_count}명 · 규칙 {run.rule_version}
                {run.reason_code
                  ? ` · ${matchingReasons[run.reason_code] ?? run.reason_code}`
                  : ""}
              </p>
              {run.policy && (
                <p className="small">
                  최소 점수 {Number(run.policy.min_score)} · 정책{" "}
                  {run.policy.version}
                  {run.search_complete === false
                    ? " · 탐색 시간 상한 도달"
                    : ""}
                </p>
              )}
              {run.tables.length > 0 && (
                <ul className="candidates" aria-label="테이블 점수">
                  {run.tables.map((table) => (
                    <li key={table.id}>
                      {table.member_count}명 · 테이블 점수 {table.score ?? "미기록"}
                      <TableExplanationView explanation={table.explanation} components={table.components} year={Number(run.event_slot.starts_at.slice(0, 4))} />
                    </li>
                  ))}
                </ul>
              )}
              {run.members.length > 0 && (
                <ul className="candidates">
                  {run.members.map((member) => (
                    <li key={member.application_id}>
                      {member.login_id} ·{" "}
                      {outcomeLabels[member.outcome] ?? member.outcome}
                      {member.reason_code
                        ? ` (${matchingReasons[member.reason_code] ?? member.reason_code})`
                        : ""}
                      {member.outcome === "SEATED" && <MemberExplanationView explanation={member.explanation} />}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p>아직 매칭 실행이 없습니다.</p>
      )}
      <button onClick={() => void load()}>매칭 이력 새로고침</button>
    </section>
  );
}

export function AdminApplicationsPage() {
  const request = useScopedApi();
  const [applications, setApplications] = useState<Application[] | null>(null);
  const [error, setError] = useState("");
  async function load() {
    setError("");
    try {
      setApplications(
        (
          await request<{ applications: Application[] }>(
            "/api/admin/applications",
          )
        ).applications,
      );
    } catch (error) {
      setError(message(error));
    }
  }
  useEffect(() => {
    void load();
  }, []);
  return (
    <>
      <section>
        <h1>신청 현황</h1>
        <p className="lead">
          참가자 신청·후보 회차·모의 결제 상태를 조회합니다. 읽기 전용입니다.
        </p>
        {error && <Notice error>{error}</Notice>}
        {!applications ? (
          !error && <Notice>신청을 확인하고 있습니다…</Notice>
        ) : applications.length ? (
          <ul className="participants" aria-label="신청 목록">
            {applications.map((application) => (
              <ApplicationItem key={application.id} application={application} />
            ))}
          </ul>
        ) : (
          <p>아직 신청이 없습니다.</p>
        )}
        <button onClick={() => void load()}>목록 새로고침</button>
      </section>
      <MatchHistory />
    </>
  );
}
