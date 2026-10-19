import { useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { EventSlot } from "./api";

// Group by Seoul wall-clock date, including slots just after midnight.
const seoulDate = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
function dateKey(value: string) {
  const parts = seoulDate.formatToParts(new Date(value));
  return ["year", "month", "day"]
    .map((type) => parts.find((p) => p.type === type)!.value)
    .join("-");
}

/** Both views render the same candidates. Selection remains owned by ApplyPage. */
export function SlotBrowser({
  slots,
  renderSlot,
  listLabel,
}: {
  slots: EventSlot[];
  renderSlot: (slot: EventSlot) => ReactNode;
  listLabel: string;
}) {
  const [view, setView] = useState<"list" | "calendar">("list");
  const keys = slots.map((slot) => dateKey(slot.starts_at)).sort();
  const [month, setMonth] = useState(() =>
    (keys[0] ?? dateKey(new Date().toISOString())).slice(0, 7),
  );
  const [selected, setSelected] = useState<string | null>(null);
  const touchX = useRef<number | null>(null);
  const bubbleId = useId();
  const grid = useRef<HTMLDivElement>(null);
  // Placed above the date when the grid has room there; dates in the top rows open below so
  // the bubble never covers the view switch and month controls above the grid.
  const [anchor, setAnchor] = useState<{ x: number; y: number; left: number; width: number; room: number; below: boolean } | null>(null);
  useLayoutEffect(() => {
    const host = grid.current;
    if (!selected || view !== "calendar" || !host) return;
    function measure() {
      const button = host!.querySelector<HTMLButtonElement>(`button[data-date="${selected}"]`);
      if (!button) return;
      const rect = button.getBoundingClientRect();
      const bounds = host!.getBoundingClientRect();
      const width = Math.min(bounds.width, 350);
      const x = rect.left - bounds.left + rect.width / 2;
      const below = rect.top - bounds.top < 200;
      const next = {
        x, y: below ? rect.bottom - bounds.top : rect.top - bounds.top, width, below,
        left: Math.max(0, Math.min(x - width / 2, bounds.width - width)),
        room: Math.max(64, Math.min(240, below ? window.innerHeight - rect.bottom - 220 : rect.top - 200)),
      };
      setAnchor(current => current && Object.keys(next).every(key => current[key as keyof typeof next] === next[key as keyof typeof next]) ? current : next);
    }
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    window.addEventListener("scroll", measure, { passive: true, capture: true });
    return () => { observer.disconnect(); window.removeEventListener("scroll", measure, true); };
  }, [selected, view, month]);
  function closeBubble() {
    grid.current?.querySelector<HTMLButtonElement>(`button[data-date="${selected}"]`)?.focus({ preventScroll: true });
    setSelected(null);
  }
  const [year, monthNumber] = month.split("-").map(Number);
  const firstWeekday = new Date(Date.UTC(year, monthNumber - 1, 1)).getUTCDay();
  const days = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  function move(delta: number) {
    const date = new Date(Date.UTC(year, monthNumber - 1 + delta, 1));
    setMonth(
      `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`,
    );
    setSelected(null);
  }
  const selectedSlots = slots.filter(
    (slot) => dateKey(slot.starts_at) === selected,
  );
  return (
    <div className="slot-browser">
      <div
        className={`view-switch ${view === "calendar" ? "is-calendar" : ""}`}
        role="group"
        aria-label="회차 보기 방식"
        onTouchStart={(event) => {
          touchX.current = event.touches[0]?.clientX ?? null;
        }}
        onTouchEnd={(event) => {
          const end = event.changedTouches[0]?.clientX;
          if (
            touchX.current !== null &&
            end !== undefined &&
            Math.abs(end - touchX.current) > 32
          ) {
            setView(end < touchX.current ? "calendar" : "list");
          }
          touchX.current = null;
        }}
      >
        <button
          type="button"
          aria-label="목록 보기"
          aria-pressed={view === "list"}
          onClick={() => setView("list")}
        >
          목록
        </button>
        <button
          type="button"
          aria-label="달력 보기"
          aria-pressed={view === "calendar"}
          onClick={() => setView("calendar")}
        >
          달력
        </button>
      </div>
      {view === "list" ? (
        <ul className="slot-options participants" aria-label={listLabel}>
          {slots.map((slot) => (
            <li key={slot.id}>{renderSlot(slot)}</li>
          ))}
        </ul>
      ) : (
        <div className="calendar">
          <div className="calendar-heading">
            <button type="button" aria-label="이전 달" onClick={() => move(-1)}>
              ‹
            </button>
            <h3 aria-live="polite">
              {year}년 {monthNumber}월
            </h3>
            <button type="button" aria-label="다음 달" onClick={() => move(1)}>
              ›
            </button>
          </div>
          <div className="calendar-weekdays" aria-hidden="true">
            {["일", "월", "화", "수", "목", "금", "토"].map((day) => (
              <span key={day}>{day}</span>
            ))}
          </div>
          <div
            ref={grid}
            className="calendar-days"
            onKeyDown={event => { if (event.key === "Escape" && selected) { event.stopPropagation(); closeBubble(); } }}
            role="group"
            aria-label={`${year}년 ${monthNumber}월 날짜`}
          >
            {Array.from({ length: firstWeekday }, (_, index) => (
              <span key={`empty-${index}`} />
            ))}
            {Array.from({ length: days }, (_, index) => {
              const day = index + 1;
              const key = `${month}-${String(day).padStart(2, "0")}`;
              const available = keys.includes(key);
              return (
                <button
                  type="button"
                  key={key}
                  data-date={key}
                  disabled={!available}
                  aria-label={`${year}년 ${monthNumber}월 ${day}일, ${available ? "회차 있음" : "모집 없음"}`}
                  aria-pressed={selected === key}
                  aria-expanded={selected === key}
                  aria-controls={selected === key ? bubbleId : undefined}
                  onClick={() => setSelected(selected === key ? null : key)}
                >
                  {day}
                  {available && <span className="calendar-dot" />}
                </button>
              );
            })}
          {selected && anchor && selectedSlots.length > 0 && (
            <section
              className="calendar-bubble"
              id={bubbleId}
              data-placement={anchor.below ? "below" : "above"}
              style={{ left: anchor.left, width: anchor.width, top: anchor.below ? anchor.y + 10 : undefined, bottom: anchor.below ? undefined : `calc(100% - ${anchor.y}px + 10px)`, "--bubble-tail": `${anchor.x - anchor.left}px`, "--bubble-room": `${anchor.room}px` } as CSSProperties}
              aria-label="선택한 날짜의 회차"
            >
              <div className="calendar-bubble-heading">
                <strong>
                  {Number(selected.slice(5, 7))}월 {Number(selected.slice(8))}일
                </strong>
                <button
                  type="button"
                  aria-label="날짜 회차 닫기"
                  onClick={closeBubble}
                >
                  닫기
                </button>
              </div>
              <ul className="slot-options">
                {selectedSlots.map((slot) => (
                  <li key={slot.id}>{renderSlot(slot)}</li>
                ))}
              </ul>
            </section>
          )}
          </div>
          <p className="small muted">
            점이 있는 날짜에 신청할 수 있는 회차가 있습니다.
          </p>
        </div>
      )}
    </div>
  );
}
