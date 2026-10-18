# 매칭 100명 측정 결과 (2026-10-19)

Work #10의 "100명 측정" 부분이다. [구현 명세](mvp-implementation-spec.md) 6절 12항과 검증 1절의 "실행당 100명에서 필수조건 위반·중복 배치·참가자 누락·성공률·실행 시간·자원 사용량을 측정한다"를 실제 계획기로 측정한 기록이다. 수용할 시간·메모리·최적해 차이의 수치는 여전히 미정이며 이 문서는 새 합격 기준을 만들지 않는다. ADR-0011(U06)의 100명 5초는 목표로만 대조한다. 100명 초과 입력 정책(U19)은 다루지 않는다.

## 측정 환경

| 항목 | 값 |
|---|---|
| 기준 커밋 | `b5f1525c7c02` (`origin/codex/work7-gathering-integration`) 위에 측정 스크립트만 추가, 제품 코드 변경 없음 |
| 기계 | `uname -m` = arm64 (macOS, 로컬 개발 기계) |
| Python | 3.12.12 (`uv run`) |
| 정책 | `DEFAULT_POLICY` (`prd-weighted-v1`, 최소 점수 60) — 작업기가 `MATCHING_MIN_SCORE` 미설정 시 쓰는 값과 같다 |
| 명령 | `PYTHONPATH=backend uv run python scripts/measure_matching_scale.py --seeds 5 --json` (종료 코드 0, 전체 약 138초) |

## 방법

- `scripts/measure_matching_scale.py`가 시드로 100명 합성 풀을 결정적으로 만든다. `data/` 원본·개인정보는 읽지 않고 집계만 출력한다.
- 각 풀에 작업기와 같은 호출 `plan_allocation(roster, capacity, policy=DEFAULT_POLICY, exclusions, met_pairs)`를 실행한다.
- 실행 시간: `time.perf_counter`로 같은 입력을 두 번 측정한다. 두 실행의 배정이 같아야 "결정적"으로 본다.
- 메모리: 세 번째 실행을 `tracemalloc`으로 감싸 최대 추적 메모리를 잰다. 프로세스 최대 RSS도 함께 기록한다.
- 독립 검사:
  - 필수조건: `tests/oracle/hard_constraints.validate_assignment` (4~6명, 결제·동의, 출생연도 차 8 이하, 제외 쌍, 이중 배치).
  - 최소 점수: `tests/oracle/scoring.validate_allocation` (독립 점수 구현으로 모든 테이블 ≥ 60, 정원 초과 없음).
  - 중복 좌석, 참가자 누락(입력 신청이 배정·미배정 어디에도 없음), 중복 집계, 입력에 없는 신청 출력.
- 비교 기준: 구성 형태는 "증인 배정이 존재하고 상한과 같은" 기지 최적값, 나머지는 계획기와 무관한 상한 `min(정원, 9년 창 안에 4명 이상이 있는 출생연도 기지자 수)`. 상한은 점수·제외 쌍을 고려하지 않아 느슨하다.

## 형태

| 형태 | 구성 | 비교 기준 |
|---|---|---|
| uniform_random | 무작위 속성, 출생연도 1985~2004, 만난 쌍 30개 | 상한 |
| skewed_gender_age | 한 성별 85%, 70%가 1996~1999, 60%가 인기 관심사 2개 | 상한 |
| two_age_groups | 1990년생 50 + 2005년생 50(혼합 불가), 동일 선호, 제출 순서 섞음 | 기지 최적 100 |
| dense_exclusions | 동갑 100명, 증인 20×5 분할 밖 쌍의 30%(약 1,400쌍) 제외 | 기지 최적 100 |
| isolated_and_unknown_age | 동갑 92 + 고립 3명(차 > 8) + 출생연도 없음 5명 | 기지 최적 92 |
| capacity_limited | 1993/1994년생 100명, 정원 62 | 기지 최적 62 |

동일 선호 형태는 어떤 나이 유효 테이블도 70점 이상이 되도록 만들어 최소 점수가 기지 최적을 바꾸지 않는다.

## 결과 (형태당 시드 5개, 총 30회)

| 형태 | 회 | 검사 통과 | 중앙값 s | 최대 s | 최대 추적 MiB | 배정 | 기준 | 최대 차이 | 위반 | 중복 | 누락 | 탐색 중단 | 5초 초과 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| uniform_random | 5 | 5 | 0.525 | 1.521 | 11.49 | 100 | 100 (상한) | 0 | 0 | 0 | 0 | 0 | 0 |
| skewed_gender_age | 5 | 5 | 0.972 | 2.861 | 14.38 | 94~98 | 100 (상한) | 6 | 0 | 0 | 0 | 0 | 0 |
| two_age_groups | 5 | 5 | 0.563 | 0.602 | 9.54 | 100 | 100 (기지 최적) | 0 | 0 | 0 | 0 | 0 | 0 |
| dense_exclusions | 5 | 5 | 0.220 | 0.240 | 20.24 | 100 | 100 (기지 최적) | 0 | 0 | 0 | 0 | 0 | 0 |
| isolated_and_unknown_age | 5 | 5 | 0.847 | 0.894 | 11.65 | 92 | 92 (기지 최적) | 0 | 0 | 0 | 0 | 0 | 0 |
| capacity_limited | 5 | 5 | 0.989 | 1.658 | 10.33 | 62 | 62 (기지 최적) | 0 | 0 | 0 | 0 | 0 | 0 |

- 30회 모두 필수조건·최소 점수 위반 0, 중복 좌석 0, 누락 0, 결정적. 모든 테이블 4~6명.
- 최대 실행 시간 2.861초(ADR 5초 목표 초과 0회). 최대 추적 메모리 20.24 MiB, 프로세스 최대 RSS 145.8 MiB(인터프리터·모듈 포함).
- 기지 최적이 있는 4형태 20회는 모두 최적값에 도달했다. skewed_gender_age의 차이 2~6명은 느슨한 상한 대비이며 실제 최적 차이인지는 알 수 없다(미배정 이유는 모두 `no_qualifying_table`).
- 기존 종단 시험 `tests/test_matching_scale.py`(실제 PostgreSQL·HTTP·별도 작업기 `--once`, 50+50 두 나이 집단): 1 passed, 52.9초(대부분 마감 대기). 작업기 프로세스 시간 `synthetic_100_worker_seconds=1.198`, 18테이블, 100명 배정, 독립 검사 위반 0.

## 관찰

1. **실행 속도에 따른 결과 변화.** skewed_gender_age 시드 0은 일반 실행 2.85초에 96명이지만, `tracemalloc`으로 약 2배 느려진 실행은 계획기의 5초 벽시계 보호(`SEARCH_SECONDS`)에 걸려 탐색이 중단되고 76명만 배정했다(`search_complete=False`, 위반은 없음). 더 느린 배포 기계에서는 같은 입력도 결과가 달라지고 배정 수가 줄 수 있다는 뜻이다. 실행 기록에는 탐색 중단이 남지만 이 경우 정책(시간 상한·중단 처리)은 미정이다.
2. **미배정 이유 표기.** capacity_limited에서 정원 때문에 남은 37~38명의 이유가 `capacity`가 아니라 `no_valid_table`로 기록된다. 현재 `_reason`은 정원이 4 미만일 때만 `capacity`를 쓴다. 필수조건 위반은 아니지만 참가자 설명 정확성(명세 6절 10항)과 관련 있어 결정이 필요한 항목으로 남긴다. 제품 코드는 바꾸지 않았다.

## 한계와 미측정

- 계획기 순수 시간만 쟀다. HTTP·작업기 프로세스·DB 조회/저장 시간은 포함하지 않는다. 종단 경로는 `tests/test_matching_scale.py` 1개 형태로만 확인했다.
- 로컬 arm64 개발 기계 측정이다. Railway 배포 환경의 시간·메모리·CPU는 측정하지 않았다(관찰 1 때문에 특히 필요하다).
- 합성 형태 6종·시드 5개다. 실제 신청 분포·다중 회차·재배치(①-c) 경로는 포함하지 않는다.
- 상한 형태의 최적해 차이는 알 수 없다. 100명 완전 탐색은 불가능하며 작은 입력의 최적 비교는 `tests/oracle/test_engine_against_scoring_oracle.py`가 담당한다.
- 수용 수치(시간·메모리·최적 차이), 100명 초과 처리(U19), 탐색 중단 시 처리 정책은 미결정이다.

## 재현

```bash
export PYTHONPATH=backend
uv run python scripts/measure_matching_scale.py --seeds 5          # 집계 표
uv run python scripts/measure_matching_scale.py --seeds 5 --json   # 실행별 집계 JSON 추가
uv run pytest -q tests/test_scale_measurement.py                   # 빠른 회귀(시드 2개 × 4형태)
```
