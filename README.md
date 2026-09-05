# Finance-Digital-Twin (FDT)

KeyFin 개인 금융 디지털 트윈의 원장·전이·예측 엔진과 로컬 코칭 대시보드입니다. DEMO 데이터만 사용하며 실제 이체·결제를 실행하지 않습니다. 같은 입력과 난수 시드로 계산을 재현할 수 있지만 미래 금융 상태를 확정적으로 예측하는 것은 아닙니다.

## 설치와 실행

Python 3.12 이상과 uv가 필요합니다. 저장소 루트에서 실행합니다.

```sh
uv sync --locked --extra dev
uv run --locked --extra dev python -m fdt.cli serve
```

브라우저에서 `http://127.0.0.1:8787`을 엽니다. 금융 프로필과 코치 페르소나는 별도로 선택합니다. Ollama가 없으면 규칙 라우팅·템플릿 코칭으로 전환하며, 금융 숫자는 FDT 코어가 계산합니다.

일반 대화는 별도 `chat` 경로로 처리하고, 명시적 금융 요청에서 구매 비교·잔액 예측·목표 계획 등의 도구를 실행합니다. 필수 금액·날짜가 없거나 유효하지 않으면 입력을 요청하며, 계산 실패를 성공 결과로 안내하지 않습니다.

```sh
uv run --locked --extra dev python -m fdt.cli state data/seed/A_steady
uv run --locked --extra dev python -m fdt.cli analyze data/seed/A_steady
```

Windows 통합 실행기는 `FDT_통합실행.bat`입니다. 직접 가상환경 Python을 사용할 때 한글 출력이 깨지면 PowerShell에서 `$env:PYTHONIOENCODING="utf-8"`을 설정합니다.

주요 명령은 `gen`, `ingest`, `state`, `forecast`, `whatif`, `risk`, `goal`, `analyze`, `brief`, `chat`, `serve`, `eval`입니다.

## 테스트와 빌드

```sh
uv run --locked --extra dev pytest -q
node --test tests/js/dashboard.test.cjs
uv build
```

JavaScript 회귀 테스트는 Node.js 22에서 별도 npm 설치 없이 실행합니다. CI는 잠금된 의존성으로 Python·JavaScript 테스트, 소스 배포본·wheel 빌드, 설치된 wheel에서 데모 프로필과 코어 실행을 검증합니다. 테스트 성공은 실제 Ollama 품질이나 예측 확률의 정확성 인증을 뜻하지 않습니다.

## 운영 경계와 설정

이 서버는 인증 없는 **로컬 데모**입니다. 공인 IP, 터널, 공유 프록시를 통한 공개 배포를 하지 마세요. 실제 사용자 데이터를 연결하려면 인증·세션 소유권·로그 보관 및 삭제 정책을 별도로 구현해야 합니다.

| 설정 | 기본값과 용도 |
| --- | --- |
| `FDT_SEED_DIR` | 소스 실행 시 `data/seed`, wheel 실행 시 패키지의 `demo/seed`. 외부 데모 데이터 경로를 지정할 수 있습니다. |
| `FDT_OLLAMA_URL` | 로컬 Ollama 주소. 기존 기본값은 `fdt/agent/llm.py`에 정의합니다. |
| `FDT_LLM_MODEL` | 사용할 Ollama 모델 이름. |
| `FDT_LLM_TIMEOUT` | 웹 LLM 요청 제한 시간, 기본 20초. |
| `FDT_TURN_LOG_DIR` | 기본 `log/turns`. 쓰기 가능한 로컬 경로를 지정하세요. |
| `FDT_ENABLE_LOG_API` | 기본 `0`. 개발 중 `1`로 설정하면 로컬 연결에서만 로그 API를 조회할 수 있습니다. 인증을 대신하지 않습니다. |

세션은 생성 중인 항목을 포함해 최대 64개이고, 30분 동안 사용하지 않으면 만료됩니다. 목표일은 기준일 이후 최대 365일, What-if 지출일은 0~60일, 채팅의 예측·위험 기간은 7~60일입니다. 채팅의 금액 입력은 0~1조 원의 정수 원으로 제한합니다.

`/api/live`는 가벼운 생존 확인, `/api/health`는 입력 데이터와 LLM 준비 상태 확인입니다. 상태 확인 요청에서 위험 시뮬레이션을 반복하지 않습니다.

## 턴 로그

턴은 `log/turns/YYYY-MM-DD/<surface>-<session_id>.jsonl`에 UTF-8 JSONL로 기록됩니다. 원문 대화가 포함되므로 민감정보를 입력하지 마세요. 로그를 공개 저장소에 추가하지 않습니다.

```sh
uv run --locked --extra dev python -m fdt.cli eval report --log-dir log/turns
```

로그 API는 기본 비활성화되어 있습니다. 활성화한 로컬 개발 환경에서는 여러 세션의 기록을 레코드 타임스탬프 기준으로 병합하며, 기존 일자별 평면 로그도 읽습니다.

## 설계와 한계

구현 기준은 [설계서](docs/03_FDT_설계.md)와 [리뷰 보완 계약](docs/04_FDT_리뷰보완.md)입니다. 변경 및 검증 내역은 [개발 기록](docs/devlog/260905.md)에 남깁니다.

목표의 `feasible`은 현재 총액·봉투 배분 규칙의 결과이며, 중간 결제일의 안전성이나 목표 달성 확률을 보장하지 않습니다. 필드별 설명 의미 검증, 과거 관측 시각 보존, 경로별 공통 난수, 목표 계획 재시뮬레이션, 실제 금융망 카드 재시도 규칙은 후속 설계 과제로 남아 있습니다.
