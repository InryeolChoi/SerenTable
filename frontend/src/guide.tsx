import { useEffect, useState } from "react";
import { type User } from "./api";
import { AppDialog } from "./app-navigation";
import { GUIDE_EVENT } from "./ui";

// 처음 접속한 브라우저에 한 번 보여 주는 안내 카드. 건너뛸 수 있고 더보기에서 다시 연다.
//
// 표시 여부는 sessionStorage에 남긴다. localStorage는 쓰지 않는다. 이 앱은 "기기에 아무것도
// 남기지 않는다"를 계약으로 두고 e2e/shell.spec.ts가 localStorage가 비어 있음을 확인한다.
// 안내 카드 하나 때문에 그 계약을 느슨하게 만들지 않는다. 대신 브라우저를 닫으면 다시 뜬다.
// (최초 1회만 기억할지는 미결정 항목이다. ui-improvement-backlog.md 2번 참고.)
const STORAGE_KEY = "serentable.guide.v1";

function seen() {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    // 저장소를 쓸 수 없으면 매번 보여 준다.
    return false;
  }
}
function remember() {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, "1");
  } catch {
    // 저장 실패는 무시한다. 안내를 다시 보여 줄 뿐이다.
  }
}

const guide: Record<
  User["role"],
  { title: string; items: string[]; action: string; path: string }
> = {
  participant: {
    title: "우연한 식탁에 오신 것을 환영합니다",
    items: [
      "프로필과 동의를 마치면 모집 회차를 신청할 수 있습니다.",
      "결제는 모의 결제이며 실제 결제가 발생하지 않습니다.",
      "매칭이 확정되면 모임 안내와 단체방이 열립니다.",
      "합성 계정으로 보는 심사용 화면입니다. 실제 개인정보를 입력하지 마세요.",
    ],
    action: "프로필 작성하기",
    path: "/participant/profile",
  },
  operator: {
    title: "운영자 화면 안내",
    items: [
      "회차를 만들고 그 회차의 가상 식당 재고를 등록합니다.",
      "매칭은 신청 마감 뒤 작업 실행기가 자동으로 처리합니다.",
      "운영 현황에서 예외·노쇼 후보와 처리 이력을 확인합니다.",
      "화면의 값은 모두 합성 데이터입니다.",
    ],
    action: "회차 만들기",
    path: "/admin/events",
  },
};

export function FirstVisitGuide({
  user,
  navigate,
}: {
  user: User;
  navigate: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    setOpen(!seen());
  }, [user.id]);
  useEffect(() => {
    const reopen = () => setOpen(true);
    window.addEventListener(GUIDE_EVENT, reopen);
    return () => window.removeEventListener(GUIDE_EVENT, reopen);
  }, []);
  function close() {
    remember();
    setOpen(false);
  }
  if (!open) return null;
  const step = guide[user.role];
  return (
    <AppDialog label={step.title} onClose={close}>
      <ul>
        {step.items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <div className="actions">
        <button
          type="button"
          className="primary"
          onClick={() => {
            close();
            navigate(step.path);
          }}
        >
          {step.action}
        </button>
        <button type="button" onClick={close}>
          건너뛰기
        </button>
      </div>
    </AppDialog>
  );
}
