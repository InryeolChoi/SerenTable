import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import type { User } from "./api";

type IconName =
  | "table"
  | "calendar"
  | "pin"
  | "chat"
  | "more"
  | "people"
  | "overview"
  | "shield"
  | "bell"
  | "close";
const paths: Record<IconName, ReactNode> = {
  table: (
    <>
      <circle cx="12" cy="12" r="5" />
      <path d="M8 2h8M8 22h8M2 8v8M22 8v8" />
    </>
  ),
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <path d="M7 2v6M17 2v6M3 11h18M8 15h2M14 15h2" />
    </>
  ),
  pin: (
    <>
      <path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z" />
      <circle cx="12" cy="10" r="2" />
    </>
  ),
  chat: (
    <path d="M21 11a8 8 0 0 1-8 8H8l-5 3V11a9 9 0 0 1 18 0ZM7 10h10M7 14h6" />
  ),
  more: (
    <>
      <circle cx="5" cy="12" r="1" />
      <circle cx="12" cy="12" r="1" />
      <circle cx="19" cy="12" r="1" />
    </>
  ),
  people: (
    <>
      <circle cx="9" cy="7" r="3" />
      <path d="M2 21v-3a7 7 0 0 1 14 0v3M17 4a3 3 0 0 1 0 6M19 14a5 5 0 0 1 3 5v2" />
    </>
  ),
  overview: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="2" />
      <rect x="14" y="3" width="7" height="11" rx="2" />
      <rect x="3" y="14" width="7" height="7" rx="2" />
      <path d="M14 18h7M14 21h7" />
    </>
  ),
  shield: (
    <>
      <path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Z" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  bell: (
    <>
      <path d="M18 8a6 6 0 0 0-12 0c0 8-3 8-3 10h18c0-2-3-2-3-10ZM9 21h6" />
    </>
  ),
  close: <path d="m6 6 12 12M18 6 6 18" />,
};

export function AppIcon({ name }: { name: IconName }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

export function AppDialog({
  label,
  onClose,
  returnFocus,
  open = true,
  children,
}: {
  label: string;
  onClose: () => void;
  returnFocus?: RefObject<HTMLButtonElement | null>;
  open?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) {
      dialog.close();
      returnFocus?.current?.focus({ preventScroll: true });
    }
  }, [open, returnFocus]);
  useEffect(() => {
    const dialog = ref.current!;
    return () => {
      if (dialog.open) dialog.close();
      returnFocus?.current?.focus({ preventScroll: true });
    };
  }, [returnFocus]);
  return (
    <dialog
      ref={ref}
      className="app-dialog"
      aria-label={label}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          const box = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < box.left ||
            event.clientX > box.right ||
            event.clientY < box.top ||
            event.clientY > box.bottom
          )
            onClose();
        }
      }}
    >
      <div className="dialog-toolbar">
        <h2>{label}</h2>
        <button
          type="button"
          className="icon-button"
          aria-label={`${label} 닫기`}
          onClick={onClose}
        >
          <AppIcon name="close" />
        </button>
      </div>
      {children}
    </dialog>
  );
}

type Destination = {
  path: string;
  label: string;
  icon: IconName;
  matches?: (path: string) => boolean;
};
const participant: Destination[] = [
  { path: "/participant", label: "내 식탁", icon: "table" },
  {
    path: "/participant/events",
    label: "모집 회차",
    icon: "calendar",
    matches: (path) =>
      path === "/participant/events" ||
      path.startsWith("/participant/apply") ||
      path.startsWith("/participant/payment/"),
  },
  { path: "/participant/gatherings", label: "모임 안내", icon: "pin" },
  { path: "/participant/rooms", label: "단체방", icon: "chat" },
];
const operator: Destination[] = [
  { path: "/admin", label: "참가자 관리", icon: "people" },
  { path: "/admin/console", label: "운영 현황", icon: "overview" },
  { path: "/admin/events", label: "회차 관리", icon: "calendar" },
  { path: "/admin/safety", label: "안전·노쇼", icon: "shield" },
];
const participantMore = [
  {
    path: "/participant/profile",
    label: "프로필",
    description: "나의 정보와 관심사",
  },
  {
    path: "/participant/consent",
    label: "동의",
    description: "개인정보와 운영 정책",
  },
  {
    path: "/participant/history",
    label: "참가 이력",
    description: "지난 식탁과 다음 만남",
  },
  {
    path: "/participant/apply",
    label: "일정 신청",
    description: "참여 가능한 일정 선택",
  },
];
const operatorMore = [
  {
    path: "/admin/venues",
    label: "식당 배정",
    description: "식당 재고와 배정 확인",
  },
  {
    path: "/admin/applications",
    label: "신청 현황",
    description: "신청·결제·매칭 이력",
  },
];
export function AppNavigation({
  user,
  path,
  navigate,
}: {
  user: User;
  path: string;
  navigate: (path: string) => void;
}) {
  const [moreOpen, setMoreOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const destinations = user.role === "operator" ? operator : participant;
  const extra = user.role === "operator" ? operatorMore : participantMore;
  const isActive = (item: Destination) =>
    item.matches
      ? item.matches(path)
      : item.path === path ||
        (path === "/" &&
          item.path === (user.role === "operator" ? "/admin" : "/participant"));
  const extraActive =
    !destinations.some(isActive) && extra.some((item) => item.path === path);
  return (
    <>
      <nav className="app-navigation" aria-label="주요 화면">
        {destinations.map((item) => (
          <a
            key={item.path}
            href={item.path}
            aria-current={isActive(item) ? "page" : undefined}
            onClick={(event) => {
              if (
                !event.metaKey &&
                !event.ctrlKey &&
                !event.shiftKey &&
                !event.altKey &&
                event.button === 0
              ) {
                event.preventDefault();
                navigate(item.path);
              }
            }}
          >
            <AppIcon name={item.icon} />
            <span>{item.label}</span>
          </a>
        ))}
        <button
          ref={trigger}
          type="button"
          aria-haspopup="dialog"
          aria-expanded={moreOpen}
          aria-current={extraActive ? "page" : undefined}
          onClick={() => setMoreOpen(true)}
        >
          <AppIcon name="more" />
          <span>더보기</span>
        </button>
      </nav>
      {moreOpen && (
        <AppDialog
          label="더보기"
          returnFocus={trigger}
          onClose={() => setMoreOpen(false)}
        >
          <p className="menu-account">
            {user.login_id} · {user.role === "operator" ? "운영자" : "참가자"}
          </p>
          <nav className="more-navigation" aria-label="더보기 화면">
            {extra.map((item) => (
              <a
                key={item.path}
                href={item.path}
                aria-label={item.label}
                aria-description={item.description}
                aria-current={path === item.path ? "page" : undefined}
                onClick={(event) => {
                  if (
                    !event.metaKey &&
                    !event.ctrlKey &&
                    !event.shiftKey &&
                    !event.altKey &&
                    event.button === 0
                  ) {
                    event.preventDefault();
                    setMoreOpen(false);
                    navigate(item.path);
                  }
                }}
              >
                <span>
                  {item.label}
                  <small>{item.description}</small>
                </span>
                <span aria-hidden="true">›</span>
              </a>
            ))}
          </nav>
        </AppDialog>
      )}
    </>
  );
}
