---
status: accepted
---

# Railway 한 프로젝트에 앱과 PostgreSQL을 배포한다

TypeScript 화면 파일을 제공하는 FastAPI 앱과 PostgreSQL을 Railway 한 프로젝트에 배포한다. 별도 Vercel·Supabase를 두지 않고 인증과 채팅은 검증된 라이브러리를 활용해 앱 안에 구성한다. 앱과 DB는 별도 서비스이며 작업 실행기를 별도 서비스로 둘지는 아직 결정하지 않았다.

여러 플랫폼의 관리형 기능을 활용하는 안 대신 사용자가 원하는 배포 관리의 단순함을 선택했다. 그 대가로 인증·채팅의 권한 및 재연결, DB 백업·복원 설정과 검증은 프로젝트가 담당한다. 비용은 앱·DB·실행기의 사용량 합산이므로 월 3~5만원 목표를 첫 배포 후 측정한다. 실제 서비스 생성과 유료 플랜 가입은 아직 실행하지 않는다.

근거: [인터뷰 Q10 후속 — 배포 플랫폼 한 곳](../design/mvp-interview.md)의 추천에 대한 사용자 답변 “엉엉 그렇게 하자”. PostgreSQL과 FastAPI 배포는 Railway 공식 문서에서 확인했다. TypeScript와 FastAPI의 업무 책임은 ADR-0003을 유지한다.

후속 결정: ADR-0006에 따라 API와 작업 실행기를 별도 서비스로 실행한다. ADR-0005에 따라 React·Vite로 빌드한 CSR 화면을 API 앱이 제공한다.
