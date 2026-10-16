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
  const mutation = init.method && !["GET", "HEAD"].includes(init.method);
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
  consents: Consent[];
  consents_complete: boolean;
};
