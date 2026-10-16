export type User = {
  id: string;
  login_id: string;
  role: "participant" | "operator";
};
export type FoodAnswer = {
  status: "unknown" | "none" | "specified";
  details: string | null;
};
export type Profile = {
  name: string | null;
  display_name: string | null;
  contact: string | null;
  instagram_id: string | null;
  birth_year: number | null;
  gender: string | null;
  occupation: string | null;
  mbtis: string[];
  interests: string[];
  self_traits: string[];
  desired_traits: string[];
  meal_budget_bands: string[];
  food_restrictions: FoodAnswer;
  allergies: FoodAnswer;
};
export type ProfileState = {
  profile: Profile | null;
  complete: boolean;
  missing_fields: string[];
  unreadable: boolean;
};
export type Choice = { value: string; label: string };
export type Options = Record<
  | "mbtis"
  | "interests"
  | "self_traits"
  | "desired_traits"
  | "meal_budget_bands",
  Choice[]
>;
export type Policy = {
  purpose: string;
  version: string;
  title: string;
  body: string;
  required: boolean;
};
export type Consent = {
  purpose: string;
  version: string;
  accepted: boolean;
  recorded_at?: string;
};
export type ConsentState = { consents: Consent[]; complete: boolean };
export type Participant = {
  id: string;
  login_id: string;
  display_name: string | null;
  profile_complete: boolean;
  profile_unreadable: boolean;
};
export type Region = { code: string; name: string };
export type EventSlot = {
  id: string;
  region: Region;
  starts_at: string;
  ends_at: string;
  closes_at: string;
  matches_at: string;
  capacity: number;
  recruiting: boolean;
};
export type ProductCode =
  "single" | "membership_1m" | "membership_3m" | "membership_6m";
export type Product = {
  code: ProductCode;
  name: string;
  kind: "SINGLE" | "MEMBERSHIP";
  price_krw: number;
  period_months: number | null;
};
export type Catalog = {
  mock: true;
  product_version: string;
  policy_version: string;
  products: Product[];
};
export type Payment = {
  id: string;
  application_id: string;
  state: "PENDING" | "PAID" | "FAILED";
  mock: true;
  amount_krw: number;
  product: Product & { version: string };
  policy_version: string;
  simulated_failure: boolean;
  requested_at: string;
  completed_at: string | null;
};
export type Entitlement = {
  id: string;
  kind: "SINGLE" | "MEMBERSHIP";
  product_code: ProductCode;
  payment_id: string;
  application_id: string | null;
  starts_at: string;
  expires_at: string | null;
  state: "HELD" | "ACTIVE" | "EXPIRED";
  policy_version: string;
};
export type Application = {
  id: string;
  state: "DRAFT" | "SUBMITTED" | "CANCELED";
  submitted_at: string | null;
  canceled_at: string | null;
  candidates: EventSlot[];
  payments: Payment[];
  coverage: {
    source: "payment" | "membership";
    entitlement: Entitlement;
  } | null;
  payment_required: boolean;
  participant?: { id: string; login_id: string };
};
let csrfToken: string | null = null;
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(validationMessage(status, detail));
  }
}
const fieldNames: Record<string, string> = {
  name: "이름 원문",
  display_name: "표시명",
  contact: "연락처",
  instagram_id: "Instagram ID",
  birth_year: "출생연도",
  gender: "성별",
  occupation: "직업",
  mbtis: "MBTI",
  interests: "관심사",
  self_traits: "본인 성향",
  desired_traits: "희망 성향",
  meal_budget_bands: "식사 예산",
  food_restrictions: "못 먹는 음식",
  allergies: "알레르기",
  region_code: "지역",
  starts_at: "시작 시각",
  ends_at: "종료 시각",
  closes_at: "신청 마감",
  matches_at: "매칭 예정",
  capacity: "정원",
  event_slot_ids: "후보 회차",
  product_code: "이용권",
};
function validationMessage(status: number, detail: unknown) {
  if (status === 422 && Array.isArray(detail)) {
    const fields = [
      ...new Set(
        detail.flatMap((item) =>
          Array.isArray(item?.loc)
            ? item.loc
                .map((part: unknown) =>
                  typeof part === "string" ? fieldNames[part] : undefined,
                )
                .filter(Boolean)
            : [],
        ),
      ),
    ];
    if (fields.length)
      return `${fields.join(", ")}의 입력 형식을 확인해 주세요. 입력 내용은 유지됩니다.`;
  }
  if (status === 503 && detail === "login_busy")
    return "로그인 요청이 잠시 몰렸습니다. 잠시 후 다시 시도해 주세요.";
  return errorMessage(status);
}
function errorMessage(status: number) {
  if (status === 401)
    return "로그인이 필요하거나 세션이 만료되었습니다. 다시 로그인해 주세요.";
  if (status === 403)
    return "허용되지 않은 요청입니다. 권한과 로그인 상태를 확인해 주세요.";
  if (status === 422)
    return "입력 형식이 올바르지 않습니다. 항목을 확인해 주세요. 입력 내용은 유지됩니다.";
  if (status === 429)
    return "로그인 시도가 많습니다. 잠시 후 다시 시도해 주세요.";
  return "요청을 완료하지 못했습니다. 입력 내용은 유지됩니다. 잠시 후 다시 시도해 주세요.";
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await send<T>(path, init);
  } catch (error) {
    // The signed CSRF token expires after an hour; fetch a fresh one and retry once.
    if (
      !(error instanceof ApiError) ||
      error.status !== 403 ||
      error.detail !== "csrf_rejected" ||
      !isMutation(init)
    )
      throw error;
    csrfToken = null;
    return send<T>(path, init);
  }
}
function isMutation(init: RequestInit) {
  return Boolean(init.method && !["GET", "HEAD"].includes(init.method));
}
async function send<T>(path: string, init: RequestInit): Promise<T> {
  const mutation = isMutation(init);
  if (mutation && !csrfToken) await bootstrapCsrf();
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(mutation ? { "X-CSRF-Token": csrfToken! } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new Error(
      "서버에 연결하지 못했습니다. 입력 내용은 유지됩니다. 연결을 확인하고 다시 시도해 주세요.",
    );
  }
  const data = await response.json().catch(() => ({}));
  if (init.signal?.aborted) throw new DOMException("Aborted", "AbortError");
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      csrfToken = null;
      window.dispatchEvent(new Event("session-expired"));
    }
    throw new ApiError(response.status, data.detail);
  }
  return data as T;
}
export async function bootstrapCsrf() {
  csrfToken = (await api<{ csrf_token: string }>("/api/auth/csrf")).csrf_token;
}
export function profileStatus(complete: boolean, unreadable: boolean) {
  if (unreadable) return "저장 형식 확인 필요";
  return complete ? "입력 완료" : "미완성";
}
export function clearCsrf() {
  csrfToken = null;
}
export const emptyProfile = (): Profile => ({
  name: "",
  display_name: "",
  contact: "",
  instagram_id: "",
  birth_year: null,
  gender: "",
  occupation: "",
  mbtis: [],
  interests: [],
  self_traits: [],
  desired_traits: [],
  meal_budget_bands: [],
  food_restrictions: { status: "unknown", details: null },
  allergies: { status: "unknown", details: null },
});

export type ParticipantDetail = {
  user: User;
  profile: Profile | null;
  profile_complete: boolean;
  missing_fields: string[];
  profile_unreadable: boolean;
  consents: Consent[];
  consents_complete: boolean;
};
