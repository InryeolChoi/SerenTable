import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError } from "./api";
import { show } from "./events";
import { message, Notice, useScopedApi } from "./ui";

type Room = {
  id: string;
  dining_table_id: string;
  member_count: number;
  starts_at: string;
  region_name: string;
};
type ChatMessage = {
  id: number;
  kind: "USER" | "SYSTEM";
  body: string;
  author: { display_name: string } | null;
  created_at: string;
};
type MessagePage = { messages: ChatMessage[]; next_cursor: number };

export function RoomsPage() {
  const request = useScopedApi();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void request<{ rooms: Room[] }>("/api/me/rooms").then((result) => {
      if (!active) return;
      setRooms(result.rooms);
      setSelected((previous) => result.rooms.some((room) => room.id === previous)
        ? previous : result.rooms[0]?.id ?? "");
    }).catch((error: unknown) => {
      if (active) setError(message(error));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);
  const room = rooms.find((item) => item.id === selected);
  return <section className="page-stack">
    <h1>단체방</h1>
    <p className="muted">확정된 식탁의 참가자와 인사를 나누세요.</p>
    {loading && <Notice>단체방을 불러오고 있습니다.</Notice>}
    {error && <><Notice error>{error}</Notice><button onClick={() => setReload((value) => value + 1)}>다시 불러오기</button></>}
    {!loading && !error && rooms.length === 0 && <Notice>확정된 단체방이 아직 없습니다.</Notice>}
    {rooms.length > 0 && <label>참여할 단체방
      <select value={selected} onChange={(event) => setSelected(event.target.value)}>
        {rooms.map((item) => <option key={item.id} value={item.id}>
          {show(item.starts_at)} · {item.region_name} · {item.member_count}인 확정
        </option>)}
      </select>
    </label>}
    {room && <RoomConversation key={room.id} room={room} />}
  </section>;
}

function RoomConversation({ room }: { room: Room }) {
  const request = useScopedApi();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [body, setBody] = useState("");
  const [pending, setPending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [connection, setConnection] = useState("대화를 불러오고 있습니다.");
  const [accessible, setAccessible] = useState(true);
  const alive = useRef(true);
  const submitting = useRef(false);
  const retry = useRef<{ body: string; request_key: string } | null>(null);
  const path = `/api/me/rooms/${room.id}/messages`;
  useEffect(() => {
    let active = true;
    let cursor = 0;
    let timer: ReturnType<typeof setTimeout>;
    alive.current = true;
    async function poll() {
      let delay = 2000;
      try {
        const page = await request<MessagePage>(`${path}?after_id=${cursor}&limit=100`);
        if (!active) return;
        cursor = page.next_cursor;
        setMessages((previous) => {
          const known = new Set(previous.map((item) => item.id));
          return [...previous, ...page.messages.filter((item) => !known.has(item.id))];
        });
        setConnection("연결됨 · 2초마다 새 대화를 확인합니다.");
        if (page.messages.length === 100) delay = 0;
      } catch (error) {
        if (!active) return;
        if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
          setAccessible(false);
          setConnection("단체방에 접근할 수 없습니다. 참여 상태와 로그인을 확인해 주세요.");
          return;
        }
        setConnection("연결이 끊겼습니다. 저장된 대화를 유지하며 다시 연결하고 있습니다.");
      }
      if (active) timer = setTimeout(() => { void poll(); }, delay);
    }
    void poll();
    return () => { active = false; alive.current = false; clearTimeout(timer); };
  }, [path]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting.current || !accessible || !body.length || body.length > 2000) return;
    submitting.current = true;
    setPending(true);
    setSendError("");
    const payload = retry.current?.body === body ? retry.current
      : { body, request_key: crypto.randomUUID() };
    retry.current = payload;
    try {
      await request<{ message: ChatMessage }>(path, { method: "POST", body: JSON.stringify(payload) });
      if (!alive.current) return;
      // The cursor poll remains the only ordered reader; sending never jumps it ahead.
      setBody("");
      retry.current = null;
    } catch (error) {
      if (alive.current) setSendError(message(error));
    } finally {
      submitting.current = false;
      if (alive.current) setPending(false);
    }
  }
  return <section className="panel" aria-label="단체방 대화">
    <h2>{room.region_name} · {room.member_count}인 확정</h2>
    <Notice>{connection}</Notice>
    <ol className="message-list" aria-label="메시지 목록">
      {messages.map((item) => <li key={item.id}>
        <strong>{item.author?.display_name ?? "식탁 안내"}</strong>{" "}
        <time dateTime={item.created_at}>{show(item.created_at)}</time>
        <p className="message-body">{item.body}</p>
      </li>)}
    </ol>
    {sendError && <Notice error>{sendError}</Notice>}
    <form onSubmit={(event) => { void submit(event); }}>
      <label>메시지
        <textarea value={body} maxLength={2000} required disabled={!accessible || pending}
          onChange={(event) => setBody(event.target.value)} />
      </label>
      <p className="small muted">{body.length}/2000자 · 연락처 등 개인정보 공유에 주의해 주세요.</p>
      <button disabled={pending || !accessible || !body.length}>{pending ? "보내는 중…" : "보내기"}</button>
    </form>
  </section>;
}
