/* Lock screens receive generic guidance only; ignore provider-supplied display data and URLs. */
self.addEventListener("push", event => {
  event.waitUntil(self.registration.showNotification("우연한 식탁", {
    body: "새 안내가 도착했습니다. 앱에서 확인해 주세요.",
    tag: "serentable-guidance",
    data: { url: "/participant/gatherings" },
  }));
});
self.addEventListener("notificationclick", event => {
  event.notification.close();
  const target = new URL("/participant/gatherings", self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async windows => {
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin) {
        await client.navigate(target); return client.focus();
      }
    }
    return self.clients.openWindow(target);
  }));
});
