import { useEffect, useState } from "react";
import {
  ApiError,
  type Application,
  type EventSlot,
  type ProductCode,
} from "./api";
import { show, SlotSummary } from "./events";
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
              아니며, 후보 간 배정 규칙은 아직 확정되지 않았습니다.
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
          {slots.map((slot) => (
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
          ))}
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
 * The matching axis (STA-01/02), kept apart from application and payment states. No
 * matching has run yet, so it only tells waiting from excluded; eligibility is the API's
 * per-slot decision (paid by the slot close).
 */
function matchingSummary(application: Application) {
  if (application.state === "CANCELED") return "신청 취소로 매칭 제외";
  const eligible = application.candidates.filter((slot) =>
    application.matching_eligible_slot_ids.includes(slot.id),
  );
  if (eligible.length)
    return `매칭 대기 (WAITING) · 매칭 예정 ${[...new Set(eligible.map((slot) => show(slot.matches_at)))].join(", ")}`;
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
      <p className="small">결제: {paymentSummary(application)}</p>
      <p className="small">매칭: {matchingSummary(application)}</p>
      <ul className="candidates">
        {application.candidates.map((slot) => (
          <li key={slot.id}>
            <SlotSummary slot={slot} />
          </li>
        ))}
      </ul>
      {action}
    </li>
  );
}

/** The participant's own applications with status; shown on the home page. */
export function MyApplications({
  navigate,
}: {
  navigate: (path: string) => void;
}) {
  const request = useScopedApi();
  const [applications, setApplications] = useState<Application[] | null>(null);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  async function load() {
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
                    application.candidates.every((slot) => slot.recruiting) && (
                      <button
                        disabled={pending === application.id}
                        onClick={() => void cancel(application.id)}
                      >
                        {pending === application.id ? "취소 중…" : "신청 취소"}
                      </button>
                    )}
                </div>
              }
            />
          ))}
        </ul>
      ) : (
        <p>아직 제출한 신청이 없습니다.</p>
      )}
      <p className="small muted">
        신청 취소는 후보 회차 중 가장 이른 신청 마감 전까지 가능하며 자동 환불이
        아닙니다. 현행 기준 화요일 24:00 이후 환불 불가, 세부 환불 정책 미정.
        결제는 가장 이른 신청 마감 전까지 가능하며 미결제 신청은 매칭에서
        제외됩니다.
      </p>
      <NoShowNotice />
      <button onClick={() => navigate("/participant/apply")}>일정 신청</button>
    </>
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
  );
}
