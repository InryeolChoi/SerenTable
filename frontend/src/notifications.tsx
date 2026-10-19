import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

type Notice = { id: string; title: string; body: string; url: string; created_at: string; read_at: string | null };
function applicationKey(value: string) {
  const raw = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
  return Uint8Array.from(raw, character => character.charCodeAt(0));
}
export function NotificationsPanel() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const reload = useCallback(async () => {
    try { setNotices((await api<{ notifications: Notice[] }>("/api/me/notifications")).notifications); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "알림을 불러오지 못했습니다."); }
  }, []);
  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => { if (!document.hidden) void reload(); }, 10000);
    return () => window.clearInterval(timer);
  }, [reload]);
  async function enablePush() {
    setBusy(true); setError("");
    try {
      if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
        setStatus("이 환경은 푸시를 지원하지 않습니다. 앱 내 알림은 계속 확인할 수 있습니다."); return;
      }
      const config = await api<{ public_key: string | null }>("/api/me/push-config");
      if (!config.public_key) { setStatus("서버 푸시 설정이 준비되지 않았습니다. 앱 내 알림을 확인해 주세요."); return; }
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setStatus(permission === "denied" ? "푸시 권한이 거부되었습니다. 브라우저 설정에서 변경할 수 있습니다." : "푸시 권한을 허용하지 않았습니다."); return;
      }
      const registration = await navigator.serviceWorker.register("/sw.js");
      await navigator.serviceWorker.ready;
      const existing = await registration.pushManager.getSubscription();
      const subscription = existing ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: applicationKey(config.public_key) });
      const result = await api<{id: string}>("/api/me/push-subscriptions", { method: "POST", body: JSON.stringify({ endpoint: subscription.endpoint, keys: subscription.toJSON().keys }) });
      // Only the nonsecret server id is retained; logout/account changes clear the UI instance.
      setSubscriptionId(result.id);
      setStatus("푸시 구독을 저장했습니다. 실제 기기 수신은 아직 확인되지 않았습니다.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "푸시 구독을 저장하지 못했습니다."); }
    finally { setBusy(false); }
  }
  const [subscriptionId, setSubscriptionId] = useState<string | null>(null);
  // On reopening, an existing browser subscription is re-saved (idempotent per endpoint)
  // so the unsubscribe button returns; another account's endpoint gets 409 and stays hidden.
  useEffect(() => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return;
    if (Notification.permission !== "granted") return;
    let cancelled = false;
    void (async () => {
      try {
        const registration = await navigator.serviceWorker.getRegistration("/sw.js");
        const subscription = await registration?.pushManager.getSubscription();
        if (!subscription) return;
        const result = await api<{id: string}>("/api/me/push-subscriptions", { method: "POST", body: JSON.stringify({ endpoint: subscription.endpoint, keys: subscription.toJSON().keys }) });
        if (!cancelled) setSubscriptionId(result.id);
      } catch { /* The allow button still works; nothing to show here. */ }
    })();
    return () => { cancelled = true; };
  }, []);
  async function disablePush() {
    setBusy(true); setError("");
    try {
      if (subscriptionId) await api(`/api/me/push-subscriptions/${subscriptionId}`, { method: "DELETE" });
      const registration = await navigator.serviceWorker.getRegistration("/sw.js");
      await (await registration?.pushManager.getSubscription())?.unsubscribe();
      setSubscriptionId(null); setStatus("푸시 구독을 해제했습니다. 앱 내 알림은 유지됩니다.");
    } catch { setError("구독 해제를 완료하지 못했습니다. 다시 시도해 주세요."); }
    finally { setBusy(false); }
  }
  return <section className="panel notifications-panel" aria-labelledby="notifications-heading">
    <h2 id="notifications-heading">알림</h2>
    <p>모임 안내는 앱 내 알림에 보관됩니다. 푸시는 이 기기에서 허용할 수 있습니다.</p>
    <button type="button" disabled={busy} onClick={() => void enablePush()}>이 기기 푸시 허용</button>
    {subscriptionId && <button type="button" disabled={busy} onClick={() => void disablePush()}>푸시 해제</button>}
    {status && <p className="notice" role="status">{status}</p>}{error && <p className="notice error" role="alert">{error}</p>}
    {notices.length === 0 && <p className="muted small">도착한 알림이 없습니다.</p>}
    <ul className="notification-list">{notices.map(notice => <li key={notice.id}>
      <strong>{notice.title}</strong><p>{notice.body}</p>
      <time dateTime={notice.created_at}>{new Date(notice.created_at).toLocaleString("ko-KR")}</time>
      {!notice.read_at && <button type="button" onClick={() => { void api(`/api/me/notifications/${notice.id}/read`, { method: "POST" }).then(reload).catch(() => setError("읽음 처리에 실패했습니다.")); }}>읽음으로 표시</button>}
    </li>)}</ul>
  </section>;
}
