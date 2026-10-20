import type { MatchRunMember, TableExplanation } from "./api";

const labels: Record<string, string> = {
  age: "연령", gender: "성비", mbti: "MBTI", interest: "관심사", trait: "성향", new: "새로운 사람",
  movies_drama: "영화·드라마", music: "음악", reading: "독서", writing: "글쓰기",
  exercise: "운동", food_cafes: "맛집·카페", travel: "여행", photo_video: "사진·영상",
  exhibitions_performances_art: "전시·공연·아트", fashion_beauty: "패션·뷰티",
  self_development_study: "자기계발·공부", similar: "비슷한 성향", different: "다른 성향",
  deep_conversation: "깊은 대화", comfortable_humor: "편안한 유머", calm_stable: "차분함·안정감",
  passionate: "열정",
};
const counts = (items: Record<string, number>) => Object.entries(items).map(([key, count]) => `${key} ${count}명`).join(" · ") || "기록 없음";

export function TableExplanationView({ explanation: e, components, year }: {
  explanation: TableExplanation | null;
  components: Record<string, string | null> | null;
  year: number;
}) {
  return <details className="small"><summary>확정 당시 구성과 점수 근거</summary>
    {e ? <>
      <p>출생연도 {e.birth_year_min}~{e.birth_year_max}년 · 회차 연도 기준 {year - e.birth_year_max}~{year - e.birth_year_min}세(생일 미반영)</p>
      <p>성비: {counts(e.gender_counts)} · 분류 불가 {e.gender_unknown_count}명</p>
      <p>MBTI: {counts(e.mbti_counts)} · 미기록 {e.mbti_unknown_count}명. 복수 선택은 중복 집계합니다.</p>
      <p>공유 관심사: {e.shared_interests.map(i => `${labels[i.code] ?? i.code} ${i.count}명`).join(" · ") || "없음"}</p>
      <p>이전 만남 {e.previous_pair_count}쌍 · 새로운 사람 점수에 반영 {e.newness_penalized_pair_count}쌍(상호 재만남 희망은 면제)</p>
    </> : <p>당시 구성 설명 미기록 · 현재 프로필로 소급 계산하지 않습니다.</p>}
    {components && <p>{Object.entries(components).map(([key, value]) => `${labels[key] ?? key} ${value ?? "계산 제외"}`).join(" · ")}</p>}
  </details>;
}

export function MemberExplanationView({ explanation: e }: { explanation: MatchRunMember["explanation"] }) {
  return e ? <p className="small">희망 성향별 충족: {Object.entries(e.trait_satisfaction).map(([key, value]) => `${labels[key] ?? key} ${value}%`).join(" · ") || "희망 성향 미기록"}
    {" · "}같은 테이블의 이전 만남 {e.previous_peer_count}명 · 동의한 대안 이동 {e.transfer_count}회
    <span className="muted"> (확정 당시, 상대별 평가 공개 없음)</span>
  </p> : <p className="small muted">당시 개인 설명 미기록</p>;
}
