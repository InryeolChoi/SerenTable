import { Component, type ReactNode } from "react";
import { Notice } from "./ui";

/** A failed optional screen bundle must leave the app's navigation usable. */
export class ScreenLoadBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed)
      return (
        <section>
          <h1>운영 현황</h1>
          <Notice error>
            화면을 불러오지 못했습니다. 연결을 확인한 뒤 새로고침하거나 다른
            메뉴로 이동해 주세요.
          </Notice>
          <button type="button" onClick={() => window.location.reload()}>
            화면 새로고침
          </button>
        </section>
      );
    return this.props.children;
  }
}
