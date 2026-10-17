import { useEffect, useState } from "react";
import {
  ApiError,
  type Application,
  type Catalog,
  type Entitlement,
  type Payment,
  type Product,
  type ProductCode,
} from "./api";
import { message, Notice, useScopedApi } from "./ui";

const won = (amount: number) => `${amount.toLocaleString("ko-KR")}원`;
const day = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "long",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const productNames: Record<ProductCode, string> = {
  single: "1회권",
  membership_1m: "멤버십 1개월",
  membership_3m: "멤버십 3개월",
  membership_6m: "멤버십 6개월",
};
const conflictMessages: Record<string, string> = {
  payment_already_paid:
    "이미 결제가 완료된 신청입니다. 내 신청을 확인해 주세요.",
  entitlement_already_covers:
    "보유한 멤버십이 이 신청의 후보 회차를 모두 포함해 결제가 필요하지 않습니다.",
  membership_too_short:
    "선택한 멤버십은 후보 회차가 시작되기 전에 끝납니다. 더 긴 이용권을 선택해 주세요.",
  application_not_payable: "취소된 신청은 결제할 수 없습니다.",
  payment_closed:
    "후보 회차의 신청 마감이 지나 결제할 수 없습니다. 미결제 신청은 매칭에서 제외됩니다.",
  application_not_found: "신청을 찾을 수 없습니다.",
  request_key_reused:
    "이전 결제 요청과 선택이 달라졌습니다. 다시 확인한 뒤 결제해 주세요.",
};
function paymentError(error: unknown) {
  if (error instanceof ApiError && error.status === 409)
    return conflictMessages[String(error.detail)] ?? message(error);
  return message(error);
}
const newKey = () => crypto.randomUUID();

/** FAQ Q1 current rule plus the still-undecided details (U04), shown before paying. */
export function RefundNotice() {
  return (
    <p className="small muted">
      환불 안내: 현행 기준 화요일 24:00 이후 환불 불가. 시스템 최종 매칭 실패의 미사용 1회권은 시간 제한 없이 전액 모의 환불할 수 있습니다. 일반 취소의 세부 정책은 미정입니다. 신청 취소는 자동 환불이 아닙니다.
    </p>
  );
}

/** FAQ Q3 / U04: no-show and late-cancellation rules are not decided yet (PAY-02). */
export function NoShowNotice() {
  return (
    <p className="small muted">
      노쇼·취소 정책 미정: 노쇼 횟수·참여 제한·이용권 차감 기준과 당일 취소
      처리는 아직 정해지지 않았습니다.
    </p>
  );
}

/** Payment is possible until the earliest candidate closes (the API answers 409 after). */
export function paymentOpen(application: Application) {
  return (
    application.payment_required &&
    application.candidates.some(slot => slot.live) &&
    application.candidates.filter(slot => slot.live).every((slot) => slot.recruiting)
  );
}

function productLabel(product: Product) {
  return `${product.name} · ${won(product.price_krw)}`;
}
// Provisional U03 rules (pending CEO confirmation), marked as such like "내 이용권".
function productDetail(product: Product) {
  return product.kind === "SINGLE"
    ? "한 번 참가 · 결제 후 보유하고 테이블 확정 시 사용 처리 · 임시 적용 · 확정 전"
    : `결제 완료 시각부터 ${product.period_months}개월(달력 기준) · 기간 내 참여 횟수 무제한 · 임시 적용 · 확정 전`;
}

export function useCatalog() {
  const request = useScopedApi();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    request<Catalog>("/api/products")
      .then(setCatalog)
      .catch((error) => setError(message(error)));
  }, []);
  return { catalog, error };
}

export function ProductChoice({
  products,
  value,
  onChange,
  disabled = false,
}: {
  products: Product[];
  value: ProductCode | null;
  onChange: (code: ProductCode) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset role="radiogroup" aria-label="이용권">
      <legend>이용권</legend>
      {products.map((product) => (
        <label className="check" key={product.code}>
          <input
            type="radio"
            name="product"
            checked={value === product.code}
            disabled={disabled}
            onChange={() => onChange(product.code)}
          />
          <span>
            <strong>{productLabel(product)}</strong>
            <span className="small muted block">{productDetail(product)}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** Mock checkout for one application: product, refund notice, explicit failure option. */
export function PaymentPanel({
  application,
  initialProduct,
  onPaid,
}: {
  application: Application;
  initialProduct: ProductCode | null;
  onPaid?: () => void;
}) {
  const request = useScopedApi();
  const { catalog, error: catalogError } = useCatalog();
  const [product, setProduct] = useState<ProductCode | null>(initialProduct);
  const [simulateFailure, setSimulateFailure] = useState(false);
  // One key per attempt: a retried click after a lost response is the same payment.
  const [requestKey, setRequestKey] = useState(newKey);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<Payment | null>(null);
  const [reused, setReused] = useState(false);
  const [error, setError] = useState("");
  const paid =
    result?.state === "PAID" ||
    application.payments.some((payment) => payment.state === "PAID");
  const chosen = catalog?.products.find((item) => item.code === product);
  function change(update: () => void) {
    update();
    setError("");
    setRequestKey(newKey());
  }
  async function pay() {
    if (!product) return;
    setPending(true);
    setError("");
    try {
      const { payment } = await request<{ payment: Payment }>(
        `/api/me/applications/${application.id}/payments`,
        {
          method: "POST",
          body: JSON.stringify({
            request_key: requestKey,
            product_code: product,
            simulate_failure: simulateFailure,
          }),
        },
      );
      setResult(payment);
      // A finished attempt (paid or failed) is never re-sent; the next try is new.
      setRequestKey(newKey());
      if (payment.state === "PAID") onPaid?.();
    } catch (error) {
      setError(paymentError(error));
    } finally {
      setPending(false);
    }
  }
  return (
    <section aria-labelledby={`pay-${application.id}`} className="pay-panel">
      <h2 id={`pay-${application.id}`}>모의 결제</h2>
      <p className="notice">
        <strong>모의 결제 · 실제 결제가 발생하지 않습니다</strong>
        <br />
        카드·계좌 정보를 받지 않으며 실제 PG 결제가 아닙니다.
      </p>
      {catalogError && <Notice error>{catalogError}</Notice>}
      {error && <Notice error>{error}</Notice>}
      {result?.state === "FAILED" && !error && (
        <Notice error>
          결제 실패 · {result.product.name} {won(result.amount_krw)}이 결제되지
          않았습니다. 실패 기록은 남으며 다시 결제할 수 있습니다.
        </Notice>
      )}
      {!paid && !reused && paymentOpen(application) && <ReusablePasses applicationId={application.id} onUsed={() => { setReused(true); onPaid?.(); }} />}
      {reused ? <Notice>보관한 1회권을 적용했습니다. 추가 결제 없이 자동 매칭을 기다려 주세요.</Notice> : paid ? (
        <Notice>
          결제 완료 ·{" "}
          {result
            ? `${result.product.name} ${won(result.amount_krw)}`
            : "이 신청의 결제가 이미 완료되었습니다"}{" "}
          (모의 결제)
        </Notice>
      ) : !catalog ? (
        !catalogError && <p>이용권을 확인하고 있습니다…</p>
      ) : (
        <>
          <ProductChoice
            products={catalog.products}
            value={product}
            disabled={pending}
            onChange={(code) => change(() => setProduct(code))}
          />
          <p>
            <strong>
              {chosen
                ? `결제 금액 ${won(chosen.price_krw)}`
                : "이용권을 선택해 주세요"}
            </strong>
          </p>
          <RefundNotice />
          <NoShowNotice />
          <label className="check">
            <input
              type="checkbox"
              checked={simulateFailure}
              disabled={pending}
              onChange={(e) =>
                change(() => setSimulateFailure(e.target.checked))
              }
            />
            <span>실패 시뮬레이션 (시연·시험용: 이번 결제를 실패로 처리)</span>
          </label>
          <div className="actions">
            <button
              className="primary"
              disabled={!chosen || pending}
              onClick={() => void pay()}
            >
              {pending ? "결제 처리 중…" : "모의 결제하기"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function ReusablePasses({ applicationId, onUsed }: { applicationId: string; onUsed: () => void }) {
  const request = useScopedApi();
  const [rights, setRights] = useState<Entitlement[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [key] = useState(newKey);
  const [selected, setSelected] = useState("");
  useEffect(() => { request<{ entitlements: Entitlement[] }>("/api/me/entitlements")
    .then(body => setRights(body.entitlements.filter(right => right.reusable)))
    .catch(error => setError(message(error))); }, [applicationId]);
  async function reuse(id: string) {
    setPending(true); setError("");
    // Keep the idempotency key tied to a single chosen right across a lost response.
    try {
      await request(`/api/me/entitlements/${id}/reuse`, { method: "POST", body: JSON.stringify({
        application_id: applicationId, request_key: key,
      }) }); onUsed();
    } catch (error) { setError(error instanceof ApiError && error.status === 409
      ? "이용권 또는 신청 상태가 변경되었습니다. 내 신청을 확인해 주세요." : message(error)); }
    finally { setPending(false); }
  }
  return <section aria-label="보관한 이용권 재사용">
    {error && <Notice error>{error}</Notice>}
    {rights.length > 0 && <><p>보관한 1회권을 추가 결제 없이 사용할 수 있습니다.</p>
      {rights.map((right, index) => <button key={right.id} disabled={pending || (!!selected && selected !== right.id)}
        onClick={() => { setSelected(right.id); void reuse(right.id); }}>보관한 1회권 사용 {index + 1}</button>)}
    </>}
  </section>;
}

/** Payment state of an application, kept separate from the application state. */
export function paymentSummary(application: Application) {
  const [latest] = application.payments;
  const failures = application.payments.filter(
    (payment) => payment.state === "FAILED",
  ).length;
  const failureNote = failures ? ` · 결제 실패 ${failures}회 기록` : "";
  if (latest?.state === "REFUNDED") return `전액 모의 환불 완료 · ${won(latest.amount_krw)}`;
  if (application.coverage?.entitlement.reserved_application_id === application.id && !latest)
    return "보관한 1회권 재사용 · 추가 결제 없음";
  if (latest?.state === "PAID")
    return `결제 완료 · ${latest.product.name} ${won(latest.amount_krw)} (모의)${failureNote}`;
  if (application.coverage?.source === "membership")
    return `멤버십 적용 · 결제 불필요${failureNote}`;
  if (application.payment_required && !paymentOpen(application))
    return `결제 마감 · 미결제${failureNote}`;
  if (latest?.state === "PENDING") return `결제 대기${failureNote}`;
  if (latest?.state === "FAILED")
    return `결제 실패 · 다시 결제 필요${failureNote}`;
  if (application.payment_required) return "결제 필요";
  return "결제 없음";
}

const entitlementStates: Record<Entitlement["state"], string> = {
  HELD: "보유 중",
  USED: "사용 완료",
  ACTIVE: "이용 중",
  EXPIRED: "만료됨",
  REFUNDED: "모의 환불 완료",
};

/** The participant's passes: kind, state and, for memberships, the period. */
export function MyEntitlements() {
  const request = useScopedApi();
  const [entitlements, setEntitlements] = useState<Entitlement[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    request<{ entitlements: Entitlement[] }>("/api/me/entitlements")
      .then((body) => setEntitlements(body.entitlements))
      .catch((error) => setError(message(error)));
  }, []);
  return (
    <>
      <h2>내 이용권</h2>
      {error && <Notice error>{error}</Notice>}
      {!entitlements ? (
        !error && <Notice>이용권을 확인하고 있습니다…</Notice>
      ) : entitlements.length ? (
        <ul className="participants" aria-label="내 이용권">
          {entitlements.map((item) => (
            <li key={item.id}>
              <p>
                <strong>
                  {productNames[item.product_code]} ·{" "}
                  {item.application_state === "CANCELED" && item.state === "HELD"
                    ? "취소된 신청에 묶여 보유"
                    : entitlementStates[item.state]}
                </strong>
              </p>
              <p className="small muted">
                {item.kind === "MEMBERSHIP"
                  ? `시작 ${day.format(new Date(item.starts_at))} · 만료 ${day.format(new Date(item.expires_at!))} · 기간 내 참여 횟수 무제한`
                  : item.reusable
                    ? "보관 완료 · 만료 없음 · 새 신청의 결제 화면에서 재사용 가능"
                  : item.state === "REFUNDED" ? "원결제 금액 전액 모의 환불 완료 · 재사용 불가"
                  : item.state === "USED"
                    ? `테이블 확정으로 사용 완료 · ${day.format(new Date(item.used_at!))}`
                  : item.application_state === "CANCELED"
                    ? "결제한 신청이 취소됨 · 자동 환불 아님 · 보관·재사용 규칙 미정"
                    : "결제한 신청에 보유 · 테이블 확정 시 사용 처리 예정 · 취소 시 보관·재사용 규칙 미정"}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p>보유한 이용권이 없습니다.</p>
      )}
      <p className="small muted">
        이용권 규칙은 임시 적용 중입니다(멤버십은 결제 완료 시각부터 달력 기준
        개월 수, 말일 보정). 최종 실패 신청당 멤버십을 7일 한 번 연장합니다. 자동 갱신 정책은 미정입니다.
      </p>
    </>
  );
}

/** /participant/payment/:id — pay later for an application that still needs a pass. */
export function PaymentPage({
  applicationId,
  navigate,
}: {
  applicationId: string;
  navigate: (path: string) => void;
}) {
  const request = useScopedApi();
  const [application, setApplication] = useState<Application | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    request<{ applications: Application[] }>("/api/me/applications")
      .then((body) => {
        const found = body.applications.find(
          (item) => item.id === applicationId,
        );
        if (found) setApplication(found);
        else setError("신청을 찾을 수 없습니다.");
      })
      .catch((error) => setError(message(error)));
  }, [applicationId]);
  return (
    <section className="narrow">
      <h1>이용권 결제</h1>
      {error && <Notice error>{error}</Notice>}
      {application ? (
        paymentOpen(application) ||
        application.payments.some((item) => item.state === "PAID") ? (
          <PaymentPanel application={application} initialProduct={null} />
        ) : (
          <Notice>{paymentSummary(application)}</Notice>
        )
      ) : (
        !error && <Notice>신청을 확인하고 있습니다…</Notice>
      )}
      <button onClick={() => navigate("/participant")}>내 신청 보기</button>
    </section>
  );
}
