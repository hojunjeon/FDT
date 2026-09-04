# FDT 개인 금융 디지털 트윈 설명서

## 문서 목적

FDT(Finance Digital Twin)는 KeyFin의 개인 금융 분석·시뮬레이션 코어다. 금융 거래를 정리해 현재 재무 상태를 만들고, 사용자의 소비 습관을 추정한 뒤, 앞으로 돈이 어떻게 움직일지 계산한다.

이 문서는 현재 저장소에 구현된 FDT의 입력, 내부 구조, 개인화 방식, 기능과 범위를 설명한다. 구현의 단일 기준은 [03_FDT_설계.md](03_FDT_설계.md)다.

FDT는 사용자의 돈을 직접 이체하거나 결제하는 시스템이 아니다. 현재 저장소는 합성 DEMO 데이터를 사용하며, 실제 금융망 연동은 다음 단계의 작업으로 남아 있다.

## 1. FDT를 한 문장으로 이해하기

FDT는 다음 세 가지를 합쳐 사용자의 금융 상태를 재현한다.

| 구성 요소 | 쉬운 설명 | 핵심 질문 |
| --- | --- | --- |
| State(t) | 기준일 현재의 재무 상태 사진 | 지금 얼마가 있고, 곧 무엇이 나가는가? |
| Behavior | 거래 이력에서 추정한 소비 습관 | 이 사용자는 언제, 어디에, 얼마를 쓰는가? |
| Transition | 하루가 지나가는 회계 규칙 | 오늘 하루가 지나면 잔액이 어떻게 변하는가? |

따라서 FDT는 하나의 학습된 신경망이 아니다. State(t)와 Behavior를 사용자별로 만들고, 정해진 Transition 규칙으로 미래를 계산하는 결정론적 시뮬레이션 엔진이다.

Qwen 같은 LLM은 이 계산에 참여하지 않는다. LLM은 사용자의 질문을 적절한 분석 도구로 연결하고, 코어가 계산한 숫자를 자연어로 설명하는 역할만 맡는다.

## 2. 입력값

### 2.1 DEMO 데이터를 만들 때 사용하는 입력

fdt/data/profiles/*.yaml은 금융망 응답을 흉내 낸 DEMO 거래를 생성하는 재료다.

| 입력 | 예시 | 역할 |
| --- | --- | --- |
| 사용자 정보 | 이름, 설명, 프로필 ID | DEMO 사용자 식별 |
| 기간·seed | 시작일, 종료일, 난수 seed | 같은 조건에서 같은 데이터 재생성 |
| 계좌 | 주거래 계좌, 비상금 계좌, 초기 잔액 | 계좌 거래 생성 |
| 카드 | 카드 번호, 출금 계좌, 출금 요일 | 카드 승인·청구·출금 생성 |
| 수입 | 월급 또는 불규칙 입금, 금액, 입금일 | 수입 거래 생성 |
| 고정비 | 월세, 관리비, 통신, 구독, 보험, 대출이자 | 약정 지출 생성 |
| 소비 설정 | 봉투별 발생률, 금액 분포, 요일 배수, 카드 비율 | 합성 소비 패턴 생성 |
| 돌발 설정 | 돌발 지출 확률·금액, 취소·더치페이 확률 | 합성 예외 상황 생성 |

생성기는 snapshot.json과 ground_truth.json을 함께 만든다.

~~~text
프로필 YAML + seed
        ↓
    generator.py
        ↓
snapshot.json       금융망 응답 형식의 입력
ground_truth.json   평가용 정답과 숨은 생성 파라미터
~~~

ground_truth.json과 YAML의 spending 값은 평가용·생성용이다. fdt/twin 코어는 이 파일을 읽지 않고, 생성된 거래 이력만 보고 행동을 추정한다. 이 경계가 있어야 미래 정답을 미리 보는 순환 검증을 피할 수 있다.

### 2.2 실행 시 FDT 코어가 받는 입력

금융망 형식의 입력 구조는 [fdt/schemas/finapi.py](../fdt/schemas/finapi.py)에 정의되어 있다.

| 입력 | 포함 내용 | 사용처 |
| --- | --- | --- |
| FinSnapshot | 계좌, 계좌 거래, 카드, 카드 거래, 청구서, 구독, 대출 | 현재 상태와 원장 구성 |
| as_of | 트윈 기준일 | 기준일 이후 거래를 제외 |
| budgets | 사용자가 조정한 봉투 예산 | 자동 제안 예산을 덮어씀 |
| seed | 난수 생성 seed | 예측 재현성 |
| VirtualSpend | 금액, 봉투, 날짜, 카드 여부 | What-if 가상 지출 |

FinSnapshot은 다음 영역을 가진다.

~~~text
accounts
accountTransactions
cards
cardTransactions
billingStatements
subscriptions
loans
~~~

금융망이 금액을 문자열로 내려주는 경우를 고려해 경계에서 int로 변환한다. 코어 내부 금액 단위는 모두 원이며, 금액 계산은 정수로 처리한다.

### 2.3 대화 입력

에이전트 계층은 코어 입력과 별도로 다음을 받는다.

| 입력 | 역할 |
| --- | --- |
| 사용자 발화 | 어떤 금융 기능을 원하는지 파악 |
| 최근 대화 이력 | 질문의 문맥 유지 |
| 코치 페르소나 | 도도냥·온순냥·지방냥 말투 선택 |
| 툴 명세 | LLM이 호출할 수 있는 기능과 인자 제한 |

대화 입력은 숫자를 직접 계산하지 않는다. LLM이 선택한 툴의 인자는 검증·정규화한 뒤 코어 함수에 전달한다.

## 3. 전체 처리 흐름

~~~mermaid
flowchart LR
    A["FinSnapshot"] --> B["ingest.py"]
    B --> C["LedgerTx 정규화 원장"]
    C --> D["build_state"]
    C --> E["estimate_behavior"]
    D --> F["State(t)"]
    E --> G["Behavior"]
    F --> H["simulate"]
    G --> H
    H --> I["forecast / what-if / risk"]
    F --> J["goal / safe-to-spend / rebalance / alerts"]
    I --> K["코어 결과 JSON"]
    J --> K
    K --> L["코칭·대시보드"]
~~~

텍스트로 쓰면 다음과 같다.

~~~text
금융망 응답
→ 원장 정규화
→ State(t)와 Behavior 생성
→ Transition으로 미래 경로 계산
→ 예측·위험·진단·목표 결과 생성
→ LLM 코칭과 대시보드에 전달
~~~

## 4. 1단계: 원장 정규화

fdt/ledger/ingest.py는 계좌 거래와 카드 거래를 하나의 LedgerTx 목록으로 합친다. LedgerTx의 구조는 [fdt/schemas/domain.py](../fdt/schemas/domain.py)에 있다.

| 필드 | 내용 |
| --- | --- |
| occurred_at | 거래 일시 |
| instrument | 계좌 또는 카드 |
| instrument_no | 계좌번호 또는 카드번호 |
| amount | 수입은 양수, 지출은 음수 |
| flow | 수입, 고정비, 카드대금, 소비, 환불, 내 계좌 이체 |
| merchant | 가맹점명 |
| envelope | 외식·교통비 등 7개 봉투 |
| confidence | 분류 확신도 |
| fixed_kind | 월세·통신·구독·보험·대출이자 등 |

가맹점 분류 순서는 다음과 같다.

~~~text
고정비 가맹점 표
→ 가맹점·세분류 매핑 표
→ 선택적 폴백 분류기
→ 기타
~~~

모든 소비 거래는 정확히 하나의 봉투에 한 번만 들어간다. 카드 취소는 원 승인 지출과 환불 거래를 모두 남겨 이력을 보존한다. 계좌에서 빠져나간 카드대금은 이미 카드 소비로 차감된 금액을 다시 봉투에서 차감하지 않는다.

## 5. 2단계: State(t) 만들기

구현 함수는 다음 형태다.

~~~python
build_state(
    txs,
    snap,
    as_of,
    budgets=None,
) -> State
~~~

### 5.1 생성 순서

| 순서 | 처리 내용 |
|---:|---|
| 1 | occurred_at.date() <= as_of인 거래만 남긴다. |
| 2 | 첫 거래의 잔액 정보를 이용해 계좌 개설잔액을 역산한다. |
| 3 | 계좌별 거래를 합산해 현재 잔액을 계산한다. |
| 4 | 카드 출금 계좌를 주거래 계좌로 정하고 나머지 계좌를 비상금으로 계산한다. |
| 5 | 과거 소비를 이용해 7개 봉투의 예산과 이번 달 사용액을 계산한다. |
| 6 | 카드 미청구액과 미결제 청구서를 카드별로 계산한다. |
| 7 | 월세·관리비·보험·구독·대출·카드대금의 약정 지출 큐를 만든다. |
| 8 | 다음 수입일, 예상 수입, 최근 소비 평균, 소비 가속도를 계산한다. |

### 5.2 State 내부 구조

~~~text
State
├─ as_of
├─ liquidity                 주거래 계좌의 현재 유동성
├─ emergency_fund            비상금 계좌 합계
├─ account_balances          계좌별 잔액
├─ primary_account_no        주거래 계좌
├─ committed[]               앞으로 나갈 약정 지출
├─ envelopes[]
│  ├─ envelope               봉투 이름
│  ├─ budget                 예산
│  ├─ spent                  이번 달 사용액
│  └─ remaining              남은 예산
├─ cards[]
│  ├─ unbilled               아직 청구되지 않은 카드 사용액
│  └─ issued_unpaid[]        발행됐지만 미결제인 청구서
├─ next_income_date
├─ expected_income
├─ spend_7d_avg
├─ spend_90d_avg
└─ acceleration
~~~

State는 “지금의 금융 상태”를 표현한다. 건강 점수와 상태 레벨은 위험 계산 뒤 진단 계층이 추가한다.

## 6. 3단계: Behavior 만들기

구현 함수는 다음 형태다.

~~~python
estimate_behavior(
    txs,
    as_of,
    window_days=90,
    budgets=None,
) -> Behavior
~~~

### 6.1 관측 범위

- 기본 관측 기간은 기준일을 포함한 최근 90일이다.
- 카드 승인과 취소가 같은 날·같은 금액으로 짝을 이루면 순수 소비 추정에서 상쇄한다.
- ground_truth.json이나 프로필 YAML의 숨은 파라미터는 사용하지 않는다.
- 데이터가 부족하면 요일 배수 1.0, 통합 금액 분포, 기본 돌발 확률 같은 보수적인 기본값을 사용한다.

### 6.2 추정하는 개인별 값

| 값 | 계산 방식 | 의미 |
| --- | --- | --- |
| daily_rate | 봉투별 거래 횟수 ÷ 관측 일수 | 하루 평균 소비 횟수 |
| weekday_mult | 요일별 거래 집중도와 축소 추정 | 어느 요일에 더 쓰는지 |
| amount_mu, amount_sigma | 소비 금액의 로그정규분포 | 평소 금액과 변동성 |
| card_share | 카드 거래 수 ÷ 전체 거래 수 | 카드 결제 성향 |
| payday_boost | 수입 후 7일 소비 평균 ÷ 평소 소비 평균 | 수입 직후 소비 증가 |
| elasticity | 예산 잔여율 20% 미만인 날과 그 외 날 비교 | 예산이 부족할 때 소비 변화 |
| income_dates | 수입 거래를 날짜별로 합산 | 수입 일정 |
| irregular_income | 수입 간격과 날짜 규칙성 검사 | 월급형인지 불규칙 입금인지 |
| shock_daily_prob | 큰 금액 거래의 관측 빈도 | 돌발 고액 지출 확률 |

봉투별 소비 횟수는 하루 발생률로 바꾸고, 미래 시뮬레이션에서는 요일 배수와 급여 후 배수를 곱한다.

~~~text
일일 소비 발생률
= 개인별 daily_rate
× 해당 요일 weekday_mult
× 급여 후 7일이면 payday_boost
× 예산이 20% 미만이면 elasticity
~~~

Behavior는 모델 가중치를 학습한 결과가 아니다. 거래 이력에서 계산한 사용자별 통계 파라미터다.

## 7. 4단계: Transition으로 하루 계산하기

Transition은 별도의 클래스로 저장되지 않고 fdt/twin/simulate.py의 simulate() 함수로 구현되어 있다.

~~~python
simulate(
    state,
    behavior,
    horizon_days=30,
    n_paths=1000,
    seed=42,
    injections=None,
) -> SimulationResult
~~~

### 7.1 하루 처리 순서

| 순서 | 처리 내용 |
|---:|---|
| 1 | 예정된 수입을 입금한다. |
| 2 | 계좌 고정비를 차감한다. 잔액이 부족하면 실제 잔액은 바꾸지 않고 의무로 기록한다. |
| 3 | 카드 고정비를 카드 미청구액에 더한다. |
| 4 | 월요일에 미청구 카드 사용액을 청구서로 발행한다. |
| 5 | 카드 출금일에 오래된 청구서부터 출금하고, 부족하면 다음 날부터 재시도한다. |
| 6 | Behavior에 따라 봉투별 소비 횟수와 금액을 생성한다. |
| 7 | 돌발 지출을 생성한다. |
| 8 | What-if 가상 지출을 적용한다. |
| 9 | 실제 잔액과 경제적 잔액을 기록한다. |

### 7.2 여러 미래 경로

시뮬레이터는 모든 경로를 numpy 배열로 동시에 계산한다.

~~~text
liquidity                 경로별 실제 주거래 잔액
card_liability            아직 출금되지 않은 카드 의무
unpaid_cash_obligation    거절된 계좌 고정비
suppressed_demand         잔액 부족으로 거절된 소비 수요
balances                  실제 잔액 시계열
economic_balances         경제적 의무까지 반영한 잔액 시계열
~~~

경제적 잔액은 다음처럼 계산한다.

~~~text
economic_balance
= liquidity
- card_liability
- unpaid_cash_obligation
- suppressed_demand
~~~

이 분리를 통해 “잔액이 부족해서 결제되지 않은 소비”가 What-if 분기에서 사라지는 오류를 막는다.

### 7.3 시뮬레이션 결과

| 기능 | 계산 | 결과 |
| --- | --- | --- |
| forecast | 미래 경로의 중앙값·P10·P90 계산 | 30일 잔액 전망 |
| what_if | 같은 seed로 기본 경로와 가상 지출 경로 비교 | 최저잔액·부족확률 델타 |
| risk | 경제적 잔액 기준 부족확률과 카드 부족확률 계산 | 0~100 위험 점수 |

같은 seed를 사용하면 같은 입력에서 같은 결과가 나온다. What-if는 원래 원장이나 State를 바꾸지 않고 메모리상의 분기에서만 계산한다.

## 8. 이 구조로 수행하는 기능

| 기능 ID | 기능 | 입력 | 처리 결과 |
| --- | --- | --- | --- |
| FDT-INP-01 | 가맹점 자동 분류 | 가맹점명·거래 요약 | 세분류와 7개 봉투 |
| FDT-INP-02 | 채팅 의도·인자 추출 | 사용자 자연어 | 호출할 툴과 금액·날짜·봉투 |
| FDT-SIM-01 | 30일 잔액 예측 | State + Behavior | 중앙값, P10/P90, 최저잔액 |
| FDT-SIM-02 | What-if 지출 | 가상 지출 JSON | 구매 전·후 잔액과 위험 변화 |
| FDT-SIM-03 | 결제 부족 위험 | State + Behavior | 부족확률, 위험 점수, 예상 부족액 |
| FDT-SIM-04 | 목표 역산 | 목표 금액·목표일 | 주차별·봉투별 지출 상한 |
| FDT-ANL-01 | Safe-to-Spend | 유동성·약정 지출·가속도 | 오늘 안심 소비 한도 |
| FDT-ANL-02 | 예산 재배분 | 봉투별 예산·초과 예상액 | 유연 봉투에서 이동할 금액 |
| FDT-ANL-03 | 소비 알림 | 최근 거래·행동 지표 | 가속도·우려 결제 알림 |
| FDT-INT-01 | 코칭 | 코어 결과 JSON·페르소나 | 숫자 충실도 검사를 거친 문장 |
| FDT-INT-02 | 방 상태 투영 | 건전성·알림·봉투 초과 | 날씨·표정·행동·코인 플래그 |
| FDT-WEB-01 | 로컬 HTTP 연동 | 프로필·세션·메시지 | FastAPI JSON API |
| FDT-UI-01 | 로컬 대시보드 | 서버 JSON | 잔액·봉투·예측·위험·채팅 화면 |

## 9. 개인화가 적용되는 지점

| 개인화 층 | 사용하는 데이터 | 개인별로 달라지는 값 |
| --- | --- | --- |
| 재무 구조 | 계좌·카드·청구서·구독·대출 | 현재 잔액, 카드 출금일, 고정비 |
| 소비 습관 | 최근 거래 90일 | 소비 빈도, 요일, 금액, 카드 비율 |
| 수입 패턴 | 수입 거래 날짜·금액 | 다음 수입일, 예상 수입, 불규칙성 |
| 예산 상태 | 과거 봉투 지출·사용자 조정 예산 | 봉투별 예산·잔여액 |
| 미래 질문 | What-if 금액·날짜·결제수단 | 특정 구매가 자신의 상태에 미치는 영향 |
| 표현 방식 | 코치 페르소나 | 같은 숫자를 말하는 말투 |

예를 들어 DEMO 프로필은 다음처럼 서로 다른 Behavior를 만든다.

| 프로필 | 관측되는 특성 | 시뮬레이션에서 중요해지는 요소 |
| --- | --- | --- |
| A 안정형 | 정기 급여, 체크카드 중심, 절약형 | 안정적인 수입과 낮은 소비 변동 |
| B 카드 집중형 | 카드 비율이 높고 고정비·카드 청구가 큼 | 카드 출금일과 청구 큐 |
| C 충동형 | 불규칙 수입, 주말 소비 증가, 큰 단건 결제 | 수입 불확실성, 주말 배수, 돌발 지출 |

실제 사용자를 연결할 때도 프로필 이름을 고르는 것만으로 개인화하지 않는다. 해당 사용자의 금융망 응답을 FinSnapshot으로 넣고, 기준일마다 State와 Behavior를 다시 계산한다.

## 10. LLM은 어디에 쓰이는가

에이전트 흐름은 다음과 같다.

~~~text
사용자 질문
→ LLM이 툴 선택과 인자 추출
→ 인자 정규화·검증
→ 결정론 코어 함수 실행
→ 엔진 결과 JSON을 LLM에 전달
→ 코칭 문장 생성
→ 숫자 충실도 검사
→ 실패하면 재생성, 다시 실패하면 템플릿 폴백
~~~

LLM이 하지 않는 일은 다음과 같다.

- 잔액을 계산하지 않는다.
- 위험 점수를 임의로 만들지 않는다.
- 예산을 마음대로 바꾸지 않는다.
- ground_truth.json을 읽지 않는다.
- 실제 결제나 이체를 실행하지 않는다.

Ollama가 꺼져 있어도 규칙 기반 툴 라우팅과 템플릿 코칭으로 코어 기능은 동작한다. LLM은 숫자 계산기가 아니라 인터페이스다.

## 11. 현재 범위와 한계

| 항목 | 현재 상태 |
| --- | --- |
| 금융 데이터 | data/seed/의 3개 합성 DEMO 프로필 |
| 실제 금융망 API | FinSnapshot 입력 형식만 준비, LIVE 커넥터는 미구현 |
| 이체·결제 실행 | 구현하지 않음 |
| 로그인·인증·운영 배포 | 구현하지 않음 |
| 알림 인프라·모바일 운영 UI | 구현하지 않음 |
| 게임 수준 방·고양이 애니메이션 | 정적 상태 파라미터만 제공 |
| 정책·혜택 RAG | policy_tips 인터페이스만 있고 현재 not_available |
| 브라우저 시각 QA | HTTP 계약 테스트와 정적 파일 검증 범위. 실제 브라우저 검증은 별도 |

서버는 인증이 없는 로컬 데모이므로 기본 바인딩을 127.0.0.1로 제한한다.

## 12. 검증 방법

현재 구현에는 다음 검증 경로가 있다.

~~~powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m fdt.cli eval backtest
.venv\Scripts\python -m fdt.cli eval calibration
.venv\Scripts\python -m fdt.cli eval routing
.venv\Scripts\python -m fdt.cli eval faithfulness
~~~

검증 의미는 다음과 같다.

| 검증 | 확인하는 것 |
| --- | --- |
| 단위·통합 테스트 | 원장, State, Behavior, 시뮬레이션, 분석, API 계약 |
| 백테스트 | 과거 기준일에서 30일 잔액 예측이 정답에 가까운지 |
| 캘리브레이션 | 위험확률이 실제 부족 발생률과 맞는지 |
| 툴 라우팅 | 자연어 질문을 올바른 기능과 인자로 연결하는지 |
| 코칭 충실도 | 코칭 문장의 숫자가 엔진 결과에서만 왔는지 |

자동 테스트 통과는 구현 계약을 확인하는 근거다. 실제 금융망 연결, 운영 환경, 브라우저 체감 품질, 별도 독립 리뷰 승인까지 완료했다는 뜻은 아니다.

## 13. 실행 예

상태 조회:

~~~powershell
.venv\Scripts\python -m fdt.cli state data/seed/A_steady
~~~

전체 분석:

~~~powershell
.venv\Scripts\python -m fdt.cli analyze data/seed/A_steady
~~~

로컬 대시보드:

~~~powershell
.venv\Scripts\python -m fdt.cli serve
~~~

또는 [FDT_통합실행.bat](../FDT_통합실행.bat)을 실행한다. 대시보드는 http://127.0.0.1:8787에서 열고, 다음 API를 제공한다.

~~~text
GET  /api/health
GET  /api/profiles
GET  /api/profiles/{profile_id}
POST /api/chat/start
POST /api/chat/message
POST /api/chat/end
~~~

## 14. 코드 위치

| 영역 | 주요 파일 |
| --- | --- |
| 금융망 입력 스키마 | fdt/schemas/finapi.py |
| 원장·도메인 스키마 | fdt/schemas/domain.py |
| 거래 인입·분류 | fdt/ledger/ingest.py, fdt/ledger/classify.py |
| 현재 상태 | fdt/twin/state.py |
| 행동 추정 | fdt/twin/behavior.py |
| 전이·예측·What-if·위험 | fdt/twin/simulate.py |
| 목표·진단·방 상태 | fdt/twin/goal.py, fdt/twin/analytics.py, fdt/twin/projection.py |
| LLM·툴·코칭 | fdt/agent/llm.py, fdt/agent/tools.py, fdt/agent/agent.py, fdt/agent/coach.py |
| HTTP·대시보드 | fdt/web.py, fdt/static/ |
| 평가 | fdt/eval/, data/eval/ |

## 15. 문서 간 우선순위

초기 기능 개념을 담은 docs/FDT.md와 구현 설계가 충돌하면 docs/03_FDT_설계.md의 결정을 따른다.

현재 구현의 기준은 다음과 같다.

- 가맹점 분류는 매핑 표를 먼저 사용하고, 미등록 거래만 선택적 폴백 분류기를 사용한다.
- 우려 결제는 단순 잔여 예산 50% 규칙만 사용하지 않고, 봉투의 하루 소비 속도와 최소 금액 기준을 함께 본다.
- 숫자 계산은 fdt/twin과 fdt/ledger에서만 수행한다.
- fdt/agent는 코어 결과를 선택하고 설명하며, fdt/web.py와 브라우저는 결과를 다시 계산하지 않는다.
