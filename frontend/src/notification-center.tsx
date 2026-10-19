import { useRef, useState } from "react";
import { AppDialog, AppIcon } from "./app-navigation";
import { NotificationsPanel } from "./notifications";

/** Opening notifications is local UI work; it never waits on the notification API. */
export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="icon-button notification-trigger"
        aria-label="알림"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setInitialized(true);
          setOpen(true);
        }}
      >
        <AppIcon name="bell" />
      </button>
      {initialized && (
        <AppDialog
          open={open}
          returnFocus={trigger}
          label="알림"
          onClose={() => setOpen(false)}
        >
          <NotificationsPanel />
        </AppDialog>
      )}
    </>
  );
}
