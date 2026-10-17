import { useEffect, useState } from "react";
import type { EventSlot } from "./api";
import { SlotSummary } from "./events";
import { message, Notice, useScopedApi } from "./ui";

// Ticket D CSV 내보내기 (operator-console-contract.md). Plain same-origin links: the
// session cookie authorizes the GET, and the server records each download in the audit.
const exportPath = (file: string, slotId: string) =>
  `/api/admin/exports/${file}?event_slot_id=${encodeURIComponent(slotId)}`;

export function ExportsSection() {
  const request = useScopedApi();
  const [slots, setSlots] = useState<EventSlot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    request<{ event_slots: EventSlot[] }>("/api/admin/event-slots")
      .then((result) => setSlots(result.event_slots))
      .catch((failure: unknown) => setError(message(failure)))
      .finally(() => setLoading(false));
  }, []);
  return (
    <section aria-labelledby="exports-title">
      <h2 id="exports-title">CSV 내보내기</h2>
      <p className="small muted">
        표시명과 내부 ID만 담습니다. 연락처·Instagram은 포함하지 않으며 내려받은
        기록은 감사 로그에 남습니다.
      </p>
      {error && <Notice error>{error}</Notice>}
      {loading ? (
        <Notice>회차를 확인하고 있습니다…</Notice>
      ) : slots.length ? (
        <ul className="participants" aria-label="내보낼 회차">
          {slots.map((slot) => (
            <li key={slot.id}>
              <SlotSummary slot={slot} />
              <p className="actions">
                <a href={exportPath("applications.csv", slot.id)} download>
                  신청 목록 CSV
                </a>
                <a href={exportPath("tables.csv", slot.id)} download>
                  테이블 CSV
                </a>
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <Notice>내보낼 회차가 없습니다.</Notice>
      )}
    </section>
  );
}
