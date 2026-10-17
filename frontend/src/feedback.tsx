import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError } from "./api";
import { message, Notice, useScopedApi } from "./ui";

// T2 owns this file: private ratings, intents and per-person preferences (FDB-02~04).
type RatingField =
  | "table_rating"
  | "conversation_rating"
  | "venue_rating"
  | "rejoin_intent"
  | "recommend_intent";
type Ratings = Record<RatingField, number>;
type Choice = "MEET_AGAIN" | "AVOID" | null;
type Tablemate = { user_id: string; display_name: string; preference: Choice };
type FeedbackState = {
  table_id: string;
  open: boolean;
  feedback: Ratings | null;
  tablemates: Tablemate[];
};

const FIELDS: { key: RatingField; label: string }[] = [
  { key: "table_rating", label: "테이블 전체 만족도" },
  { key: "conversation_rating", label: "대화 만족도" },
  { key: "venue_rating", label: "식당 만족도" },
  { key: "rejoin_intent", label: "재참여 의향" },
  { key: "recommend_intent", label: "추천 의향" },
];
const CHOICES: { value: Choice; label: string }[] = [
  { value: null, label: "선택 안 함" },
  { value: "MEET_AGAIN", label: "다시 만나고 싶어요" },
  { value: "AVOID", label: "다시 만나고 싶지 않아요" },
];

export function FeedbackSection({ tableId }: { tableId: string }) {
  const request = useScopedApi();
  const [state, setState] = useState<FeedbackState | null>(null);
  const [ratings, setRatings] = useState<Partial<Ratings>>({});
  const [loadError, setLoadError] = useState("");
  const [hidden, setHidden] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const alive = useRef(true);
  const path = `/api/me/tables/${tableId}`;
  useEffect(() => {
    alive.current = true;
    void request<FeedbackState>(`${path}/feedback`).then((result) => {
      if (!alive.current) return;
      setState(result);
      setRatings(result.feedback ?? {});
    }).catch((error: unknown) => {
      if (!alive.current) return;
      if (error instanceof ApiError && error.status === 404) setHidden(true);
      else setLoadError(message(error));
    });
    return () => { alive.current = false; };
  }, [path]);

  async function write(suffix: string, body: unknown, done: string) {
    if (pending) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      const result = await request<FeedbackState>(`${path}/${suffix}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      if (!alive.current) return;
      setState(result);
      setNotice(done);
    } catch (error) {
      if (!alive.current) return;
      setError(error instanceof ApiError && error.detail === "feedback_not_open"
        ? "모임이 끝난 뒤에 평가할 수 있습니다." : message(error));
    } finally {
      if (alive.current) setPending(false);
    }
  }
  function submitRatings(event: FormEvent) {
    event.preventDefault();
    if (FIELDS.some(({ key }) => !ratings[key])) {
      setError("다섯 항목을 모두 골라 주세요.");
      return;
    }
    void write("feedback", ratings, "평가를 저장했습니다. 언제든 수정할 수 있습니다.");
  }
  function choose(mate: Tablemate, choice: Choice) {
    if (choice === "AVOID" && !window.confirm(
      `${mate.display_name} 님과 다음 매칭에서 같은 테이블에 배정되지 않습니다. ` +
      "선택을 해제해도 이 분리는 유지됩니다. 계속할까요?")) return;
    void write("preferences", { preferences: [{ target_id: mate.user_id, choice }] },
      "선호를 저장했습니다. 상대에게는 공개되지 않습니다.");
  }

  if (hidden) return null;
  if (loadError) return <Notice error>{loadError}</Notice>;
  if (!state) return <Notice>평가 정보를 불러오고 있습니다.</Notice>;
  if (!state.open) return <Notice>모임이 끝나면 비공개 평가를 남길 수 있습니다.</Notice>;
  return <section className="panel" aria-label="모임 평가">
    <h3>모임 평가</h3>
    <p className="muted">평가와 선호는 운영과 다음 매칭에만 쓰이며 다른 참가자에게 공개되지 않습니다.
      남기지 않아도 다음 신청은 가능합니다.</p>
    {notice && <Notice>{notice}</Notice>}
    {error && <Notice error>{error}</Notice>}
    <form onSubmit={submitRatings}>
      <fieldset disabled={pending}>
        <legend>만족도와 의향 (1 낮음 ~ 5 높음)</legend>
        {FIELDS.map(({ key, label }) => <label key={key}>{label}
          <select value={ratings[key] ?? ""} required
            onChange={(event) => setRatings({ ...ratings, [key]: Number(event.target.value) })}>
            <option value="" disabled>선택</option>
            {[1, 2, 3, 4, 5].map((score) => <option key={score} value={score}>{score}</option>)}
          </select>
        </label>)}
        <button type="submit">{state.feedback ? "평가 수정" : "평가 저장"}</button>
      </fieldset>
    </form>
    {state.tablemates.length > 0 && <fieldset disabled={pending}>
      <legend>같은 테이블 참가자</legend>
      {state.tablemates.map((mate) => <div key={mate.user_id} role="radiogroup"
        aria-label={`${mate.display_name} 님에 대한 선호`}>
        <strong>{mate.display_name}</strong>
        {CHOICES.map((option) => <label key={option.value ?? "none"}>
          <input type="radio" name={`preference-${mate.user_id}`}
            checked={mate.preference === option.value}
            onChange={() => choose(mate, option.value)} />
          {option.label}
        </label>)}
      </div>)}
    </fieldset>}
  </section>;
}
