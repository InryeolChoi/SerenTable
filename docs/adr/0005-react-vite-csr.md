---
status: accepted
---

# React와 Vite로 CSR 화면을 만들고 FastAPI가 제공한다

참가자·운영자 화면은 React + TypeScript + Vite로 작성해 정적 파일로 빌드하고, FastAPI가 화면 파일과 업무 API를 같은 앱 주소에서 제공한다. 브라우저가 화면을 그리는 CSR이며 별도 Node SSR 서버를 두지 않는다.

업무 화면 중심의 심사용 MVP에서 화면 서버를 추가하는 대신 Railway 배포 구성을 줄인다. 첫 화면 로딩, 경로 새로고침, 로그인 상태와 모바일 UX는 직접 검증하며, 공개 콘텐츠의 검색 노출 최적화보다 P0 흐름에 집중한다. 근거: [인터뷰 Q12](../design/mvp-interview.md), 사용자 답변 “A”.
