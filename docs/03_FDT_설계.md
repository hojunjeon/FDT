# FDT 개인 금융 디지털 트윈 · 분석/코칭 에이전트 설계서 (v1.0)

- 상태: 확정 (2026-09-03). 구현 에이전트는 이 문서를 단일 기준으로 삼는다.
- 상위 문서: `01_KeyFin_기획의도.md`, `02_KeyFin_요구사항명세.md`, `FDT.md`. 충돌 시 이 문서 §3 의 결정이 우선한다.
- 코드 위치: `fdt/` 패키지. 완료 모듈과 미완료(stub) 모듈은 §5 에 표시한다.
- 문서에서 "MUST"는 위반 시 PR 반려, "SHOULD"는 이유를 적으면 예외 가능.

---

## 0. 한 페이지 요약

KeyFin 의 **개인 금융 디지털 트윈(PFDT)** 코어와, 그 위에서 동작하는 **읽기 전용 분석·코칭 에이전트**, 이를 조작·확인하는 **로컬 대시보드**를 만든다.

- 입력: SSAFY 금융망 API 응답 형식의 JSON (지금은 생성기가 만든 더미, 나중엔 LIVE).
- 코어: 원장 → `State(t)` + `Behavior` → 단일 시뮬레이터(전이 함수) → 예측·리스크·목표 역산·진단.
- 에이전트: 로컬 LLM(Ollama, qwen2.5 7B)이 **툴 선택과 문장 생성만** 담당. 숫자는 100% 코어가 낸다.
- 대시보드: `KeyFin_Local_Agent` 의 3열 UI 흐름을 참고한 정적 HTML/CSS/JS + 얇은 FastAPI 어댑터. 사용자 프로필과 코치 페르소나는 별도 선택한다.
- 검증: 홀드아웃 백테스트, 리스크 캘리브레이션, 코칭 숫자 충실도 자동 검사, 툴 라우팅 평가.
- 범위 밖: 실제 이체·결제 실행, 운영 배포·회원·알림 인프라, 게임 수준의 방·고양이 렌더링.

---

## 1. 범위와 비범위

### 1.1 범위 (이 저장소가 만드는 것)

| 기능 ID | 이름 | 이 저장소의 산출물 |
| --- | --- | --- |
| FDT-INP-01 | 가맹점 자동 세분류 | 매핑 테이블 우선 + 폴백 분류기 인터페이스(LLM) |
| FDT-INP-02 | 채팅 의도·파라미터 추출 | LLM tool calling 으로 툴·파라미터 선택 |
| FDT-SIM-01 | 30일 잔액 궤적 | 시뮬레이터 중앙값 경로 + P10/P90 |
| FDT-SIM-02 | What-if 분기 | 공통 난수 기본/분기 비교, 델타 |
| FDT-SIM-03 | 결제 부족 리스크 | 경로 기반 부족 확률, 0~100 점수 |
| FDT-SIM-04 | 목표 역산 | 주차별·봉투별 지출 상한 |
| FDT-ANL-01 | Safe-to-Spend | 당일 안심 소비 한도 |
| FDT-ANL-02 | 봉투 재배분 | 여유 봉투 → 초과 봉투 이동안 |
| FDT-ANL-03 | 가속도·우려 결제 | 알림 목록 (결정론 규칙) |
| FDT-INT-01 | 페르소나 코칭 | 3종 말투 문장 + 숫자 충실도 검사 |
| FDT-INT-02 | 방 상태 매핑 | 날씨/표정/행동 파라미터 JSON |
| FDT-WEB-01 | 로컬 HTTP 연동 | 프로필 조회·세션·채팅을 제공하는 FastAPI 어댑터 |
| FDT-UI-01 | 로컬 대시보드 | 상태·봉투·예측·What-if·목표·위험·코칭 시각화 |
| FR-BGT-01 | 예산 제안 | 이력 기반 결정론 제안 (승인·조정 UI 는 범위 밖) |
| FR-USR-04 | 온보딩 시딩 | 프로필 생성기 (완료) |

### 1.2 비범위 (결정 사항)

- **이체·결제 실행**(FR-PAY-03/04/06/08): 하지 않는다. FDT.md 원칙. 결제일별 부족액 JSON 은 산출하되 "이체 제안" 도 만들지 않는다.
- **운영 UI**: 로그인, 실제 사용자 금융 연동, 모바일 대응, 알림, 운영 배포는 범위 밖. v1.0 은 로컬 데모 대시보드만 제공한다.
- **게임 UI**: 방·고양이 애니메이션과 코인 상점은 범위 밖. 대시보드는 `RoomProjection` 을 상태 카드와 정적 고양이 이미지로만 표현한다.
- **회원/연동/알림 인프라**(USR, NTF), **코인 계산**(GAM-03/04): 범위 밖. INT-02 에서 `coin_eligible_today` 플래그만 낸다.
- **KoELECTRA 파인튜닝**: 하지 않는다. 시딩 가맹점은 매핑 테이블이 100% 커버하고, 미등록 가맹점은 LLM 폴백으로 처리한다. P2 로 이연.
- **RAG 정책 추천**(FDT-INT-03, FR-AI-05/06): 이번 버전 범위 밖. 툴 인터페이스만 예약(§8.2 `policy_tips`, 미구현 표시).

---

## 2. 용어

| 용어 | 뜻 | 주의 |
| --- | --- | --- |
| 사용자 프로필 (profile) | 더미 데이터를 만드는 가상 사용자 3명 (A/B/C) | 문서의 "페르소나"와 다른 개념 |
| 코치 페르소나 (persona) | 고양이 말투 3종: 도도냥/온순냥/지방냥 | FR-AI-02 |
| 봉투 (envelope) | 7대 소비 예산 카테고리 | 소비만 담는다. 고정비·수입·카드대금은 봉투 아님 |
| 흐름 (flow) | 거래 종류: 수입/고정비/카드대금/내계좌이체/환불·취소/소비 | `fdt.taxonomy.categories.Flow` |
| 약정 지출 큐 | 향후 나갈 확정·준확정 지출 목록 | 카드 청구 예정액 포함 |
| as_of | 트윈 기준일. 이 날짜 이하의 원장만 사용 | 홀드아웃 평가의 핵심 |
| 경로 (path) | 시뮬레이션 1회 실행이 만든 일별 잔액 시계열 | n_paths 개 |
| 공통 난수 (CRN) | 기본/분기 시뮬레이션에 같은 시드를 써 잡음을 상쇄 | What-if 델타 계산 필수 |

---

## 3. 문서 간 충돌 해소 (결정)

| # | 충돌 | 결정 | 근거 |
| --- | --- | --- | --- |
| 1 | 요구사항명세는 이체 실행이 P0, FDT.md 는 제외 | **제외**. 이 저장소는 분석·코칭 전용 | 사용자 결정 (2026-09-03) |
| 2 | FDT.md 는 카드 "결제일"을 월 단위처럼 서술, 금융망은 주 단위 청구 | **주 단위**를 기본. 월~일 사용분 → 차주 월 07:30 청구 → 카드별 출금 요일 16:00 출금 | 금융망 실검증 (`02` §3) |
| 3 | FR-AI-03 "애매 상황을 LLM 이 판단" | **삭제**. 우려 결제 규칙을 잔여 일수로 정규화해 결정론적으로 해결 (§7.6.3) | "숫자 판정에 LLM 개입 금지" 원칙 |
| 4 | FDT.md SIM-01 "결정론 엔진" vs SIM-03 "몬테카를로 엔진" | **엔진 하나**. 결정론 궤적 = 경로 중앙값 | 두 엔진이 서로 다른 답을 내는 사고 방지 |
| 5 | FDT-INP-01 "KoELECTRA 10ms" | 매핑 테이블(<1ms) + LLM 폴백. 모델 파인튜닝은 P2 | 더미 가맹점은 전부 매핑됨 |
| 6 | 카드 취소 표현 | 금융망은 원 승인 레코드의 `cardStatus` 만 `취소`로 바뀜. 원장은 **승인(−)+취소(+) 두 건**으로 기록 | 이력 보존 + 순액 0 (구현 중 발견, 테스트로 고정) |
| 7 | 미결제 청구서 재시도 | 잔액 부족 시 **다음 날부터 매일 16:00 재시도**로 가정. 금융망 실제 동작은 미확인 → §14 리스크 | 생성기와 시뮬레이터가 같은 가정을 써야 함 |
| 8 | 미결 #7 질문 빈도 | 확신도 < 0.7 인 소비 건만 "미확정"으로 집계 | INT-02 코인 플래그, State.unconfirmed_count |
| 9 | 기존 결정은 UI를 다른 저장소 범위로 둠 | **로컬 데모 대시보드와 HTTP 어댑터는 포함**. 운영 UI와 게임 UI는 계속 제외 | 사용자 결정 (2026-09-03), §9.2 |

---

## 4. 아키텍처와 데이터 흐름

```mermaid
flowchart LR
  subgraph IN[입력]
    G[프로필 YAML + 시드<br/>generator.py] --> S[FinSnapshot JSON<br/>금융망 응답 형식]
    L[LIVE 금융망 API<br/>(후일)] -.-> S
  end
  S --> I[ingest.py<br/>정규화 원장 LedgerTx]
  I --> C[classify.py<br/>매핑→고정비→키워드→LLM폴백]
  I --> ST[state.py<br/>State(t)]
  I --> BH[behavior.py<br/>Behavior]
  ST --> SIM[simulate.py<br/>전이 함수 · n경로]
  BH --> SIM
  SIM --> R1[SIM-01 궤적]
  SIM --> R2[SIM-02 What-if]
  SIM --> R3[SIM-03 리스크]
  ST --> GO[goal.py SIM-04]
  ST --> AN[analytics.py<br/>ANL-01/02/03 · health]
  R3 --> AN
  AN --> PR[projection.py INT-02]
  subgraph AG[에이전트 (LLM 은 여기서만)]
    U[사용자 발화] --> T[tools.py<br/>툴 선택·파라미터]
    T --> EX[execute_tool → 코어 함수]
    EX --> CO[coach.py<br/>페르소나 문장]
    CO --> F[숫자 충실도 검사]
    F -->|실패| TB[템플릿 폴백]
  end
  R1 & R2 & R3 & GO & AN & PR --> EX
  subgraph WEB[로컬 대시보드]
    D[index.html + app.js<br/>상태·차트·채팅] --> W[web.py<br/>FastAPI 어댑터]
  end
  W -->|프로필 로드| I
  W -->|사용자 발화| U
  ST & R1 & R2 & R3 & GO & AN & PR -->|JSON| W
```

**불변 원칙 (MUST)**

1. `fdt/twin/**`, `fdt/ledger/**`, `fdt/data/**` 는 LLM 을 import 하지 않는다. 숫자는 여기서만 만들어진다.
2. `fdt/agent/**` 는 숫자를 계산하지 않는다. 툴 결과 JSON 을 그대로 전달하고 문장만 만든다.
3. 원장(`LedgerTx` 목록)은 불변. What-if 는 `State` 복사본 위에서만 돈다.
4. 모든 난수는 명시적 시드를 받는다. 같은 입력·같은 시드 → 같은 출력 (바이트 단위).
5. 금액은 정수 원(`int`). 부동소수는 확률·비율·로그정규 파라미터에만.
6. `fdt/web.py` 는 코어·에이전트의 공개 함수만 호출하는 어댑터다. 금융 숫자나 위험 판정을 다시 계산하지 않는다.
7. 브라우저는 서버 JSON 을 표시만 한다. 금액 포맷과 진행 막대 비율 외의 도메인 판단을 JavaScript 에 두지 않는다.

---

## 5. 저장소 구조와 진행 상태

```
fdt/
  taxonomy/categories.py     [완료] 7대 봉투, 22 세분류, 75 가맹점 매핑, 고정비·요약 키워드
  schemas/finapi.py          [완료] 금융망 REC 스키마 (필드명 원본)
  schemas/domain.py          [완료] LedgerTx, State, Behavior, 결과 스키마
  data/profiles/*.yaml       [완료] A_steady, B_card_crunch, C_impulsive
  data/generator.py          [완료] 프로필 → FinSnapshot + ground_truth
  ledger/classify.py         [완료] 라벨링 (폴백 분류기 Protocol 포함)
  ledger/ingest.py           [완료] 스냅샷 → 원장, 대사(reconcile), 저장/로드
  twin/state.py              [완료] §7.1
  twin/behavior.py           [완료] §7.2
  twin/simulate.py           [완료] §7.3 §7.4
  twin/goal.py               [완료] §7.5
  twin/analytics.py          [완료] §7.6
  twin/projection.py         [완료] §7.7
  agent/llm.py               [완료] §8.1
  agent/tools.py             [완료] §8.2
  agent/coach.py             [완료] §8.3 §8.4 §8.5
  agent/agent.py             [완료] §8.6
  web.py                     [완료] §9.2 HTTP·세션 어댑터
  static/                    [완료] §9.2 로컬 대시보드 HTML/CSS/JS/SVG
  eval/backtest.py           [완료] §11.4
  eval/calibration.py        [완료] §11.5
  eval/faithfulness.py       [완료] §11.6 §11.7
  cli.py                     [완료] §9 의 명령 전체
tests/test_ledger.py         [완료] 5 케이스
tests/test_web.py            [완료] §11.3.1
data/seed/<profile>/         [생성물] snapshot.json, ground_truth.json, profile.yaml (커밋함, 1.2MB)
```

stub 파일의 함수 시그니처는 **계약**이다. 바꿔야 하면 이 문서를 먼저 고치고 커밋 메시지에 명시한다.

---

## 6. 데이터 계층 (완료 모듈의 규칙 정리)

### 6.1 금융망 스키마 (`schemas/finapi.py`)

- 금융망은 숫자를 **문자열**로 내려준다. 스키마는 `str` 로 받고 인입에서 `int()`.
- 계좌 거래(`AccountTransaction`)는 가맹점 정보가 `transactionSummary` 문자열에만 있다. 생성기는 `"<가맹점> 체크카드"` 형식으로 쓰고, 인입은 접미어(체크카드/카드/결제/승인)를 떼고 첫 토큰을 가맹점으로 본다.
- 카드 거래(`CardTransaction`)는 `categoryId/categoryName/merchantName` 이 구조화돼 있다. `categoryName` 은 금융망 7종(주유/대형마트/교통/교육·육아/통신/해외/생활)이며 **참고 원본**일 뿐, 봉투 결정에 쓰지 않는다 (FR-TXN-02).
- 카드 출금 요일 `withdrawalDate` 는 "1=월 … 7=일". 도메인에서는 0=월 … 6=일 로 변환.
- `FinSnapshot` 은 한 사용자의 조회 결과 묶음. LIVE 전환 시 어댑터가 실제 API 응답을 이 구조로 채우면 하위 계층은 무변경.

### 6.2 프로필과 생성기 (`data/profiles`, `data/generator.py`)

설계 의도: 세 프로필이 **엔진의 서로 다른 경로**를 검증한다.

| 프로필 | 특징 | 검증 대상 | 현재 6개월 결과 |
| --- | --- | --- | --- |
| A_steady 김안정 | 고정 급여 315만, 체크카드 위주(카드 35%), 절약형 탄력도 0.75, 월 30만 비상금 적립 | ANL-01 이 조용히 맞는지, 기준선 | 부족 0, 최종 잔액 525만 |
| B_card_crunch 이카드 | 급여 287만, 카드 2장(화·토 출금) 90%, 월세 70만·대출 1,200만(6.8%) | SIM-03, 청구 큐 전이, 카드대금 이중 차감 방지 | 카드 부족 1건, 최종 78만 |
| C_impulsive 박자유 | 프리랜서 월 2~4회 불규칙 입금(평균 320만), 주말 배수 최대 2.4, 탄력도 1.4(충동) | ANL-03, 요일 밀도, 불규칙 수입 추정 | 카드 부족 6건, 체크 거절 45건, 최종 6천원 |

생성기가 **엔진에 숨기는 변수** (엔진은 원장에서 추정만 가능):

- 급여 후 7일 소비 배수(`payday_boost`), 급여 전 5일 감쇠(`pre_payday_damp`)
- 봉투 잔여 < 20% 시 배수(`elasticity`)
- 돌발 지출(일 확률·금액 분포), 카드 취소(`cancel_prob`), 더치페이 입금(`dutch_pay_prob`)
- 잔액 부족 시 체크카드 결제 **거절**(원장에 남지 않음 → 정답 파일에만 기록)

생성기 규칙 요약 (하루 처리 순서): 수입 → 고정비 → 카드 청구(월요일 발행)/출금(요일 16:00, 미결제는 매일 재시도) → 봉투별 포아송 소비 → 돌발 → 당일 취소·더치페이 → 일말 잔액 기록. **시뮬레이터의 전이 순서(§7.3)와 동일해야 한다.**

`ground_truth.json` 필드: `daily_balance{YYYYMMDD:{accountNo:balance}}`, `card_shortfalls[]`, `declined_debits[]`, `shocks[]`, `cancels[]`, `dutch_pays[]`, `envelope_true_spend{YYYYMM:{봉투:순지출}}`, `income_events[]`, `hidden_params`. **평가 코드만 읽는다. 트윈 코드가 읽으면 반려.**

재현성: `generatedAt` 을 제외한 스냅샷은 같은 프로필·시드에서 바이트 동일 (확인됨). `python -m fdt.cli gen all` 로 재생성.

### 6.3 원장 인입·분류 (`ledger/`)

분류 우선순위 (`classify_merchant`): ① 고정비 가맹점 테이블 → ② 가맹점→세분류 매핑 → ③ 폴백 분류기(LLM, 확신도 ≤ 0.6) → ④ 미분류(기타/경조사·기타, 확신도 0.3).

계좌 요약 분류 (`classify_account_summary`): 요약 키워드(급여/카드대금/월세/관리비/보험료/대출이자/비상금이체/더치페이/취소…) 우선 → 입금이면 수입(확신도 0.5) → 출금이면 가맹점 분류.

원장 규칙 (NFR-BGT-01):

- 카드 승인 → `SPEND`(−) 또는 `FIXED`(−). `cardStatus=취소` 면 같은 시각에 `REFUND`(+) 한 건 추가 (tx_id 접미 `:cancel`).
- 계좌 "카드대금 …" 출금 → `CARD_BILL`. `envelope=None`. **봉투에 다시 차감하지 않는다.**
- `transactionAccountNo` 가 내 계좌면 `TRANSFER_INTERNAL`.
- 봉투 순지출 = `SPEND` + `REFUND`(envelope 있는 것) 합의 절대값.

대사(`reconcile`)는 계좌별 `개설잔액 + Σ원장 == 최종잔액`, 미분류 0, 저확신 0 을 검사한다. 3 프로필 모두 통과.

---

## 7. 트윈 코어 설계 (구현 대상)

### 7.1 State(t) — `twin/state.py`

입력: 원장 `txs`(전체), `snap`, `as_of`, 선택 `budgets`. **`as_of` 보다 뒤의 거래는 절대 보지 않는다.** 필터는 `t.occurred_at.date() <= as_of`.

#### 7.1.1 계좌 역할과 잔액

- primary 계좌: 카드 `withdrawalAccountNo` 가 가리키는 계좌. 카드가 없으면 `INCOME` 거래가 가장 많은 계좌.
- emergency 계좌: primary 외 수시입출금 계좌들의 합.
- 잔액(as_of): `개설잔액 + Σ(해당 계좌 원장 amount, ≤ as_of)`. 개설잔액은 첫 거래의 `transactionAfterBalance − 부호 있는 금액` 으로 역산 (거래 없으면 스냅샷 `accountBalance`).
- `liquidity` = primary 잔액. `emergency_fund` = emergency 합. (비상금은 시뮬레이션에서 자동 사용하지 않는다. FR-BGT-09 는 사용자 선택.)

#### 7.1.2 카드 상태

카드별 `CardState`:
- `withdrawal_weekday = int(withdrawalDate) − 1`
- `unbilled` = 이번 청구 주기(가장 최근 월요일 ~ as_of, 월요일 포함) 카드 거래 순액(승인 − 취소, FIXED 포함). as_of 가 월요일이면 그날 07:30 에 직전 주가 청구되므로 "이번 주기"는 당일부터.
- `issued_unpaid` = 스냅샷 `billingStatements` 에서 `status=미결제` 이고 `billingDate ≤ as_of` 인 청구서 → `FixedCommitment(kind="카드대금", due=다음 출금 요일 (as_of 포함), certainty=1.0)`.
  - 스냅샷 청구서가 as_of 이후 정보를 담고 있을 수 있다(홀드아웃). **`billingDate > as_of` 는 무시**하고, 대신 원장에서 직전 주 승인 합을 다시 계산해 "발행됐어야 할 청구서"를 재구성한다: 직전 월요일 발행분이 원장에 `CARD_BILL` 출금으로 아직 안 보이면 미결제로 본다.

#### 7.1.3 약정 지출 큐 `build_committed_queue`

`as_of+1` 부터 `horizon_days`(기본 35) 안에 나갈 항목:

| 종류 | 탐지 | 다음 예정일 | 금액 |
| --- | --- | --- | --- |
| 월세/관리비/보험/대출이자 (계좌) | 원장 `FIXED` 를 `(fixed_kind, merchant 문자열)` 로 묶어 **월 1회 반복**(간격 25~35일) 확인, 최소 2회 | 마지막 발생일 + 1개월 (같은 일자, 말일 보정) | 최근 3회 중앙값 |
| 통신/구독 (카드) | 원장 `FIXED` 카드 거래, 같은 방식 | 동일 | 동일 |
| 구독 (스냅샷) | `snap.subscriptions[status=ACTIVE]` | `nextPaymentDate` (≤ as_of 면 +1개월 반복) | `paymentAmount` |
| 대출이자 (스냅샷) | `snap.loans` | 원장의 대출이자 발생일 패턴, 없으면 매월 말일 | `loanBalance × rate/100/12`, 10원 단위 |
| 카드대금(미청구) | `CardState.unbilled` | 다음 월요일 발행 후 첫 출금 요일 | `unbilled`, certainty 0.9 |
| 카드대금(미결제) | `CardState.issued_unpaid` | 다음 출금 요일 | 청구액, certainty 1.0 |

중복 제거: 원장에서 탐지한 구독과 스냅샷 구독이 같은 가맹점이면 스냅샷 것을 우선. 동일 (kind, name, due) 는 하나만.

#### 7.1.4 봉투와 예산 제안 `propose_budgets`, `envelope_states`

- 주기: 달력 월 (1일~말일). `cycle_start = as_of.replace(day=1)`.
- 예산 제안 (FR-BGT-01, 결정론):
  1. as_of 이전의 **완결된 월**(1일~말일 전부 as_of 이전)별 봉투 순지출 계산.
  2. 완결 월 ≥ 3 → 중앙값. 1~2 → 평균. 0 → 최근 28일 순지출 × 30/28.
  3. 만원 단위 **올림**. 하한 10,000원.
  4. `budgets` 인자가 주어지면 그 값을 쓴다 (사용자 승인·조정 FR-BGT-02 대응).
- `spent` = 이번 달 1일~as_of 봉투 순지출. `remaining = budget − spent` (음수 허용).

#### 7.1.5 수입·행동 지표

- `next_income_date`, `expected_income`: §7.2.6 `detect_income_schedule` 결과.
- `spend_7d_avg` = (as_of−6 ~ as_of) 봉투 순지출 합 / 7. `spend_90d_avg` = 90일 합 / 90 (데이터가 90일 미만이면 실제 일수로 나눔).
- `acceleration = spend_7d_avg / max(spend_90d_avg, 1000)`.
- `unconfirmed_count` = 이번 달 `SPEND` 중 `confidence < 0.7` 건수.
- `health_score/level` 은 `analytics.health()` 가 SIM-03 결과와 함께 채운다. `build_state` 는 0 / "SAFE" 기본값으로 둔다.

### 7.2 Behavior — `twin/behavior.py`

윈도우: `[as_of − window_days + 1, as_of]`, 기본 90일, 최소 28일(부족하면 있는 만큼). `SPEND` 거래만 사용 (`REFUND` 는 상쇄된 건을 제외하는 데만 쓴다: 같은 카드·같은 금액·같은 날의 승인+취소 쌍은 제거).

#### 7.2.1 발생률과 요일 배수

봉투 e 에 대해 `n_e` = 건수, `N` = 윈도우 일수.
- `daily_rate_e = n_e / N`
- 요일 w 의 건수 `c_w`, 요일 w 의 일수 `d_w`. 기대 `E_w = daily_rate_e × d_w`.
- 축소 추정: `m_w = (c_w + α) / (E_w + α)`, α = 2. 이후 `m_w ← m_w / mean(m)` 으로 평균 1 정규화.
- `n_e < 10` 이면 요일 배수는 전부 1.0.

#### 7.2.2 금액 분포

로그정규. `a_i` 양수 금액들에 대해 `mu = mean(ln a)`, `sigma = std(ln a, ddof=1)`.
- `sigma` 하한 0.2, 상한 1.5.
- `n_e < 5` 면 전 봉투 통합(pooled) 추정치를 쓴다. 통합도 5 미만이면 `mu = ln(10000)`, `sigma = 0.6`.

#### 7.2.3 카드 비율

`card_share_e = 카드 건수 / n_e`. `n_e = 0` 이면 전체 카드 비율. 전체도 0이면 0.5.

#### 7.2.4 급여 효과

수입 일자 목록 `D` (§7.2.6). "급여 후" 날 = 어떤 d∈D 에 대해 `0 ≤ day − d < 7`.
`payday_boost = (급여 후 날들의 일평균 총 봉투 지출) / (그 외 날들의 일평균)`. 클립 [0.7, 2.0]. 급여 후 날이 14일 미만이거나 D 가 비면 1.0. 봉투 공통 값(봉투별 추정은 데이터가 부족).

#### 7.2.5 충동 탄력도

각 날 t, 봉투 e 의 "잔여율" = `1 − (해당 월 1일~t−1 순지출) / budget_e`. budget 은 `budgets` 인자(없으면 `propose_budgets(as_of)` 결과).
`elasticity_e = (잔여율 < 0.2 인 날들의 일평균 지출) / (그 외 날들의 일평균)`. 클립 [0.5, 2.0]. 저잔여 날이 5일 미만이면 1.0.

#### 7.2.6 수입 일정 `detect_income_schedule`

`INCOME` 거래(확신도 ≥ 0.5)를 일자별로 합산 → 일자 목록 `D`(오름차순), 금액 `A`.
- `|D| ≥ 2`: 간격 `g_i`. `cv = std(g)/mean(g)`. 각 일자의 day-of-month 최빈값 비율 `p_dom`.
- **규칙적**(salary): `cv ≤ 0.25` 이고 `p_dom ≥ 0.6` → `next = as_of 이후 첫 번째 그 day-of-month(말일 보정)`, `expected = median(A)`, `irregular=False`.
- **불규칙**: 그 외 → `next = 마지막 수입일 + median(g)` (as_of 이하면 as_of+1), `expected = median(A)`, `irregular=True`.
- `|D| ≤ 1`: `next=None`, `expected=0`, `irregular=True`.

#### 7.2.7 돌발 지출

윈도우 내 `SPEND` 중 `금액 ≥ max(50,000, 5 × exp(mu_e))` 인 건을 돌발로 본다.
`shock_daily_prob = 건수 / N`, `shock_amount_mu/sigma` 는 그 금액들의 로그 평균/표준편차(sigma 하한 0.3). 0건이면 `prob=0.01, mu=ln(100000), sigma=0.6`. 돌발로 분류된 건은 §7.2.1~7.2.2 의 봉투 추정에서 **제외**하지 않는다(단순화, 이중 계상은 소폭이며 보수적).

### 7.3 회계 전이 함수 (하루 처리 순서)

경로 p, 날짜 d 에 대해 순서 고정. **생성기와 동일**.

1. **수입**: `d == next_income_date` 이면 `liquidity += expected_income`. 규칙적이면 다음 수입일 = +1개월 같은 일자. 불규칙이면 `+ median 간격` 이며 금액에 로그정규 잡음(sigma 0.4) 을 준다.
2. **고정비**: 큐에서 `due == d` 인 항목. 계좌 항목은 `cash >= amount` 일 때만 `liquidity −= amount` 하고, 부족하면 거절되어 잔액을 바꾸지 않는다. 카드 항목(통신/구독) → 해당 카드 `unbilled += amount`. 카드대금 항목은 4에서 처리.
3. **청구서 발행**: `d.weekday()==0` 이면 카드별 `issued.append(unbilled)`, `unbilled = 0`.
4. **카드 출금**: 카드별 `d.weekday()==withdrawal_weekday` **또는** 미결제 청구서가 발행 7일 이상 경과(재시도) 이면, 발행일 ≤ d 인 미결제 청구서를 오래된 것부터 시도한다. `cash >= total` 이면 `liquidity −= total` 하고 청구서를 제거하고, 부족하면 `card_shortfall[p]=True` 로 기록하되 잔액은 바꾸지 않고 청구서를 남긴다. 재시도는 매일.
5. **소비**: 봉투별 `λ = daily_rate × weekday_mult[wd] × boost × elasticity_gate`.
   - `boost = payday_boost` if 최근 수입 후 7일 이내 else 1.
   - `elasticity_gate = elasticity` if 봉투 `remaining_ratio < 0.2` else 1. (remaining 은 경로별로 추적: `budget − (spent_this_month + 시뮬 지출)`. 달이 바뀌면 spent 0으로 리셋.)
   - `n ~ Poisson(λ)`, 각 건 금액 `~ LogNormal(mu, sigma)` 100원 반올림. 카드 비율만큼 `unbilled` 로, 나머지는 `cash >= amount` 일 때만 `liquidity` 에서 즉시 차감한다. 잔액이 부족한 체크성 지출은 거절되어 잔액·봉투 누적에 반영하지 않는다(`declined_debits` 와 같은 가정).
   - 봉투별 지출 누적 `envelope_spend[p, e] += Σ`.
6. **돌발**: `Bernoulli(shock_daily_prob)` → `LogNormal(shock_mu, shock_sigma)`, 카드 비율은 전체 평균. 봉투 `기타` 로 누적.
7. **가상 지출 주입**(What-if): `injections` 중 `on == d` 인 건을 5 와 같은 방식으로 적용(카드면 `unbilled`).
8. **일말 기록**: `balances[p, k] = liquidity`. `liquidity < 0` 이면 `any_shortfall[p]=True`, `first_shortfall_idx` 갱신.

벡터화: 모든 경로를 numpy 배열로 동시에 진행한다(`liquidity: (n_paths,)`). 포아송 건수는 `rng.poisson(λ, n_paths)`, 금액은 총 건수만큼 한 번에 뽑아 `np.add.reduceat` 로 경로별 합산. 성능 기준 §11.8.

### 7.4 시뮬레이터 API 와 SIM-01~03 정의

`simulate(state, behavior, horizon_days=30, n_paths=1000, seed=42, injections=None) -> SimulationResult`

- `dates[0] = as_of` (기록값은 as_of 잔액), `dates[k] = as_of + k`.
- `SimulationResult.stats()` → `PathStats`: 일별 중앙값/P10/P90/평균, `min_balance = min(median)`, `min_balance_date`, `shortfall_prob = mean(any_shortfall)`, `card_shortfall_prob = mean(card_shortfall)`, `first_shortfall_date_median` = 부족 경로들의 첫 부족일 중앙값(없으면 None).

| 기능 | 정의 |
| --- | --- |
| **SIM-01** `forecast` | `simulate(...).stats()`. UI 는 median 선 + P10~P90 밴드. "최저 잔액점 브리핑" = `min_balance`, `min_balance_date` |
| **SIM-02** `what_if` | `base = simulate(seed=s)`, `branch = simulate(seed=s, injections=…)`. **같은 시드**. `delta_min_balance = branch.min − base.min`, `delta_shortfall_prob`, `delta_end_balance = median 마지막 차`. `verdict`: 분기 `card_shortfall_prob ≥ 0.5` 또는 `min_balance < 0` → DANGER; `delta_shortfall_prob ≥ 0.15` 또는 분기 min < 기본 min 의 50% → CAUTION; 그 외 OK |
| **SIM-03** `risk` | `risk_score = round(100 × max(card_shortfall_prob, 0.6 × shortfall_prob))`. level: `< 20` SAFE, `< 50` WARNING, 그 외 DANGER. `worst_day = first_shortfall_date_median`. `expected_shortfall` = 부족 경로들의 최저 잔액 절대값 평균 |

`n_paths` 기본 1000. 시드 기본 42. 두 값은 툴 파라미터로 노출하지 않는다(재현성).

### 7.5 목표 역산 (SIM-04) — `twin/goal.py`

`plan_goal(state, behavior, target_amount, target_date)`:

1. `H = (target_date − as_of).days`, `H ≤ 0` → infeasible.
2. `base = simulate(horizon=H)`; `baseline_discretionary = median(Σ envelope_spend)`.
3. 확정 유입 `I` = 기간 내 예상 수입 합(규칙적이면 확정, 불규칙이면 `expected × (H / median 간격)` × 0.8 보수 계수). 확정 유출 `F` = 큐의 고정비·카드대금 합 + 기간 내 반복될 월 고정비(월 단위 반복 가정).
4. `available = liquidity + I − F − target_amount`. `available < 0` → infeasible, note 에 부족액.
5. `reduction_ratio = max(0, 1 − available / baseline_discretionary)` (available ≥ baseline 이면 0, "지금대로 가능").
6. 주차 분할: as_of+1 부터 7일 단위, 마지막 주는 잔여 일수. 주 w 의 총 상한 = `available × days_w / H`.
7. 봉투 배분: 기준선 비율 `s_e = baseline_e / baseline`. **필수 봉투(교통비·의료·건강·편의점·마트·잡화)** 는 `≥ 0.8 × baseline_e × days_w/H` 하한. 하한 합이 주 상한을 넘으면 필수만 채우고 유연 봉투 0, `feasible=False` 유지하되 note 에 사유.
8. 출력 `WeeklyCap.caps` 는 100원 단위 내림.

### 7.6 진단·처방 — `twin/analytics.py`

#### 7.6.1 Safe-to-Spend (ANL-01)

```
days = max(1, (next_income_date − as_of).days)      # next 없음 → 30
committed = Σ committed.amount  where as_of < due < next_income_date   # 카드대금(미청구·미결제) 포함
raw_daily = (liquidity − committed) / days
factor = 1 / acceleration  if acceleration > 1 else 1
spent_today = Σ 오늘 SPEND 순지출
safe_today = max(0, floor((raw_daily × factor − spent_today) / 100) × 100)
```
`note`: `liquidity − committed < 0` 이면 "다음 수입 전 고정비를 감당할 수 없음. 부족 X원". 비상금은 계산에 넣지 않고 note 에 "비상금 Y원 별도" 만 적는다.

#### 7.6.2 봉투 재배분 (ANL-02)

- 월 진행률 `r = as_of.day / 말일`.
- 봉투별 예상 월말 지출 `proj_e = spent_e / max(r, 0.15)` (월초 과민 방지).
- 트리거 = `proj_e − budget_e` 가 가장 큰 봉투, 단 `> 0` 이고 `remaining_e < 0.2 × budget_e`. 없으면 `trigger=None, moves=[]`.
- `shortfall = proj_e − budget_e`.
- 공급 후보 = **유연 봉투**(취미·여가, 쇼핑, 외식, 기타) 중 트리거 제외. 여유 `slack_f = max(0, budget_f − proj_f)`.
- 배분 `move_f = shortfall × slack_f / Σslack`, 1,000원 단위 내림. `Σslack < shortfall` → `feasible=False`, 있는 만큼만 이동.
- **필수 봉투에서는 절대 빼지 않는다** (테스트로 고정).

#### 7.6.3 가속도·우려 결제 (ANL-03, FR-AI-01)

- **가속도**: `acceleration ≥ 1.3` 이고 `spend_7d_avg ≥ 10,000` → `Alert(kind=ACCELERATION, severity=WARNING(<1.6)/DANGER(≥1.6), ratio=acceleration)`.
- **우려 결제**: 검사 대상 = `recent_txs`(기본 as_of 당일 `SPEND`). 각 건에 대해
  ```
  remaining_before = budget_e − (spent_e_before_tx)        # 그 결제 직전 잔여
  days_in_cycle = 말일
  pace_unit = budget_e / days_in_cycle                     # 봉투의 하루치
  concerning = amount ≥ 0.5 × max(remaining_before, 0) and amount ≥ 3 × pace_unit and amount ≥ 20,000
  ```
  `threshold = max(0.5 × remaining_before, 3 × pace_unit, 20,000)`. severity: `amount ≥ remaining_before` → DANGER, 그 외 WARNING.
  월말에 잔여 2만원·결제 1.5만원인 경우 50% 룰은 걸리지만 `3 × pace_unit`(예산 60만 → 6만) 에 못 미쳐 **발동하지 않는다**. 이것이 FR-AI-03 을 대체하는 결정론 규칙이다.

#### 7.6.4 건전성 점수 `health`

```
cov  = clip((liquidity − committed_30d) / max(monthly_spend, 1), 0, 1)     # monthly_spend = spend_90d_avg × 30
adh  = 1 − mean_e( clip(spent_e/budget_e − r, 0, 1) )                    # 진행률 대비 초과분, r = 월 진행률
rsk  = 1 − card_shortfall_prob
score = 100 × (0.4 × cov + 0.3 × adh + 0.3 × rsk)
level = SAFE (≥ 70) / WARNING (≥ 40) / DANGER
```

### 7.7 방 상태 매핑 (INT-02) — `twin/projection.py`

| 입력 | 출력 |
| --- | --- |
| `level` | `weather`: SAFE→맑음, WARNING→흐림, DANGER→비 |
| `level` + 알림 | `avatar_mood`: SAFE→만족, WARNING→걱정, DANGER→울상. 알림에 DANGER 있으면 강제 울상 |
| 가장 초과율 높은 봉투 | `avatar_action`: 외식→포크질, 교통비→택시타기, 의료·건강→약봉투, 취미·여가→게임패드, 쇼핑→쇼핑백, 편의점·마트·잡화→장바구니, 기타→서류. 초과 봉투 없으면 "휴식" |
| 봉투별 `spent/budget` | `board_progress` (0~1 초과 허용, 소수 3자리) |
| `Σspent > Σbudget` | `seizure_sticker=True` |
| `unconfirmed_count == 0` | `coin_eligible_today=True` |

---

## 8. 에이전트 계층 설계 (구현 대상)

### 8.1 로컬 LLM

- 런타임: Ollama (설치됨, v0.32). 기본 모델 `qwen2.5:7b-instruct-q4_K_M` (4.7GB, `tools` capability 확인됨). 근거: VRAM 8GB(RTX 4070 Laptop) 에서 7B Q4 + 컨텍스트 8k 가 안전하게 올라가고, 한국어와 tool calling 이 동급 중 안정적. 대체 후보 `qwen3:8b`(더 나은 한국어, thinking 으로 지연 증가) 는 §14 에 실험 항목으로.
- 호출: `POST {url}/api/chat`, `stream=false`. 툴 선택 단계 `temperature=0`, 코칭 단계 `temperature=0.7`, `num_ctx=8192`. 폴백 분류기·파라미터 추출은 `format="json"`.
- 환경변수 `FDT_OLLAMA_URL`, `FDT_LLM_MODEL`. 서버 미가동 시 `available()==False` → 에이전트는 **툴 라우팅을 규칙 기반 키워드 매칭으로 대체**하고 코칭은 템플릿 폴백. 즉 LLM 없이도 전체 파이프라인이 동작해야 한다 (테스트는 LLM 없이 돈다).

### 8.2 툴 정의 (FDT-INP-02)

LLM 에 노출하는 함수. 모두 `TwinContext` 의 결정론 함수를 감싼다. 반환은 해당 pydantic 모델의 `model_dump(mode="json")`.

| 툴 | 파라미터 (JSON Schema) | 코어 호출 | 대응 |
| --- | --- | --- | --- |
| `get_state` | 없음 | `ctx.state` 요약(잔액·봉투·큐 상위 5건·수입 예정) | 상태 질의 |
| `forecast_balance` | `horizon_days: int 7~60 (기본 30)` | `simulate.forecast` | SIM-01 |
| `what_if` | `amount: int`, `envelope: enum 7`, `days_from_now: int 0~60`, `via_card: bool`, `label: str` | `simulate.what_if` | SIM-02 |
| `payment_risk` | `horizon_days` | `simulate.risk` | SIM-03 |
| `goal_plan` | `target_amount: int`, `target_date: YYYY-MM-DD` | `goal.plan_goal` | SIM-04 |
| `safe_to_spend` | 없음 | `analytics.safe_to_spend` | ANL-01 |
| `rebalance_envelopes` | 없음 | `analytics.rebalance` | ANL-02 |
| `spending_alerts` | `days: int 1~7 (기본 1)` | `analytics.detect_alerts` | ANL-03 |
| `room_status` | 없음 | `projection.project_room` | INT-02 |
| `policy_tips` | 없음 | **미구현**: `{"status":"not_available"}` 반환 | INT-03 예약 |

파라미터 정규화 규칙(툴 실행 전, 결정론): `envelope` 동의어 매핑(예 "밥/식비/커피"→외식, "옷/화장품"→쇼핑, "택시/지하철"→교통비, "병원/약"→의료·건강, "영화/게임/여행"→취미·여가, "편의점/마트"→편의점·마트·잡화, 나머지→기타). 금액 표기 "3만원/30,000원/3만" → 30000. 날짜 "다음 주 금요일/이번 달 말/25일" → as_of 기준 해석. 이 정규화는 `tools.py` 의 순수 함수로 두고 단위 테스트한다.

### 8.3 코치 페르소나 (FDT-INT-01, 미결 #5 확정안)

공통 시스템 프롬프트 골격:
```
너는 KeyFin 의 고양이 코치다. 아래 [엔진 결과] 의 숫자만 사용해 한국어로 2~4문장 답한다.
[엔진 결과]에 없는 숫자·날짜·확률을 만들지 않는다. 금액은 만원 단위로 반올림해 말할 수 있다.
말투: {페르소나 규칙}
```

| 페르소나 | 말투 규칙 | 예시 (엔진: 안심한도 18,000원, 카드 출금 목요일 21만원) |
| --- | --- | --- |
| 도도냥 | 짧고 새침. 문장 끝 "~냥". 칭찬 인색, 경고는 직설 | "오늘 쓸 수 있는 건 1만 8천원이냥. 목요일에 21만원 나가는 거 잊지 말라냥." |
| 온순냥 | 부드럽고 격려. "~해요/~냥" 혼용, 이모지 없음 | "오늘은 1만 8천원 정도면 편하게 쓸 수 있어요. 목요일 카드값 21만원은 제가 챙겨둘게요, 냥." |
| 지방냥 | 구수한 사투리. "~했시봉/~겨/~해야제" | "오늘은 1만 8천원까진 써도 되겄다. 목요일에 카드값 21만원 나가니께 그건 남겨두소." |

강도: 위험 레벨 DANGER 면 세 페르소나 모두 첫 문장에 위험 사실을 먼저 말한다.

### 8.4 숫자 충실도 검사 (환각 차단의 증거)

목적: 코칭 텍스트의 **모든 숫자**가 엔진 JSON 에서 왔음을 기계적으로 보장.

`allowed_numbers(engine_json)`:
1. JSON 을 재귀 순회해 모든 `int/float` 리프 수집. 문자열 중 날짜(`YYYY-MM-DD`)는 `월`, `일` 정수도 추가.
2. 파생값 추가: 각 금액 v 에 대해 `round(v, −4)`(만원 반올림), `round(v, −3)`(천원), `v // 10000`(만 단위 정수), `round(v/10000)`; 각 확률 p∈[0,1] 에 `round(100p)`, `round(100p, 1)`; 각 비율 r 에 `round(r,1)`, `round(100(r−1))`.
3. 항상 허용: 0, 1, 2, 3, 7, 30 (문장 구조용 소수), 연도 as_of.year.

`extract_numbers(text)`: 정규식으로 `\d[\d,]*(\.\d+)?` 와 한글 단위(`만`, `천`, `억`, `원`, `%`, `일`, `주`) 결합을 파싱. "1만 8천원"→18000, "21만원"→210000, "35%"→35, "3일"→3.

`check_faithful`: 추출된 각 수가 허용 집합에 있으면 통과. 금액은 **만원 단위 표기일 때 ±5,000원 허용**, 천원 단위 표기 ±500원. 그 외 정확 일치.

`coach()` 절차: 생성 → 검사 → 실패 시 위반 숫자 목록을 넣어 1회 재생성("다음 숫자는 사용 금지: …") → 재실패 시 `template_fallback`. 반환에 `faithful: bool, fallback: bool, violations: list` 를 항상 포함해 평가에서 집계한다.

### 8.5 템플릿 폴백

의도별 고정 문장에 엔진 숫자만 삽입. 페르소나별 어미만 다르게 (예: `{safe_today:,}원까지 써도 돼{ending}`). LLM 없이도 모든 툴에 대해 응답이 나와야 한다. 템플릿은 `coach.py` 상단 dict 로 관리하고 테스트에서 전 의도·전 페르소나 조합을 렌더링해 충실도 100% 를 확인한다.

### 8.6 대화 루프 `FdtAgent.ask`

1. `messages = [system(툴 선택용), *history(최근 6턴), user]` 로 `chat(tools=TOOL_SPECS, temperature=0)`.
2. 응답에 `tool_calls` 없으면 → `get_state` 로 간주(상태 질의 기본값).
3. 각 tool_call: 파라미터 정규화 → `execute_tool` → 결과 dict. 실행 예외는 `{"error": …}` 로 감싸 코칭에 전달(에이전트가 죽지 않는다).
4. `intent` = 첫 툴 이름. `engine_json` = 툴 결과들의 dict.
5. `coach(persona, intent, engine_json, user_text)` → 텍스트.
6. 반환 `{reply, tool_calls:[{name,args,result}], faithful, fallback, persona, engine_json}`. history 에 user/assistant 텍스트만 저장(툴 결과는 저장하지 않아 컨텍스트 폭증 방지).

`briefing()`: 툴 4개(`get_state`, `safe_to_spend`, `spending_alerts`, `payment_risk`) 결과를 합쳐 한 번 코칭. CLI `fdt brief` 가 부른다.

---

## 9. 실행 인터페이스

### 9.1 CLI (`fdt/cli.py`)

| 명령 | 동작 |
| --- | --- |
| `fdt gen [profile] [--seed] [--end]` | 더미 생성 (완료) |
| `fdt ingest <seed_dir> [--out ledger.jsonl]` | 원장 생성 + 대사 결과 출력 |
| `fdt state <seed_dir> [--as-of]` | State JSON 출력 |
| `fdt forecast <seed_dir> [--as-of] [--days 30]` | SIM-01 표 (날짜, P10, 중앙값, P90) |
| `fdt whatif <seed_dir> --amount --envelope --days-from-now [--card]` | SIM-02 |
| `fdt risk <seed_dir>` / `fdt goal <seed_dir> --target --date` | SIM-03 / SIM-04 |
| `fdt analyze <seed_dir>` | ANL-01~03 + health + room |
| `fdt brief <seed_dir> [--persona]` | 에이전트 브리핑 |
| `fdt chat <seed_dir> [--persona]` | 대화 REPL |
| `fdt eval backtest|calibration|faithfulness|routing` | §11 평가 실행, JSON 보고서 `data/out/eval/*.json` |
| `fdt serve [--host 127.0.0.1] [--port 8787]` | §9.2 로컬 대시보드 실행 |

금융 계산 명령은 `--as-of YYYY-MM-DD` 를 받으며 기본값은 원장 마지막 거래일. 출력은 `PYTHONIOENCODING=utf-8` 환경에서 깨지지 않아야 한다(Windows).

### 9.2 로컬 대시보드와 HTTP 연동

#### 9.2.1 기준과 범위

- 참고 UI: `C:/Users/SSAFY/Desktop/KeyFin_Local_Agent/app/static/` 의 3열 구조(프로필 선택 / 고양이 채팅 / 금융 상태·봉투)와 결과 카드·선 그래프 흐름.
- 구현은 이 저장소의 `fdt/static/` 에 자체 포함한다. 실행 시 다른 저장소의 파일이나 서버를 참조하지 않는다.
- 프런트엔드는 빌드 없는 HTML/CSS/JavaScript 로 유지한다. React/Vite/Node 의존성은 추가하지 않는다.
- 좌측에서 **금융 사용자 프로필** A/B/C와 **코치 페르소나** 도도냥/온순냥/지방냥을 별도 선택한다. 둘을 같은 "페르소나"로 합치지 않는다.
- 중앙은 정적 고양이, 채팅, 빠른 질문, 도구 실행 경로를 표시한다. 우측은 기준일, 유동성, 비상금, 다음 수입, 약정 지출, 위험도와 7개 봉투를 표시한다.
- 상단 상태 표시는 `DEMO`/`LIVE`, 기준일, 엔진 준비 여부, LLM 모델 또는 `template fallback` 을 분리해 표시한다. v1.0 데이터는 `DEMO`이며 LIVE 연결 전에는 LIVE로 표시하지 않는다.

#### 9.2.2 HTTP 인터페이스 (`fdt/web.py`)

기본 주소는 `http://127.0.0.1:8787` 이다. 정적 파일과 JSON 인터페이스를 같은 FastAPI 프로세스가 제공한다.

| 메서드·경로 | 입력 | 출력·역할 |
| --- | --- | --- |
| `GET /` | 없음 | `fdt/static/index.html` |
| `GET /api/health` | 없음 | `ok`, `source`, `engine_ready`, `llm_ready`, `llm_model`, `fallback` |
| `GET /api/profiles` | 없음 | A/B/C 프로필의 id·이름·설명 목록 |
| `GET /api/profiles/{profile_id}` | `as_of` 선택 | 프로필 메타 + `State` + `RiskResult` + `RoomProjection` JSON |
| `POST /api/chat/start` | `profile_id`, `coach_persona`, `as_of` 선택 | 메모리 세션 생성, `session_id`와 첫 인사 |
| `POST /api/chat/message` | `session_id`, `message`(1~1000자) | 코칭 문장, 실행 툴, 엔진 원본 결과, 시각화 명세 |
| `POST /api/chat/end` | `session_id` | 세션 삭제 확인 |

`/api/chat/message` 응답의 최소 계약:

```json
{
  "message": "오늘은 1만 9천원 안에서 쓰자냥.",
  "route": ["safe_to_spend", "coach"],
  "results": [{"tool": "safe_to_spend", "data": {}, "visualization": null}],
  "faithful": true,
  "fallback": false
}
```

`data` 는 `execute_tool` 의 `model_dump(mode="json")` 결과를 그대로 넣는다. `web.py` 는 키 이름을 복제 계산하지 않고, 시각화 명세만 다음처럼 변환한다.

| 툴 결과 | 대시보드 표현 |
| --- | --- |
| `get_state`, `safe_to_spend` | 금액 카드와 봉투 진행 막대 |
| `forecast_balance` | 날짜별 P50 선 + P10~P90 범위 |
| `what_if` | 기본/구매 후 비교 막대 + 위험도 델타 |
| `payment_risk` | 위험 점수·부족 확률·예상 부족액 카드 |
| `goal_plan` | 주차별 상한 표와 달성 가능 여부 |
| `spending_alerts`, `rebalance`, `room_state` | 알림·이동안·날씨/표정/행동 상태 카드 |

#### 9.2.3 세션과 실패 처리

1. 시작 시 `data/seed/<profile>/snapshot.json` 을 인입하고 선택 `as_of` 로 `State`, `Behavior`, `TwinContext`, `FdtAgent` 를 한 번 만든다.
2. 세션은 단일 프로세스 메모리 dict 에 저장한다. 같은 세션의 메시지는 lock 으로 직렬화해 history 순서를 보장한다. `chat/end` 또는 프로세스 종료 시 사라진다.
3. What-if 는 세션의 원장·State 를 변경하지 않는다. §4 불변 원칙대로 복사본에서만 실행한다.
4. 없는 프로필·세션은 404, 잘못된 입력은 422, 엔진 로드 실패는 503이다.
5. LLM 미가동은 장애가 아니다. HTTP 200과 `fallback=true` 로 규칙 라우터·템플릿 코칭을 반환한다. 엔진이 계산하지 못할 때만 503이다.
6. 기본 host는 `127.0.0.1` 이다. v1.0 은 인증이 없으므로 외부 공개 바인딩과 실제 금융 데이터 사용을 금지한다.

---

## 10. 구현 기준 (MUST/SHOULD)

**언어·도구**: Python 3.12, uv, pydantic v2, numpy, pandas(선택), pyyaml, httpx, typer, FastAPI, uvicorn, pytest. 대시보드는 바닐라 HTML/CSS/JavaScript이며 npm 의존성은 없다. 새 의존성 추가는 `pyproject.toml` 에 이유 주석과 함께.

**코드 규약**
- MUST 타입 힌트 전부. `from __future__ import annotations`.
- MUST 금액 `int`(원). 확률·비율 `float`. 날짜 `datetime.date`, 시각 포함은 `datetime`. 문자열 날짜는 경계(JSON/CLI)에서만.
- MUST 난수는 `np.random.default_rng(seed)` 를 함수 인자로 받은 시드로 생성. 전역 상태 금지. `random`, `hash()` 금지(재현성. 실제 사고 있었음).
- MUST `twin/`, `ledger/`, `data/` 에서 `fdt.agent` import 금지. 검사: `tests/test_architecture.py` 가 import 그래프를 확인한다.
- MUST 트윈 코드에서 `ground_truth.json`, 프로필 YAML 의 `spending` 읽기 금지.
- MUST `web.py` 와 `static/` 에 금융 판정 공식을 복제하지 않는다. 모든 숫자와 상태 판정은 코어 결과를 사용한다.
- MUST `fdt serve` 기본 바인딩은 `127.0.0.1`. 인증 구현 전 `0.0.0.0` 을 기본값으로 쓰지 않는다.
- MUST 공개 함수는 docstring 첫 줄에 설계서 절 번호(예 `§7.6.1`).
- SHOULD 함수 60줄 이내, 모듈 500줄 이내. 넘으면 분리.
- SHOULD 예외는 도메인 예외(`FdtError` 계층)로 감싸고 메시지에 as_of, 프로필 id 포함.
- 로그: `logging` 모듈, 모듈명 로거. print 는 CLI 에서만.
- 한글: 파일 UTF-8. 사용자 노출 문자열은 한국어, 식별자·로그 키는 영어.

**커밋**: CLAUDE.md 규칙. 한 기능 = 한 커밋 = 한 push. 메시지에 기능 ID 와 설계서 절 번호. 테스트가 깨진 상태로 push 금지.

**병렬 작업 시 파일 소유**: §13 의 담당 파일만 수정. 공용 파일(`schemas/domain.py`, `taxonomy/categories.py`, 이 문서)은 변경 전 해당 절을 먼저 수정하고 커밋 메시지에 "설계 변경" 을 붙인다.

---

## 11. 검증·테스트 계획

### 11.1 단위 테스트 (모듈별 필수 케이스)

`tests/test_state.py`
- as_of 이후 거래가 잔액·봉투·큐에 영향을 주지 않는다 (같은 원장, as_of 두 개).
- primary 계좌 잔액 == 정답 `daily_balance[as_of]` (3 프로필, as_of 3개).
- `propose_budgets`: 완결 월 3개 이상일 때 중앙값·만원 올림; 완결 월 0개일 때 28일 환산.
- 큐: B 프로필 as_of 화요일 → 화요일 카드 미결제/미청구 항목의 due·금액이 원장에서 직접 계산한 값과 일치.
- 월요일 as_of 의 `unbilled` 경계(당일부터).
- 카드대금이 봉투 `spent` 에 포함되지 않는다.

`tests/test_behavior.py`
- 요일 배수 평균 1.0 (±1e-9), `n<10` 이면 전부 1.
- sigma 클립, 데이터 부족 시 pooled/기본값.
- `detect_income_schedule`: A → 규칙적(25일), C → 불규칙, 수입 1건 → None.
- 탄력도: 저잔여 날 < 5 → 1.0.
- 순환 금지: `behavior.py` 소스에 "ground_truth", "hidden_params", "yaml" 문자열이 없다.

`tests/test_simulate.py`
- 재현성: 같은 시드 두 번 → `balances` 바이트 동일.
- `daily_rate=0`, 돌발 0 인 Behavior → 모든 경로 동일, 궤적 = 큐·수입만 반영한 결정론 계단.
- 전이 순서 검증: 수작업 3일 시나리오(수입일, 고정비, 월요일 청구, 출금 요일)에서 기대 잔액 정확 일치.
- 카드 출금 부족 → `card_shortfall=True`, 잔액 되돌림, 다음 날 재시도.
- What-if: 주입 금액 ≥ 0 이면 분기 `min_balance ≤ 기본 min_balance` (CRN 이면 항상 성립). 주입 0원 → 델타 전부 0.
- 리스크 단조성: 주입 금액 증가 → `card_shortfall_prob` 비감소.
- 성능: 1000경로×30일 < 2초.

`tests/test_goal.py`
- 목표가 현 잔액보다 작고 수입 충분 → feasible, reduction 0.
- 불가능 목표 → infeasible + 부족액.
- 필수 봉투 하한 80% 보장. 주차 상한 합 == available (±100원×주 수).

`tests/test_analytics.py`
- Safe-to-Spend ≥ 0. 고정비 > 잔액이면 0 + note.
- 재배분: 필수 봉투에서 이동 없음(모든 프로필·as_of 전수). 이동 합 ≤ shortfall.
- 우려 결제: 문서 예시(예산 60만, 월말 잔여 2만, 결제 1.5만) 미발동; (예산 60만, 잔여 20만, 결제 12만) 발동 WARNING; (결제 25만) DANGER.
- 가속도: 7일 평균 1만 미만 노이즈 플로어.
- health 경계값 70/40.

`tests/test_projection.py`: 매핑표 전수.

`tests/test_tools.py` (LLM 없이)
- `TOOL_SPECS` 가 유효한 JSON Schema, 이름 유일.
- 파라미터 정규화: 봉투 동의어, 금액 표기 12종, 상대 날짜 8종.
- `execute_tool` 전 툴 실행 → JSON 직렬화 가능, 예외 시 `error` 키.

`tests/test_coach.py` (LLM 없이)
- `extract_numbers` 20 케이스("1만 8천원", "21만원", "35%", "3일 뒤", "2026-09-25", "1,250,000원").
- `allowed_numbers` 파생값 포함.
- `check_faithful`: 만원 허용 오차 경계(±5,000), 없는 숫자 검출.
- 템플릿 폴백: 전 의도 × 전 페르소나 충실도 100%.

`tests/test_architecture.py`: import 그래프(§10), stub 잔존(`NotImplementedError`) 0건 — 최종 단계 검사 활성화 완료.

### 11.2 불변식(속성) 테스트

3 프로필 × as_of 후보(매주 월요일, 데이터 90일 이후 전부)에 대해:
- `Σ봉투 spent(월) == ground_truth.envelope_true_spend` (이미 원장 테스트로 보장, State 경유로 재확인).
- `State.liquidity == daily_balance[as_of][primary]`.
- `forecast.median[0] == liquidity`.
- `0 ≤ shortfall_prob, card_shortfall_prob ≤ 1`, `card_shortfall_prob ≤ shortfall_prob + 0.05`(출금 부족은 잔액 음수의 부분집합에 가깝다; 되돌림 때문에 정확 부분집합은 아님 → 허용 오차).
- `health_score ∈ [0,100]`.

### 11.3 통합 테스트

`tests/test_pipeline.py`: `gen(짧은 기간, 임시 디렉터리) → ingest → state → forecast/risk/analyze → project_room → 템플릿 코칭` 이 3 프로필에서 예외 없이 끝나고 결과 JSON 이 스키마를 만족한다. LLM 은 사용하지 않는다.

### 11.3.1 대시보드·HTTP 통합 테스트

`tests/test_web.py` 는 LLM 없이 실제 A/B/C seed를 사용해 다음을 검증한다.

- `/`, 정적 CSS/JS, `/api/health`, `/api/profiles` 가 200이고 한글 UTF-8과 JSON 직렬화를 만족한다.
- 금융 프로필과 코치 페르소나 선택이 분리되며, `as_of` 이후 거래가 상태·화면 JSON 에 섞이지 않는다.
- start → message(상태/예측/What-if/목표 각 1건) → end 흐름이 동작하고 응답에 `faithful`, `fallback`, `route`, `results` 가 항상 있다.
- 잘못된 프로필·세션·날짜·금액은 404/422이다. 같은 세션의 동시 메시지는 순서대로 처리된다.
- LLM 미가동 시 200 + `fallback=true`, 엔진 로드 실패 시 503으로 구분한다.
- JavaScript가 참조하는 HTTP 경로와 서버 route 목록이 일치한다. 시각·반응형·키보드 조작은 실제 브라우저에서 별도 확인한다.

### 11.4 백테스트 (SIM-01 정확도) — `eval/backtest.py`

절차
1. 프로필별 `as_of = end − 30`. 원장·스냅샷은 그대로 넘기되 State/Behavior 가 as_of 필터를 지키는지에 의존(§11.1 첫 케이스가 보장).
2. `forecast(horizon=30, n_paths=1000, seed=42)`.
3. 정답 `daily_balance[d][primary]`, d = as_of+1 … as_of+30.

지표
- `MAE = mean|median_k − truth_k|`
- `sMAPE = mean( |m−t| / ((|m|+|t|)/2 + 100,000) )` (잔액 0 근처 폭주 방지용 10만원 가산)
- 최저점 오차: `|min(median) − min(truth)|`, 최저일 차이(일)
- 커버리지: `mean( p10_k ≤ truth_k ≤ p90_k )`

합격 기준 (초기 목표, 미달 시 원인 분석 보고 필수)

| 프로필 | sMAPE | 최저점 오차 | 커버리지 |
| --- | --- | --- | --- |
| A | ≤ 0.15 | ≤ 300,000원 | 0.6~0.95 |
| B | ≤ 0.25 | ≤ 300,000원 | 0.6~0.95 |
| C | ≤ 0.40 | ≤ 500,000원 | 0.5~0.95 |

C 는 불규칙 수입 때문에 기준이 느슨하다. 커버리지 상한은 "밴드가 너무 넓어 무의미"를 걸러낸다.

보고서: `data/out/eval/backtest.json` + 프로필별 CSV(날짜, p10, median, p90, truth).

### 11.5 리스크 캘리브레이션 (SIM-03) — `eval/calibration.py`

절차
1. 표본: 3 기본 프로필 + **시드 교란 프로필 20개**(각 프로필에 `generate(seed=k)` 로 다른 시드, 기간 동일). 총 23 사용자.
2. 각 사용자에 대해 `as_of` 를 데이터 시작+90일부터 end−30 까지 7일 간격으로 이동.
3. 각 (사용자, as_of) 에서 `risk(horizon=30)` 의 `card_shortfall_prob = p`. 실제 `y` = 정답 `card_shortfalls` 중 `as_of < date ≤ as_of+30` 인 건 존재 여부.
4. 쌍 (p, y) 수집 → 5 구간(0~0.2, …) 별 평균 p 와 실제 비율.

지표·기준
- ECE(기대 캘리브레이션 오차) `≤ 0.15`
- Brier 점수 `< 기준율 Brier` (항상 기준율을 예측할 때보다 나아야 함)
- 구간별 표본 수 보고(표본 < 15 구간은 판단 보류 표시)

### 11.6 코칭 충실도 — `eval/faithfulness.py`

- 시나리오 파일 `data/eval/scenarios.yaml`: 30개(프로필 × 의도 조합, "다음 주에 15만원짜리 신발 사도 돼?" 같은 발화 포함).
- 3 페르소나 × 30 = 90 실행 (LLM 필요, Ollama 가동 상태에서만).
- 지표: 1차 통과율, 재생성 후 통과율, 폴백률, **최종 응답 불충실 건수(= 0 이어야 함, 폴백은 허용)**.
- 기준: 최종 불충실 0건, 폴백률 ≤ 20%, 1차 통과율 ≥ 80%. 폴백률이 높으면 프롬프트를 고치되 검사 규칙을 느슨하게 하지 않는다.

### 11.7 툴 라우팅 평가 (FDT-INP-02)

- `data/eval/utterances.yaml`: 40개 한국어 발화, 라벨 `{tool, args}`. 예: "이번 달 남은 돈 얼마야"→`safe_to_spend`; "다음 주 금요일에 30만원 쓰면 카드값 괜찮아?"→`what_if{amount:300000, days_from_now:N, envelope:?}`; "12월까지 200만원 모으려면"→`goal_plan`.
- 지표: 툴 정확도 ≥ 0.85, 파라미터 완전 일치율 ≥ 0.75(봉투는 동의어 정규화 후 비교, 날짜는 ±1일).
- LLM 미가동 시 규칙 기반 라우터로 같은 평가를 돌려 기준선(≥ 0.6)을 기록한다.

### 11.8 성능 기준

| 항목 | 기준 |
| --- | --- |
| `build_state` + `estimate_behavior` (6개월 원장) | < 1초 |
| `simulate` 1000경로 × 30일 | < 2초 |
| `what_if` (2회 시뮬) | < 4초 |
| 프로필 대시보드 초기 JSON(State + Risk + Room) | < 3초 |
| 캘리브레이션 전체(23×~12 as_of) | < 15분 |
| LLM 툴 선택 + 코칭 (GPU) | < 20초/턴 |

### 11.9 리뷰 절차

1. 구현자는 PR(또는 커밋 묶음) 설명에 **설계서 절 번호, 테스트 목록, 벤치 수치** 를 적는다.
2. 리뷰어(다른 에이전트 또는 사람)는 §12 체크리스트를 항목별로 확인하고 결과를 커밋 메시지 혹은 `docs/reviews/YYYYMMDD_<모듈>.md` 에 남긴다.
3. 설계와 다르게 구현했으면 이 문서를 먼저 수정하는 커밋을 별도로 낸다.

---

## 12. 코드 리뷰 체크리스트

- [ ] 숫자를 만드는 코드가 `twin/`·`ledger/` 에만 있는가. `agent/` 에 사칙연산이 있으면 이유가 있는가(포맷팅 외 금지).
- [ ] `as_of` 필터가 모든 원장 접근에 적용되는가(홀드아웃 누수 없음).
- [ ] 난수 시드가 인자로 들어오고 전역 RNG 가 없는가. `hash()`, `random` 사용 없음.
- [ ] 생성기 정답·YAML 숨은 파라미터를 트윈 코드가 읽지 않는가.
- [ ] 전이 순서가 §7.3 와 생성기 순서와 동일한가.
- [ ] 카드대금 이중 차감이 없는가(봉투 spent, 시뮬 지출 양쪽).
- [ ] What-if 가 같은 시드를 쓰는가.
- [ ] 필수 봉투에서 재배분으로 빼는 경로가 없는가.
- [ ] 우려 결제 규칙에 `3 × pace_unit` 정규화가 있는가.
- [ ] 코칭 결과에 `faithful/fallback` 플래그가 항상 있는가. 검사 실패를 조용히 통과시키는 코드가 없는가.
- [ ] 대시보드가 코어 숫자·위험 판정을 JavaScript나 `web.py`에서 다시 계산하지 않는가.
- [ ] 금융 프로필과 코치 페르소나가 UI·HTTP 입력에서 분리되어 있는가.
- [ ] `DEMO`/`LIVE`, 엔진 준비, LLM/fallback 상태가 화면에서 구분되는가.
- [ ] 기본 host가 `127.0.0.1` 이고 LLM 장애와 엔진 장애의 HTTP 상태가 §9.2.3과 같은가.
- [ ] LLM 미가동 시 전체 CLI 가 동작하는가.
- [ ] 금액 int, 100원/1,000원/만원 단위 규칙이 문서와 같은가.
- [ ] 테스트가 §11.1 목록을 모두 포함하고 통과하는가. 벤치 수치가 §11.8 안인가.
- [ ] docstring 절 번호, 한국어 사용자 문자열, UTF-8.

---

## 13. 작업 분할 (WBS) 과 병렬 투입 규칙

| 작업 | 담당 파일 | 선행 | 완료 정의(DoD) |
| --- | --- | --- | --- |
| T1 State | `twin/state.py`, `tests/test_state.py` | 없음 | §7.1 전부, §11.1 state 케이스 통과, 3 프로필 잔액 == 정답 |
| T2 Behavior | `twin/behavior.py`, `tests/test_behavior.py` | 없음 (budgets 는 `propose_budgets` 필요 → T1 의 그 함수만 선행. 먼저 구현·커밋) | §7.2, 순환 금지 테스트 |
| T3 Simulator | `twin/simulate.py`, `tests/test_simulate.py` | T1, T2 의 스키마(이미 확정)만. 테스트용 State/Behavior 는 손으로 만든 fixture 사용 | §7.3~7.4, 성능, CRN 단조성 |
| T4 Goal + Analytics + Projection | `twin/goal.py`, `twin/analytics.py`, `twin/projection.py`, 테스트 3개 | T3 (risk 사용) | §7.5~7.7 |
| T5 Tools + Coach(검사·템플릿) | `agent/tools.py`, `agent/coach.py`, `agent/llm.py`, `tests/test_tools.py`, `tests/test_coach.py` | T1~T4 함수 시그니처(확정) | LLM 없이 전 테스트 통과, 템플릿 충실도 100% |
| T6 Agent + CLI | `agent/agent.py`, `cli.py` | T5 | `fdt brief/chat/analyze/...` 동작, LLM 유무 양쪽 |
| T7 Eval | `eval/*.py`, `data/eval/*.yaml`, `tests/test_pipeline.py` | T1~T6 | 4종 보고서 생성, 기준 충족 여부 표 |
| T8 Dashboard | `web.py`, `static/*`, `tests/test_web.py`, `cli.py`의 serve 명령 | T1~T6 공개 함수 | §9.2 HTTP 계약, A/B/C 브라우저 흐름, LLM 유무 양쪽 통과 |
| T9 마감 | `tests/test_architecture.py`, README, 이 문서 갱신 | 전부 | stub 0건, 전체 테스트 통과 |

병렬 규칙: T1/T2/T3 동시 가능(T3 는 fixture 로 시작). T4 는 T3 뒤. T5 는 T1~T4 의 **시그니처**만 있으면 시작 가능(결과 dict 는 스키마에서 생성). T8 정적 UI는 먼저 만들 수 있지만 실제 연동 완료 판정은 T1~T6 뒤에만 한다. 공용 파일 수정 필요 시 §10 규칙.

각 작업의 마지막 커밋 메시지 예: `기능: State(t) 산출과 예산 제안 구현 (FDT 설계 §7.1, FR-BGT-01)`.

---

## 14. 리스크와 미결

| # | 항목 | 영향 | 대응 |
| --- | --- | --- | --- |
| R1 | 미결제 청구서 재시도 규칙이 금융망 실제와 다를 수 있음 | 리스크 확률 정의가 흔들림 | 생성기·시뮬레이터가 같은 가정. LIVE 검증 후 한 곳(§7.3 4단계)만 수정 |
| R2 | 7B 로컬 모델의 tool calling 실패율 | 라우팅 정확도 미달 | 규칙 기반 라우터 폴백, few-shot 예시 6개를 시스템 프롬프트에 포함, 실패 시 `get_state` |
| R3 | 3 프로필로는 캘리브레이션 표본 부족 | ECE 신뢰도 낮음 | 시드 교란 20 프로필(§11.5) |
| R4 | 불규칙 수입(C) 예측 오차 | 백테스트 기준 미달 | 기준을 별도 설정. 개선안: 수입 간격 분포 샘플링(현재는 중앙값 고정) → v1.1 |
| R5 | 봉투 예산 주기가 달력 월인데 급여일이 25일/10일 | 월초 진행률 기반 규칙이 급여 주기와 어긋남 | v1.0 은 달력 월 고정. 급여 주기 옵션은 v1.1 |
| R6 | 돌발 지출이 봉투 추정에 이중 계상 | 예측이 약간 보수적 | 백테스트 커버리지로 감시 |
| R7 | qwen3:8b 등 대체 모델 | 한국어 품질 | 라우팅·충실도 평가를 모델별로 돌려 표로 비교 후 결정 |
| R8 | 코어 결과와 대시보드 JSON 불일치 | 화면은 보이지만 숫자 의미가 달라짐 | `model_dump` 원본 전달 + `tests/test_web.py` 계약 테스트, UI 재계산 금지 |
| R9 | 금융 프로필과 코치 페르소나 혼동 | 개인화 기준과 말투가 뒤섞임 | 선택 UI·요청 필드·표시명을 분리 |
| R10 | 인증 없는 로컬 서버 외부 노출 | 더미 또는 향후 LIVE 금융정보 노출 | 기본 `127.0.0.1`, v1.0 외부 공개 금지. 운영화 시 인증·권한·CSRF를 별도 설계 |

---

## 15. 부록

### A. 카드 청구 주기 예시 (B 프로필, KB카드 화요일 출금)

| 날짜 | 요일 | 사건 |
| --- | --- | --- |
| 3/2~3/8 | 월~일 | 승인 누적 103,500 |
| 3/9 07:30 | 월 | 청구서 발행 103,500 |
| 3/10 16:00 | 화 | 출금 103,500 (잔액 충분) |
| 3/16 07:30 | 월 | 청구서 167,800 |
| 3/17 16:00 | 화 | 잔액 120,000 → 부족. 미결제 유지, `card_shortfall` |
| 3/18 16:00 | 수 | 재시도(설계 가정). 잔액 200,000 → 출금 |

### B. 툴 결과 JSON 예 (`safe_to_spend`)

```json
{"as_of":"2026-09-02","liquidity":783360,"committed_until_income":612000,"days_until_income":8,
 "raw_daily":21420,"acceleration":1.12,"safe_today":19100,"note":"비상금 350,000원 별도"}
```
허용 숫자 집합에는 783360, 780000, 78, 612000, 610000, 61, 8, 21420, 21000, 2, 1.12, 12, 19100, 19000, 2, 350000, 350000, 35 … 가 들어간다. "오늘은 1만 9천원 안에서 쓰자냥" 은 통과, "오늘은 2만 5천원까지" 는 위반.

### C. 우려 결제 규칙 수치 예

| 예산 | 잔여(직전) | 결제 | 0.5×잔여 | 3×pace | 판정 |
| --- | --- | --- | --- | --- | --- |
| 600,000 | 20,000 | 15,000 | 10,000 | 60,000 | 미발동 (월말 과민 방지) |
| 600,000 | 200,000 | 120,000 | 100,000 | 60,000 | WARNING |
| 600,000 | 200,000 | 250,000 | 100,000 | 60,000 | DANGER (잔여 초과) |
| 100,000 | 90,000 | 45,000 | 45,000 | 10,000 | WARNING |
