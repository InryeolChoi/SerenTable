import { useEffect, useState, type FormEvent } from "react";
import { Notice, message, useScopedApi } from "./ui";
import { show } from "./events";
import type { EventSlot } from "./api";

type Venue = { name: string; address: string; map_url: string; price_krw: number; reservation_name: string };
type Gathering = { id: string; starts_at: string; region_name: string; venue: Venue | null };
type Inventory = Venue & { id: string; event_slot_id: string; capacity: number };
type Table = { id: string; event_slot_id: string; food_snapshot: string; food_clear: boolean; allocated_inventory_id: string | null; review_required: boolean; conditions: { user_id: string; meal_budget_bands: string[]; food_restrictions: {status: string; details?: string}; allergies: {status: string; details?: string} }[] };

const budgetLabels: Record<string, string> = { "10000_20000": "1~2만원", "20000_30000": "2~3만원", "30000_plus": "3만원 이상" };

export function GatheringsPage() {
  const request = useScopedApi();
  const [items, setItems] = useState<Gathering[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { void request<{gatherings: Gathering[]}>("/api/me/gatherings").then(r => setItems(r.gatherings)).catch(e => setError(message(e))); }, []);
  return <section><h1>모임 안내</h1>{error && <Notice error>{error}</Notice>}
    {!items.length && !error && <Notice>확정된 모임이 없습니다.</Notice>}
    {items.map(item => <article className="panel" key={item.id}>
      <h2>{show(item.starts_at)} · {item.region_name}</h2>
      {item.venue ? <><h3 className="venue-name">{item.venue.name}</h3><p>{item.venue.address}</p><p>예약명 {item.venue.reservation_name} · 예상 식비 {item.venue.price_krw.toLocaleString()}원</p><a className="venue-map" href={item.venue.map_url} target="_blank" rel="noopener noreferrer">식당 지도</a></> : <Notice>식당 배정은 운영자 확인 중입니다.</Notice>}
      <p>단체방에서 모임 안내와 대화 주제를 확인할 수 있습니다.</p>
    </article>)}
  </section>;
}

export function AdminVenuesPage() {
  const request = useScopedApi();
  const [slots, setSlots] = useState<EventSlot[]>([]);
  const [inventory, setInventory] = useState<Inventory[]>([]);
  const [tables, setTables] = useState<Table[]>([]);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState("");
  const [form, setForm] = useState({event_slot_id: "", name: "", address: "", map_url: "", price_krw: "15000", capacity: "6"});
  async function load() {
    const [s, v, t] = await Promise.all([
      request<{event_slots: EventSlot[]}>("/api/admin/event-slots"),
      request<{inventory: Inventory[]}>("/api/admin/venue-inventory"),
      request<{tables: Table[]}>("/api/admin/gathering-tables"),
    ]);
    setSlots(s.event_slots); setInventory(v.inventory); setTables(t.tables);
  }
  useEffect(() => { void load().catch(e => setError(message(e))); }, []);
  async function submit(e: FormEvent) {
    e.preventDefault(); setPending(true); setError(""); setSaved("");
    try {
      await request("/api/admin/venue-inventory", {method: "POST", body: JSON.stringify({...form, price_krw: Number(form.price_krw), capacity: Number(form.capacity)})});
      await load(); setSaved("가상 예약 재고를 등록했습니다. 다음 작업 실행에서 배정을 시도합니다.");
    } catch(e) { setError(message(e)); } finally {setPending(false);}
  }
  async function approve(v: Inventory, t: Table) {
    setPending(true); setError(""); setSaved("");
    try {
      await request(`/api/admin/venue-inventory/${v.id}/food-approvals`, {method: "POST", body: JSON.stringify({dining_table_id: t.id, food_snapshot: t.food_snapshot, confirmed_suitable: true})});
      await load();
      setSaved("현재 음식·알레르기·식비 조건의 적합성을 기록했습니다. 기존 배정은 유지하며 미배정은 다음 작업 실행에서 시도합니다.");
    } catch(e) {setError(message(e));} finally {setPending(false);}
  }
  return <section><h1>식당 배정 관리</h1><p>한 건은 해당 회차에서 예약 가능한 테이블 하나입니다. 실제 식당 예약을 실행하지 않습니다.</p>
    {error && <Notice error>{error}</Notice>}{saved && <Notice>{saved}</Notice>}
    <form className="operator-form" onSubmit={e => void submit(e)}>
      <label>회차<select required value={form.event_slot_id} onChange={e => setForm({...form, event_slot_id: e.target.value})}><option value="">회차 선택</option>{slots.map(s => <option key={s.id} value={s.id}>{show(s.starts_at)} · {s.region.name}</option>)}</select></label>
      {([['name','식당명'], ['address','주소'], ['map_url','HTTPS 지도 링크'], ['price_krw','1인 식비(원)'], ['capacity','좌석 수']] as const).map(([key,label]) => <label key={key}>{label}<input required value={form[key]} type={key === 'price_krw' || key === 'capacity' ? 'number' : 'text'} onChange={e => setForm({...form, [key]: e.target.value})} /></label>)}
      <button disabled={pending}>가상 재고 등록</button>
    </form>
    <h2>등록한 재고</h2>{inventory.map(v => <p key={v.id}>{v.name} · {v.price_krw.toLocaleString()}원 · {v.capacity}석</p>)}
    <h2>테이블 식사 조건 확인</h2><p>식당에 현재 음식·알레르기·식비 조건의 적합성을 직접 확인한 경우에만 확인 버튼을 누르십시오. 배정 뒤 조건이 바뀌면 예약을 유지하며 재검토합니다.</p>
    {tables.map(t => <article className="panel" key={t.id}><h3>테이블 {t.id.slice(0,8)}</h3>
      {t.review_required && <Notice>식사 조건 재검토가 필요합니다. 기존 예약은 유지됩니다.</Notice>}
      {t.food_clear && !t.review_required ? <p>전원 음식 제한·알레르기 없음</p> : <>{t.conditions.map(c => <p key={c.user_id}>음식 제한: {c.food_restrictions.details || c.food_restrictions.status} / 알레르기: {c.allergies.details || c.allergies.status} / 허용 식비: {c.meal_budget_bands.map(b => budgetLabels[b] ?? b).join(", ") || "미기록"}</p>)}{inventory.filter(v => v.event_slot_id === t.event_slot_id && (!t.allocated_inventory_id || v.id === t.allocated_inventory_id)).map(v => <button key={v.id} disabled={pending} onClick={() => void approve(v,t)}>{v.name} 적합성 확인 완료</button>)}</>}
    </article>)}
  </section>;
}
