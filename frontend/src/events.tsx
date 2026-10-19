import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, type EventSlot, type Region } from "./api";
import { message, Notice, useScopedApi } from "./ui";
import { AppDialog } from "./app-navigation";
import { SlotBrowser } from "./slot-browser";

// Operators enter Seoul wall-clock time; the API stores absolute instants.
const seoulInstant = (local: string) => `${local}:00+09:00`;
const dateTime = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  month: "long",
  day: "numeric",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const timeOnly = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
export const show = (iso: string) => dateTime.format(new Date(iso));

export function SlotSummary({ slot }: { slot: EventSlot }) {
  return (
    <>
      <strong>
        {show(slot.starts_at)} ~ {timeOnly.format(new Date(slot.ends_at))} ·{" "}
        {slot.region.name}
      </strong>
      <p className="small muted">
        신청 마감 {show(slot.closes_at)} · 매칭 예정 {show(slot.matches_at)} ·
        정원 {slot.capacity}명
      </p>
    </>
  );
}

const emptyForm = {
  region_code: "",
  starts_at: "",
  ends_at: "",
  closes_at: "",
  matches_at: "",
  capacity: "24",
};
type FormField = keyof typeof emptyForm;
type Problem = { field: FormField; message: string };
const fieldLabels: Record<FormField, string> = {
  region_code: "지역",
  starts_at: "시작 시각",
  ends_at: "종료 시각",
  closes_at: "신청 마감",
  matches_at: "매칭 예정",
  capacity: "정원",
};

export function AdminEventsPage() {
  const request = useScopedApi();
  const [regions, setRegions] = useState<Region[]>([]);
  const [slots, setSlots] = useState<EventSlot[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [problems, setProblems] = useState<Problem[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const inputs = useRef<Partial<Record<FormField, HTMLElement | null>>>({});
  async function load() {
    setLoading(true);
    setError("");
    try {
      const [regionList, slotList] = await Promise.all([
        request<{ regions: Region[] }>("/api/admin/regions"),
        request<{ event_slots: EventSlot[] }>("/api/admin/event-slots"),
      ]);
      setRegions(regionList.regions);
      setSlots(slotList.event_slots);
    } catch (error) {
      setError(message(error));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  // 제출을 막는 문제를 한 번에 모은다. 첫 문제만 알리면 나머지를 고친 뒤 다시 막힌다.
  function collectProblems(): Problem[] {
    const found: Problem[] = [];
    for (const name of Object.keys(emptyForm) as FormField[]) {
      if (!form[name]) found.push({ field: name, message: `${fieldLabels[name]}을 입력해 주세요.` });
    }
    if (found.length) return found;
    const at = (name: FormField) => new Date(seoulInstant(form[name]));
    if (!(at("starts_at") < at("ends_at")))
      found.push({ field: "ends_at", message: "종료 시각은 시작 시각보다 늦어야 합니다." });
    if (!(at("closes_at") <= at("matches_at") && at("matches_at") <= at("starts_at")))
      found.push({
        field: "matches_at",
        message: "신청 마감 ≤ 매칭 예정 ≤ 시작 시각 순서여야 합니다.",
      });
    return found;
  }
  const problemFor = (name: FormField) =>
    problems.find((problem) => problem.field === name)?.message;
  function edit(name: FormField, value: string) {
    setSaved("");
    setProblems((previous) => previous.filter((problem) => problem.field !== name));
    setForm({ ...form, [name]: value });
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    setSaved("");
    const found = collectProblems();
    if (found.length) {
      setProblems(found);
      setDialogOpen(true);
      return;
    }
    setProblems([]);
    setPending(true);
    setError("");
    try {
      const result = await request<{ event_slot: EventSlot }>(
        "/api/admin/event-slots",
        {
          method: "POST",
          body: JSON.stringify({
            region_code: form.region_code,
            starts_at: seoulInstant(form.starts_at),
            ends_at: seoulInstant(form.ends_at),
            closes_at: seoulInstant(form.closes_at),
            matches_at: seoulInstant(form.matches_at),
            capacity: Number(form.capacity),
          }),
        },
      );
      setForm(emptyForm);
      setSaved(
        `${show(result.event_slot.starts_at)} ${result.event_slot.region.name} 회차를 만들었습니다.`,
      );
      await load();
    } catch (error) {
      setError(
        error instanceof ApiError && error.status === 409
          ? "같은 지역·시작 시각의 회차가 이미 있습니다. 입력 내용은 유지됩니다."
          : message(error),
      );
    } finally {
      setPending(false);
    }
  }
  const fieldError = (name: FormField) => {
    const text = problemFor(name);
    return text ? <span className="field-error">{text}</span> : null;
  };
  const field = (name: FormField, title: string, hint: string) => (
    <label>
      {title}
      <span className="small muted">{hint}</span>
      <input
        ref={(element) => {
          inputs.current[name] = element;
        }}
        type="datetime-local"
        aria-label={title}
        aria-description={hint}
        aria-invalid={problemFor(name) ? true : undefined}
        value={form[name]}
        onChange={(e) => edit(name, e.target.value)}
      />
      {fieldError(name)}
    </label>
  );
  return (
    <section>
      <h1>모집 회차 관리</h1>
      <p className="lead">
        서울 4개 지역의 회차를 만듭니다. 시각은 모두 서울 기준입니다.
      </p>
      {error && <Notice error>{error}</Notice>}
      {saved && <Notice>{saved}</Notice>}
      {dialogOpen && (
        <AppDialog
          label="입력을 확인해 주세요"
          onClose={() => {
            setDialogOpen(false);
            const first = problems[0]?.field;
            if (first) inputs.current[first]?.focus();
          }}
        >
          <ul>
            {problems.map((problem) => (
              <li key={problem.field}>{problem.message}</li>
            ))}
          </ul>
        </AppDialog>
      )}
      <div className="admin-grid">
        <form aria-label="회차 만들기" onSubmit={create}>
          <fieldset disabled={pending || loading} className="form-body">
            <label>
              지역
              <select
                ref={(element) => {
                  inputs.current.region_code = element;
                }}
                aria-invalid={problemFor("region_code") ? true : undefined}
                value={form.region_code}
                onChange={(e) => edit("region_code", e.target.value)}
              >
                <option value="">지역 선택</option>
                {regions.map((region) => (
                  <option key={region.code} value={region.code}>
                    {region.name}
                  </option>
                ))}
              </select>
              {fieldError("region_code")}
            </label>
            {field("starts_at", "시작 시각", "모임이 시작하는 시각")}
            {field("ends_at", "종료 시각", "시작보다 늦어야 합니다")}
            {field("closes_at", "신청 마감", "지금 이후, 매칭 예정 이전")}
            {field("matches_at", "매칭 예정", "신청 마감 이후, 시작 이전")}
            <label>
              정원
              <span className="small muted">4~100명</span>
              <input
                ref={(element) => {
                  inputs.current.capacity = element;
                }}
                type="number"
                min={4}
                max={100}
                aria-invalid={problemFor("capacity") ? true : undefined}
                value={form.capacity}
                onChange={(e) => edit("capacity", e.target.value)}
              />
              {fieldError("capacity")}
            </label>
            <button className="primary" type="submit">
              {pending ? "만드는 중…" : "회차 만들기"}
            </button>
          </fieldset>
        </form>
        <div>
          <h2>회차 목록</h2>
          {loading ? (
            <Notice>회차를 확인하고 있습니다…</Notice>
          ) : slots.length ? (
            <ul className="participants" aria-label="회차 목록">
              {slots.map((slot) => (
                <li key={slot.id}>
                  <SlotSummary slot={slot} />
                  <p className="small muted">
                    {slot.recruiting ? "모집 중" : "모집 종료"}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p>아직 만든 회차가 없습니다.</p>
          )}
          <button onClick={() => void load()}>목록 새로고침</button>
        </div>
      </div>
    </section>
  );
}

export function ParticipantEventsPage() {
  const request = useScopedApi();
  const [slots, setSlots] = useState<EventSlot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  async function load() {
    setLoading(true);
    setError("");
    try {
      setSlots(
        (await request<{ event_slots: EventSlot[] }>("/api/event-slots"))
          .event_slots,
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
  return (
    <section className="narrow">
      <h1>모집 중인 회차</h1>
      <p className="lead">
        날짜·시간·지역과 신청 마감을 확인하세요. 시각은 서울 기준입니다.
      </p>
      <p className="muted">
        신청은 ‘일정 신청’ 화면에서 후보 회차를 골라 제출합니다.
      </p>
      {error && (
        <>
          <Notice error>{error}</Notice>
          <button onClick={() => void load()}>다시 불러오기</button>
        </>
      )}
      {loading ? (
        <Notice>회차를 확인하고 있습니다…</Notice>
      ) : slots.length ? (
        <SlotBrowser
          slots={slots}
          listLabel="모집 중인 회차"
          renderSlot={(slot) => <SlotSummary slot={slot} />}
        />
      ) : (
        !error && <p>현재 모집 중인 회차가 없습니다.</p>
      )}
    </section>
  );
}
