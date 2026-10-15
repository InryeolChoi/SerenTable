import { createRoot } from 'react-dom/client';
import './style.css';

const path = window.location.pathname;
const area = path === '/admin' ? '운영자 화면' : path === '/participant' ? '참가자 화면' : '우연한 식탁';

createRoot(document.getElementById('root')!).render(
  <main>
    <h1>{area}</h1>
    <p>처음 만나는 사람들과 함께하는 한 끼</p>
    <section aria-labelledby="preparing">
      <h2 id="preparing">서비스 준비 중</h2>
      <p>아직 신청과 로그인 기능을 제공하지 않습니다.</p>
      <p>참가자와 운영자 화면을 준비하고 있습니다.</p>
    </section>
    <nav aria-label="화면 선택">
      <a href="/">홈</a>
      <a href="/participant" aria-current={path === '/participant' ? 'page' : undefined}>참가자 화면</a>
      <a href="/admin" aria-current={path === '/admin' ? 'page' : undefined}>운영자 화면</a>
    </nav>
  </main>
);
