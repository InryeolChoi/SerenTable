import { useEffect, useRef, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import {
  api,
  ApiError,
  bootstrapCsrf,
  clearCsrf,
  emptyProfile,
  profileStatus,
  type User,
  type Profile,
  type ProfileState,
  type Choice,
  type Options,
  type Policy,
  type Consent,
  type ConsentState,
  type Participant,
  type ParticipantDetail,
} from "./api";
import symbol from "./chance-table-symbol.svg";
import "./style.css";

function message(error: unknown) {
  return error instanceof Error ? error.message : "요청을 완료하지 못했습니다.";
}
function Notice({
  children,
  error = false,
}: {
  children: React.ReactNode;
  error?: boolean;
}) {
  return (
    <p
      className={error ? "notice error" : "notice"}
      role={error ? "alert" : "status"}
    >
      {children}
    </p>
  );
}
// 화면을 떠난 뒤 이전 계정의 응답이 새 화면의 입력을 덮어쓰지 않도록 취소한다.
function useScopedApi() {
  const controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);
  return function request<T>(path: string, init: RequestInit = {}) {
    return api<T>(path, { ...init, signal: controller.current.signal });
  };
}
function Login({
  onLogin,
  expired,
}: {
  onLogin: (user: User) => void;
  expired: boolean;
}) {
  const request = useScopedApi();
  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      await bootstrapCsrf();
      const result = await request<{ user: User }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ login_id: loginId, password }),
      });
      setPassword("");
      await bootstrapCsrf();
      onLogin(result.user);
    } catch (error) {
      setError(
        error instanceof ApiError && error.status === 401
          ? "계정 ID 또는 비밀번호를 확인해 주세요."
          : message(error),
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="narrow">
      <h1>식탁을 시작하세요</h1>
      <p className="lead">사전 발급된 합성 계정으로 로그인해 주세요.</p>
      <p className="muted">
        심사용 데모입니다. 실제 개인정보를 입력하지 마세요.
      </p>
      {expired && (
        <Notice error>
          세션이 만료되었습니다. 다시 로그인해 주세요. 저장하지 않은 프로필은 이
          탭에서 같은 계정으로 돌아올 때 유지됩니다.
        </Notice>
      )}
      <form aria-label="합성 계정 로그인" onSubmit={submit}>
        <label>
          계정 ID
          <input
            required
            autoComplete="username"
            value={loginId}
            onChange={(e) => setLoginId(e.target.value)}
            maxLength={100}
          />
        </label>
        <label>
          비밀번호
          <input
            required
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            maxLength={256}
          />
        </label>
        {error && <Notice error>{error}</Notice>}
        <button className="primary" disabled={pending}>
          {pending ? "로그인 확인 중…" : "로그인"}
        </button>
      </form>
    </section>
  );
}
function Checks({
  title,
  choices,
  selected,
  onChange,
  hint,
}: {
  title: string;
  choices: Choice[];
  selected: string[];
  onChange: (values: string[]) => void;
  hint?: string;
}) {
  return (
    <fieldset>
      <legend>{title}</legend>
      {hint && <p className="muted small">{hint}</p>}
      <div className="checks">
        {choices.map((choice) => (
          <label key={choice.value}>
            <input
              type="checkbox"
              checked={selected.includes(choice.value)}
              onChange={(e) =>
                onChange(
                  e.target.checked
                    ? [...selected, choice.value]
                    : selected.filter((value) => value !== choice.value),
                )
              }
            />
            {choice.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
function FoodField({
  name,
  title,
  draft,
  setDraft,
}: {
  name: "food_restrictions" | "allergies";
  title: string;
  draft: Profile;
  setDraft: (draft: Profile) => void;
}) {
  const answer = draft[name];
  return (
    <fieldset>
      <legend>{title}</legend>
      <label>
        확인 상태
        <select
          value={answer.status}
          onChange={(e) =>
            setDraft({
              ...draft,
              [name]: {
                status: e.target.value,
                details:
                  e.target.value === "specified"
                    ? (answer.details ?? "")
                    : null,
              },
            })
          }
        >
          <option value="unknown">아직 확인하지 않음</option>
          <option value="none">없음</option>
          <option value="specified">있음 · 내용 입력</option>
        </select>
      </label>
      {answer.status === "specified" && (
        <label>
          내용
          <textarea
            required
            value={answer.details ?? ""}
            maxLength={500}
            onChange={(e) =>
              setDraft({
                ...draft,
                [name]: { ...answer, details: e.target.value },
              })
            }
          />
        </label>
      )}
    </fieldset>
  );
}
function ProfilePage({
  draft,
  setDraft,
  navigate,
}: {
  draft: Profile | null;
  setDraft: (draft: Profile) => void;
  navigate: (path: string) => void;
}) {
  const request = useScopedApi();
  const [options, setOptions] = useState<Options | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  async function load() {
    setLoading(true);
    setError("");
    try {
      const [choices, state] = await Promise.all([
        request<Options>("/api/profile/options"),
        request<ProfileState>("/api/me/profile"),
      ]);
      setOptions(choices);
      if (!draft) setDraft(state.profile ?? emptyProfile());
    } catch (error) {
      setError(message(error));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    setPending(true);
    setSaved("");
    setError("");
    try {
      const result = await request<ProfileState>("/api/me/profile", {
        method: "PUT",
        body: JSON.stringify(draft),
      });
      setDraft(result.profile ?? draft);
      setSaved(
        result.complete
          ? "프로필을 저장했습니다. 필요한 항목이 모두 입력되었습니다."
          : "미완성 프로필을 저장했습니다. 빠진 항목은 나중에 추가할 수 있습니다.",
      );
    } catch (error) {
      setError(message(error));
    } finally {
      setPending(false);
    }
  }
  if (loading) return <Notice>프로필을 확인하고 있습니다…</Notice>;
  if (!options || !draft)
    return (
      <>
        <Notice error>{error}</Notice>
        <button onClick={() => void load()}>다시 불러오기</button>
      </>
    );
  const textFields = [
    ["name", "이름 원문"],
    ["display_name", "표시명"],
    ["contact", "연락처"],
    ["instagram_id", "Instagram ID"],
    ["occupation", "직업"],
  ] as const;
  return (
    <section className="narrow">
      <h1>내 프로필</h1>
      <p className="lead">
        합성 정보만 입력해 주세요. 미완성 상태로도 저장할 수 있습니다.
      </p>
      <p className="muted">
        이름과 표시명은 다릅니다. 연락처·Instagram·출생연도·이름 원문은 다른
        참가자에게 공개하지 않습니다.
      </p>
      <form aria-label="본인 프로필" onSubmit={save}>
        <fieldset disabled={pending} className="form-body">
          {textFields.map(([name, title]) => (
            <label key={name}>
              {title}
              <span className="small muted">
                {name === "instagram_id"
                  ? "입력 완료에 필요 · @ 없이 영문·숫자·마침표·밑줄만 입력"
                  : "입력 완료에 필요"}
              </span>
              <input
                value={draft[name] ?? ""}
                maxLength={
                  name === "instagram_id" ? 30 : name === "contact" ? 40 : 100
                }
                autoComplete="off"
                onChange={(e) => {
                  setSaved("");
                  setDraft({ ...draft, [name]: e.target.value });
                }}
              />
            </label>
          ))}
          <label>
            출생연도
            <span className="small muted">
              4자리 연도. 정확한 만나이로 표시하지 않습니다.
            </span>
            <input
              type="number"
              min={1000}
              max={new Date().getFullYear()}
              value={draft.birth_year ?? ""}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  birth_year: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </label>
          <label>
            성별
            <input
              value={draft.gender ?? ""}
              maxLength={100}
              onChange={(e) => setDraft({ ...draft, gender: e.target.value })}
            />
          </label>
          <Checks
            title="MBTI (복수 선택)"
            hint="모르면 선택하지 않아도 됩니다."
            choices={options.mbtis}
            selected={draft.mbtis}
            onChange={(values) => setDraft({ ...draft, mbtis: values })}
          />
          {(
            [
              ["interests", "요즘 관심사"],
              ["self_traits", "나는 어떤 사람인가요"],
              ["desired_traits", "만나고 싶은 사람"],
              ["meal_budget_bands", "식사에 쓸 수 있는 예산"],
            ] as const
          ).map(([name, title]) => (
            <Checks
              key={name}
              title={title}
              choices={options[name]}
              selected={draft[name]}
              hint="입력 완료에 1개 이상 선택해 주세요."
              onChange={(values) => setDraft({ ...draft, [name]: values })}
            />
          ))}
          <FoodField
            name="food_restrictions"
            title="못 먹는 음식"
            draft={draft}
            setDraft={setDraft}
          />
          <FoodField
            name="allergies"
            title="알레르기"
            draft={draft}
            setDraft={setDraft}
          />
          <p className="small muted">
            미확인은 없음과 구분해 저장합니다. 식사 예산과 참가비는 별개입니다.
          </p>
          {error && <Notice error>{error}</Notice>}
          {saved && <Notice>{saved}</Notice>}
          <div className="actions">
            <button className="primary" disabled={pending}>
              {pending ? "저장 중…" : "프로필 저장"}
            </button>
            <button
              type="button"
              onClick={() => navigate("/participant/consent")}
            >
              동의 내용 확인
            </button>
          </div>
        </fieldset>
      </form>
    </section>
  );
}
function ConsentPage() {
  const request = useScopedApi();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [choices, setChoices] = useState<Consent[]>([]);
  const [current, setCurrent] = useState<ConsentState | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  async function load() {
    setLoading(true);
    setError("");
    try {
      const [terms, state] = await Promise.all([
        request<{ policies: Policy[] }>("/api/consent/policies"),
        request<ConsentState>("/api/me/consents"),
      ]);
      setPolicies(terms.policies);
      setCurrent(state);
      setChoices(
        terms.policies.map((policy) => ({
          purpose: policy.purpose,
          version: policy.version,
          accepted: state.consents.some(
            (consent) =>
              consent.purpose === policy.purpose &&
              consent.version === policy.version &&
              consent.accepted,
          ),
        })),
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
  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    setSaved(false);
    try {
      setCurrent(
        await request<ConsentState>("/api/me/consents", {
          method: "PUT",
          body: JSON.stringify({ consents: choices }),
        }),
      );
      setSaved(true);
    } catch (error) {
      setError(message(error));
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="narrow">
      <h1>동의 및 이용 안내</h1>
      <p className="lead">목적별 전문과 버전을 확인하고 직접 선택해 주세요.</p>
      <p className="muted">
        합성 데이터 데모용 안내입니다. 정식 출시를 위한 법률 검토를 마친
        개인정보 처리방침은 아닙니다.
      </p>
      {loading ? (
        <Notice>동의 내용을 확인하고 있습니다…</Notice>
      ) : policies.length ? (
        <form onSubmit={submit}>
          {policies.map((policy, index) => (
            <fieldset
              className="policy"
              key={policy.purpose}
              disabled={pending}
            >
              <legend>
                {policy.title}
                {policy.required ? " (필수)" : " (선택)"}
              </legend>
              <p className="small muted">버전: {policy.version}</p>
              <div className="policy-body">{policy.body}</div>
              <label className="check">
                <input
                  type="checkbox"
                  checked={choices[index]?.accepted ?? false}
                  onChange={(e) => {
                    setSaved(false);
                    setChoices(
                      choices.map((choice, i) =>
                        i === index
                          ? { ...choice, accepted: e.target.checked }
                          : choice,
                      ),
                    );
                  }}
                />
                이 목적에 동의합니다
              </label>
            </fieldset>
          ))}
          {error && <Notice error>{error}</Notice>}
          <button className="primary" disabled={pending}>
            {pending ? "저장 중…" : "동의 선택 저장"}
          </button>
          {saved && <Notice>동의 선택을 저장했습니다.</Notice>}
          <h2>현재 저장된 상태</h2>
          <p>
            {current?.complete
              ? "필수 동의가 완료되었습니다."
              : "필수 동의가 완료되지 않았습니다."}
          </p>
          {current?.consents.map((consent) => (
            <p className="small" key={`${consent.purpose}-${consent.version}`}>
              {policies.find((policy) => policy.purpose === consent.purpose)
                ?.title ?? consent.purpose}{" "}
              / {consent.version} / {consent.accepted ? "동의" : "미동의"}
              {consent.recorded_at
                ? ` / ${new Date(consent.recorded_at).toLocaleString("ko-KR")}`
                : ""}
            </p>
          ))}
        </form>
      ) : (
        <>
          <Notice error>{error || "동의 안내를 불러오지 못했습니다."}</Notice>
          <button onClick={() => void load()}>다시 불러오기</button>
        </>
      )}
    </section>
  );
}
function ParticipantHome({ navigate }: { navigate: (path: string) => void }) {
  const request = useScopedApi();
  const [profile, setProfile] = useState<ProfileState | null>(null);
  const [consent, setConsent] = useState<ConsentState | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([
      request<ProfileState>("/api/me/profile"),
      request<ConsentState>("/api/me/consents"),
    ])
      .then(([p, c]) => {
        setProfile(p);
        setConsent(c);
      })
      .catch((error) => setError(message(error)));
  }, []);
  return (
    <section className="narrow">
      <h1>내 식탁 준비</h1>
      <p className="lead">본인 정보와 동의 상태를 확인해 주세요.</p>
      {error ? (
        <Notice error>{error}</Notice>
      ) : !profile || !consent ? (
        <Notice>저장 상태를 확인하고 있습니다…</Notice>
      ) : (
        <dl className="status-grid">
          <div>
            <dt>프로필</dt>
            <dd>{profile.complete ? "입력 완료" : "미완성 프로필"}</dd>
          </div>
          <div>
            <dt>필수 동의</dt>
            <dd>{consent.complete ? "동의 완료" : "확인 필요"}</dd>
          </div>
        </dl>
      )}
      <div className="actions">
        <button
          className="primary"
          onClick={() => navigate("/participant/profile")}
        >
          프로필 수정
        </button>
        <button onClick={() => navigate("/participant/consent")}>
          동의 내용 확인
        </button>
      </div>
      <p className="notice">
        참가 신청·결제는 다음 개발 단계에서 제공합니다. 입력 완료는 참가 확정이
        아닙니다.
      </p>
    </section>
  );
}
function AdminPage() {
  const request = useScopedApi();
  const [list, setList] = useState<Participant[]>([]);
  const [options, setOptions] = useState<Options | null>(null);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<ParticipantDetail | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("");
  async function load() {
    setLoading(true);
    setError("");
    try {
      const [result, metadata] = await Promise.all([
        request<{ participants: Participant[] }>("/api/admin/participants"),
        request<Options>("/api/profile/options"),
      ]);
      setList(result.participants);
      setOptions(metadata);
    } catch (error) {
      setError(message(error));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function show(person: Participant) {
    setSelected(person.id);
    setDetail(null);
    setError("");
    setPending(true);
    try {
      setDetail(
        await request<ParticipantDetail>(
          `/api/admin/participants/${encodeURIComponent(person.id)}`,
        ),
      );
    } catch (error) {
      setError(message(error));
    } finally {
      setPending(false);
    }
  }
  return (
    <section>
      <h1>합성 참가자 관리</h1>
      <p className="lead">
        권한이 있는 운영자만 상세 정보를 확인할 수 있습니다.
      </p>
      {error && <Notice error>{error}</Notice>}
      <div className="admin-grid">
        <div>
          <h2>참가자 목록</h2>
          {loading ? (
            <Notice>목록을 확인하고 있습니다…</Notice>
          ) : list.length ? (
            <ul className="participants">
              {list.map((person) => (
                <li key={person.id}>
                  <strong>{person.display_name || "표시명 미입력"}</strong>
                  <p className="small muted">
                    {person.login_id} ·{" "}
                    {profileStatus(
                      person.profile_complete,
                      person.profile_unreadable,
                    )}
                  </p>
                  <button
                    aria-label={`상세 보기: ${person.login_id}`}
                    aria-pressed={selected === person.id}
                    onClick={() => void show(person)}
                  >
                    상세 보기
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p>등록된 합성 참가자가 없습니다.</p>
          )}
          <button onClick={() => void load()}>목록 새로고침</button>
        </div>
        <div>
          <h2>참가자 상세</h2>
          {pending ? (
            <Notice>상세 정보를 확인하고 있습니다…</Notice>
          ) : detail ? (
            <AdminDetail value={detail} options={options} />
          ) : (
            <p className="muted">
              목록에서 참가자를 선택해 주세요. 연락처는 목록에 표시하지
              않습니다.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
function AdminDetail({
  value,
  options,
}: {
  value: ParticipantDetail;
  options: Options | null;
}) {
  const p = value.profile;
  const fields: [string, string | number | null | undefined][] = [
    ["계정 ID", value.user.login_id],
    ["이름 원문", p?.name],
    ["표시명", p?.display_name],
    ["연락처", p?.contact],
    ["Instagram ID", p?.instagram_id],
    ["출생연도", p?.birth_year],
    ["성별", p?.gender],
    ["직업", p?.occupation],
    ["MBTI", p?.mbtis.join(", ")],
  ];
  const foodText = (answer: Profile["allergies"] | undefined) =>
    !answer || answer.status === "unknown"
      ? "아직 확인하지 않음"
      : answer.status === "none"
        ? "없음"
        : answer.details;
  const categories = [
    ["interests", "관심사"],
    ["self_traits", "본인 성향"],
    ["desired_traits", "희망 성향"],
    ["meal_budget_bands", "식사 예산"],
  ] as const;
  return (
    <article>
      <h3>{p?.display_name || value.user.login_id}</h3>
      <dl className="detail-list">
        {fields.map(([label, text]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{text || "미입력"}</dd>
          </div>
        ))}
        {categories.map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              {p?.[key]
                .map(
                  (v) => options?.[key].find((c) => c.value === v)?.label ?? v,
                )
                .join(", ") || "미입력"}
            </dd>
          </div>
        ))}
        <div>
          <dt>못 먹는 음식</dt>
          <dd>{foodText(p?.food_restrictions)}</dd>
        </div>
        <div>
          <dt>알레르기</dt>
          <dd>{foodText(p?.allergies)}</dd>
        </div>
      </dl>
      <p>
        프로필:{" "}
        {profileStatus(value.profile_complete, value.profile_unreadable)}
      </p>
      <p>필수 동의: {value.consents_complete ? "완료" : "미완료"}</p>
      {value.consents.map((c) => (
        <p className="small" key={c.purpose}>
          {c.purpose === "privacy" ? "개인정보 동의" : "운영 정책 동의"} ·{" "}
          {c.version} · {c.accepted ? "동의" : "미동의"}
        </p>
      ))}
    </article>
  );
}
function App() {
  const [path, setPath] = useState(window.location.pathname);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [initialError, setInitialError] = useState("");
  const [expired, setExpired] = useState(false);
  const [draft, setDraft] = useState<Profile | null>(null);
  const previousUser = useRef<string | null>(null);
  const [logoutPending, setLogoutPending] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  function navigate(next: string) {
    window.history.pushState({}, "", next);
    setPath(next);
    window.scrollTo(0, 0);
  }
  async function checkSession() {
    setLoading(true);
    setInitialError("");
    try {
      setUser((await api<{ user: User }>("/api/auth/me")).user);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401))
        setInitialError(message(error));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void checkSession();
    const pop = () => setPath(window.location.pathname);
    const expire = () => {
      setUser(null);
      setExpired(true);
    };
    window.addEventListener("popstate", pop);
    window.addEventListener("session-expired", expire);
    return () => {
      window.removeEventListener("popstate", pop);
      window.removeEventListener("session-expired", expire);
    };
  }, []);
  function loggedIn(next: User) {
    if (previousUser.current !== next.id) setDraft(null);
    previousUser.current = next.id;
    setUser(next);
    setExpired(false);
    navigate(next.role === "operator" ? "/admin" : "/participant");
  }
  async function logout() {
    setLogoutPending(true);
    setLogoutError("");
    try {
      await api("/api/auth/logout", { method: "POST" });
      finishLogout();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) finishLogout();
      else setLogoutError(message(error));
    } finally {
      setLogoutPending(false);
    }
  }
  function finishLogout() {
    clearCsrf();
    setUser(null);
    setDraft(null);
    previousUser.current = null;
    setExpired(false);
    navigate("/login");
  }
  useEffect(() => {
    if (user && !previousUser.current) previousUser.current = user.id;
  }, [user]);
  useEffect(() => {
    const heading = document.querySelector<HTMLElement>("main h1");
    if (heading) {
      heading.tabIndex = -1;
      heading.focus();
      document.title = `${heading.textContent} · 우연한 식탁`;
    }
  }, [path, user, loading]);
  const adminRoute = path.startsWith("/admin");
  return (
    <>
      <a className="skip" href="#main">
        본문으로 이동
      </a>
      <div className="demo-banner">
        합성 데이터 심사용 데모 · 실제 개인정보를 입력하지 마세요
      </div>
      <div className="shell">
        <header>
          <a
            className="brand"
            href="/"
            onClick={(e) => {
              e.preventDefault();
              navigate("/");
            }}
            aria-label="우연한 식탁 홈"
          >
            <img src={symbol} alt="" />
            <span>
              우연한
              <br />
              식탁
            </span>
          </a>
          {user && (
            <div className="account">
              <span>
                {user.login_id} ·{" "}
                {user.role === "operator" ? "운영자" : "참가자"}
              </span>
              <button disabled={logoutPending} onClick={() => void logout()}>
                {logoutPending ? "로그아웃 중…" : "로그아웃"}
              </button>
            </div>
          )}
        </header>
        {user && (
          <nav aria-label="주요 화면">
            <a
              href={user.role === "operator" ? "/admin" : "/participant"}
              onClick={(e) => {
                e.preventDefault();
                navigate(user.role === "operator" ? "/admin" : "/participant");
              }}
            >
              {user.role === "operator" ? "참가자 관리" : "입력 상태"}
            </a>
            {user.role === "participant" && (
              <>
                <a
                  href="/participant/profile"
                  onClick={(e) => {
                    e.preventDefault();
                    navigate("/participant/profile");
                  }}
                >
                  프로필
                </a>
                <a
                  href="/participant/consent"
                  onClick={(e) => {
                    e.preventDefault();
                    navigate("/participant/consent");
                  }}
                >
                  동의
                </a>
              </>
            )}
          </nav>
        )}
        <main id="main">
          {logoutError && <Notice error>{logoutError}</Notice>}
          {loading ? (
            <Notice>로그인 상태를 확인하고 있습니다…</Notice>
          ) : initialError ? (
            <>
              <Notice error>{initialError}</Notice>
              <button onClick={() => void checkSession()}>다시 시도</button>
            </>
          ) : !user ? (
            <Login onLogin={loggedIn} expired={expired} />
          ) : adminRoute && user.role !== "operator" ? (
            <section>
              <h1>접근 권한이 없습니다</h1>
              <p>운영자 화면을 볼 수 없습니다.</p>
              <button onClick={() => navigate("/participant")}>
                내 화면으로 돌아가기
              </button>
            </section>
          ) : user.role === "operator" ? (
            <AdminPage />
          ) : path === "/participant/profile" ? (
            <ProfilePage
              draft={draft}
              setDraft={setDraft}
              navigate={navigate}
            />
          ) : path === "/participant/consent" ? (
            <ConsentPage />
          ) : (
            <ParticipantHome navigate={navigate} />
          )}
        </main>
        <footer>
          <p>우연한 식탁 · 운영사 와썹하우스</p>
          <p>제공 자료를 참고한 재현 심볼이며 공식 로고 원본이 아닙니다.</p>
        </footer>
      </div>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
