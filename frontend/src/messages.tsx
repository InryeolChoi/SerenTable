import { useEffect, useState } from "react";
import { Notice, message, useScopedApi } from "./ui";
import { show } from "./events";

// PRD §11·§17 "테이블 상세"·"자동 메시지 관리". 읽기 전용이며 수동 발송·수정은 없다.
type TableDetail = {
  id: string;
  starts_at: string;
  region_name: string;
  member_count: number;
  members: string[];
  venue: { name: string; reservation_name: string } | null;
  room_id: string | null;
  message_count: number;
  notices: Record<string, number>;
};
type Template = { kind: string; name: string; trigger: string; channels: string };
type Sent = {
  id: string;
  kind: string;
  title: string;
  body: string;
  login_id: string;
  created_at: string;
  read: boolean;
  push_status: string;
};

const pushLabels: Record<string, string> = {
  accepted: "푸시 전달",
  pending: "푸시 대기",
  failed: "푸시 실패",
  unavailable: "푸시 불가",
  not_subscribed: "앱 알림만",
};
const pushSummary = (counts: Record<string, number>) =>
  Object.entries(counts)
    .map(([state, count]) => `${pushLabels[state] ?? state} ${count}`)
    .join(" · ") || "발송 기록 없음";

export function AdminMessagesPage() {
  const request = useScopedApi();
  const [tables, setTables] = useState<TableDetail[] | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [history, setHistory] = useState<Sent[]>([]);
  const [error, setError] = useState("");
  async function load() {
    setError("");
    try {
      const [t, m] = await Promise.all([
        request<{ tables: TableDetail[] }>("/api/admin/table-details"),
        request<{ templates: Template[]; history: Sent[] }>("/api/admin/messages"),
      ]);
      setTables(t.tables);
      setTemplates(m.templates);
      setHistory(m.history);
    } catch (e) {
      setError(message(e));
    }
  }
  useEffect(() => {
    void load();
  }, []);
  const names = Object.fromEntries(templates.map((t) => [t.kind, t.name]));
  return (
    <section className="page-stack">
      <h1>테이블·메시지</h1>
      <p className="lead">
        확정된 테이블의 구성·식당·단체방과 자동 메시지 발송 기록입니다. 모두
        자동으로 처리되며 이 화면은 읽기 전용입니다.
      </p>
      {error && <Notice error>{error}</Notice>}
      <section>
        <h2>테이블 상세</h2>
        {!tables ? (
          !error && <Notice>테이블을 확인하고 있습니다…</Notice>
        ) : tables.length ? (
          <ul className="participants" aria-label="테이블 상세 목록">
            {tables.map((t) => (
              <li key={t.id}>
                <strong>
                  {show(t.starts_at)} · {t.region_name} · {t.member_count}명
                </strong>
                <p className="small">참가자: {t.members.join(", ")}</p>
                <p className="small">
                  식당:{" "}
                  {t.venue
                    ? `${t.venue.name} · 예약명 ${t.venue.reservation_name}`
                    : "배정 대기(운영자 확인 필요)"}
                </p>
                <p className="small">
                  단체방: {t.room_id ? `개설 · 메시지 ${t.message_count}건` : "미개설"}{" "}
                  · 안내 발송: {pushSummary(t.notices)}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p>확정된 테이블이 없습니다.</p>
        )}
      </section>
      <section>
        <h2>자동 메시지</h2>
        <p className="small muted">
          문구는 시스템이 상태에 맞춰 만듭니다. 잠금화면 푸시에는 일반 안내만
          보이고 상세 내용은 앱 안에서만 보입니다.
        </p>
        <table className="message-templates" aria-label="자동 메시지 종류">
          <thead>
            <tr>
              <th>메시지</th>
              <th>발송 시점</th>
              <th>채널</th>
            </tr>
          </thead>
          <tbody>
            {templates.map((t) => (
              <tr key={t.kind}>
                <td>{t.name}</td>
                <td>{t.trigger}</td>
                <td>{t.channels}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3>최근 발송 이력</h3>
        {history.length ? (
          <ul className="participants" aria-label="자동 메시지 발송 이력">
            {history.map((h) => (
              <li key={h.id}>
                <strong>{names[h.kind] ?? h.kind}</strong>{" "}
                <span className="small muted">
                  {h.login_id} · {show(h.created_at)} ·{" "}
                  {pushLabels[h.push_status] ?? h.push_status} ·{" "}
                  {h.read ? "읽음" : "안 읽음"}
                </span>
                <p className="small">{h.body}</p>
              </li>
            ))}
          </ul>
        ) : (
          tables && <p>아직 발송된 메시지가 없습니다.</p>
        )}
        <button onClick={() => void load()}>새로고침</button>
      </section>
    </section>
  );
}
