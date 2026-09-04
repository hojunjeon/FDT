# FDT 운영 지표

턴 로거가 남긴 JSONL을 집계해 에이전트 운영 상태를 확인하는 보고서다. 보고서 생성기는
`fdt.eval.report.run_report`이며, 금융 원장이나 트윈 계산에는 관여하지 않는다.

## 입력 로그

로그 루트는 `log/turns`이고 `FDT_TURN_LOG_DIR` 환경변수나 `TurnLogger` 생성자 인자로
바꿀 수 있다. `run_report`는 로그 루트 아래의 모든 `*.jsonl` 파일을 `rglob`으로 재귀
검색해 읽는다. 한 줄은 한 대화 턴이며 UTF-8과 `ensure_ascii=False`를 사용한다.

### 파일 경로 규칙

```
<로그루트>/<YYYY-MM-DD>/<surface>-<session_id>.jsonl
```

예: `log/turns/2026-09-04/web-3d36493c9ee94d45b5722b3c6bdbc9cc.jsonl`

- `<YYYY-MM-DD>`는 레코드의 `ts` 값에서 뽑은 날짜다. 한 세션이 자정을 넘기면 그 세션의
  로그가 날짜별로 두 파일에 나뉜다(의도된 동작).
- `<surface>`와 `<session_id>`는 파일명에 쓸 수 없는 문자(`[A-Za-z0-9_-]` 이외)를 `_`로
  치환하고 각각 최대 80자로 자른 값이다. 빈 값이면 `unknown`을 쓴다.
- 같은 세션의 여러 턴은 한 파일에 이어 쓴다(append).

### 왜 세션별로 파일을 나누는가

이전에는 하루치 로그가 `log/turns/YYYY-MM-DD.jsonl` 파일 하나에 몰렸다. 웹 서버와 CLI를
동시에 띄우면 서로 다른 프로세스가 같은 파일에 동시에 append하는데, 프로세스 내부 락
(`threading.Lock`)은 프로세스 경계를 넘어 파일을 보호하지 못한다. 세션·surface별로 파일을
쪼개면 서로 다른 세션의 쓰기가 물리적으로 다른 파일로 가서 경합이 사라지고, 특정 세션의
턴만 보고 싶을 때 파일 하나만 열면 되어 세션 단위 분석도 빨라진다.

### 하위 호환

`log/turns/2026-09-04.jsonl` 같은 옛 평면 파일이 이미 존재해도 `rglob("*.jsonl")`에
그대로 걸려 함께 읽힌다. 새 구조로 넘어가더라도 과거 로그가 사라지거나 무시되지 않는다.

```json
{
  "ts": "2026-09-04T09:12:33.123+09:00",
  "schema_version": 1,
  "surface": "web",
  "session_id": "string",
  "turn": 1,
  "profile_id": "B_card_crunch",
  "persona": "온순냥",
  "as_of": "2026-09-02",
  "llm_model": "qwen2.5:7b-instruct-q4_K_M",
  "user_message": "string",
  "reply": "string",
  "route": ["what_if", "coach"],
  "tool_calls": [{"name": "what_if", "args": {}, "result_summary": {"min_balance": 0}}],
  "faithful": true,
  "first_faithful": true,
  "attempt": 0,
  "fallback": false,
  "violations": [],
  "verdict_conflict": null,
  "latency_ms": {"total": 0, "engine": 0, "llm": 0},
  "llm_calls": 2,
  "tokens": {"prompt": 0, "completion": 0},
  "llm_error": null
}
```

`llm_model`과 `tokens`, `llm_error`, `verdict_conflict`는 해당 값이 없으면 `null`이다.
`result_summary`에는 로그를 키우는 원본 결과 대신 스칼라 필드만 넣는다. 잘못된 JSON 줄이나
JSON 객체가 아닌 줄은 버리고 `skipped_lines`에 센다. 빈 줄은 무시한다.

## 지표 정의

보고서의 최상위 `turns`는 읽은 유효 턴 수, `sessions`는 고유 `session_id` 수다.
`surfaces`는 `web`, `cli_chat`, `cli_brief`, `eval`별 턴 수이고, `routes`는 route 배열을
`" -> "`로 연결한 경로별 턴 수다. 빈 경로는 `(none)`으로 표시한다.

| 지표 | 계산식·의미 |
| --- | --- |
| `tool_calls` | `total`은 모든 턴의 호출 수, `by_tool`은 도구명별 호출 수, `avg_per_turn = total / turns` |
| `fallback` | `count`는 `fallback=true` 턴 수, `rate = count / turns`, `causes`는 해당 턴의 `llm_error.type`별 수. 오류가 없으면 `unknown` |
| `first_faithful` | `count`는 `first_faithful=true` 턴 수, `rate = count / turns` |
| `attempts` | `distribution`은 `attempt` 값별 턴 수, `avg`는 시도 횟수의 턴 평균 |
| `violations` | `by_type`는 `violations` 배열의 `type`(문자열이면 문자열 자체)별 건수, `total`은 항목 합계 |
| `verdict_conflict_count` | `verdict_conflict`가 있거나 위반 유형에 `verdict_conflict`가 포함된 턴 수 |
| `latency_ms` | `total`, `engine`, `llm` 각각의 p50·p95. 값은 오름차순 후 위치 `(n-1)×p`를 선형 보간 |
| `tokens` | `prompt`, `completion` 합계와 `total`; `avg_per_turn`은 각 합계를 전체 턴 수로 나눈 값 |
| `llm_errors` | `llm_error`가 있는 턴 수·비율과 `timeout`, `connection`, `parse`, `other` 유형별 수 |
| `models` | `llm_model`별로 위 집계를 같은 구조로 분리. JSON 키가 될 수 있도록 `null` 모델은 문자열 `null`로 표시 |

`fallback_rate`, `first_faithful_rate`, `llm_error_rate`는 각각의 중첩 집계와 같은 값을
바로 읽을 수 있게 최상위에도 제공한다. 턴 수가 0이면 비율과 평균은 `0.0`, 지연 값이
하나도 없으면 p50·p95는 `null`이다.

## 세션 단위 지표

전체 합산 지표만으로는 특정 사용자·특정 세션에서 무슨 일이 있었는지 알기 어렵다.
`run_report`는 최상위에 `session_summaries` 키로 세션별 지표 목록을 함께 반환한다.
`session_count`는 `sessions`(고유 세션 수)와 같은 값을 갖는 별칭 키이며, 파일 경로
계약의 `<session_id>` 단위와 이름을 맞추기 위해 추가했다. 기존에 이미 쓰이던 `sessions`
키(정수 카운트)의 의미는 바꾸지 않았다.

`session_summaries`의 각 항목은 다음 필드를 가지며, 목록은 `last_ts` 내림차순(최신
세션이 먼저)으로 정렬된다.

| 필드 | 의미 |
| --- | --- |
| `session_id` | 세션 식별자 |
| `surface` | 그 세션 첫 턴의 `surface` 값 |
| `profile_id` | 그 세션 첫 턴의 `profile_id` 값 |
| `persona` | 그 세션 첫 턴의 `persona` 값 |
| `turns` | 그 세션의 턴 수 |
| `first_ts` | 그 세션에서 가장 이른 `ts` (문자열 원본 그대로) |
| `last_ts` | 그 세션에서 가장 늦은 `ts` (문자열 원본 그대로) |
| `fallback_rate` | `fallback=true` 턴 수 / 턴 수 |
| `first_faithful_rate` | `first_faithful=true` 턴 수 / 턴 수 |
| `verdict_conflict_count` | `verdict_conflict_count`와 같은 규칙으로 센 세션 내 건수 |
| `violations_count` | 세션 내 모든 턴의 `violations` 항목 합계 |
| `llm_calls` | 세션 내 `llm_calls` 합계 |
| `tokens_total` | 세션 내 `tokens.prompt + tokens.completion` 합계 |
| `latency_total_p50`, `latency_total_p95` | 세션 내 `latency_ms.total` 값들의 p50·p95 (값이 없으면 `null`) |

한 세션의 턴 수는 항상 1 이상이므로 세션 내부 비율 계산에서 0으로 나누는 문제는
일어나지 않는다. 다만 로그가 아예 없는 경우(턴 0)에는 `session_summaries`가 빈 목록
`[]`이 되고, 최상위 `fallback_rate` 등도 안전하게 `0.0`을 반환한다.

`ts`를 파싱할 수 없는 레코드가 섞여 있어도 예외를 던지지 않는다. 파싱에 실패한 값은
정렬에서 가장 뒤로 밀리고, `first_ts`·`last_ts`에는 원본 문자열이 그대로 담긴다.

`render_markdown`은 `session_summaries` 상위 10개(최신순)를 "최근 세션" 표로 렌더링한다.
세션이 없으면 "기록 없음"이라고 표시한다.

### 특정 세션만 집계하기

`run_report(log_dir, out=None, session_id=None)`에 `session_id`를 넘기면 그 세션의
레코드만 걸러 집계한다. 기본값 `None`은 기존 동작(전체 집계)과 완전히 동일하다.

```python
from pathlib import Path
from fdt.eval.report import run_report

# 세션 하나만 보고 싶을 때
report = run_report(Path("log/turns"), session_id="3d36493c9ee94d45b5722b3c6bdbc9cc")
```

새 파일 구조에서는 `<session_id>`가 파일명에 그대로 들어가므로, 위처럼 특정 세션만
확인하려는 요청은 실제로는 파일 한두 개만 읽으면 되는 경우가 많다(단, `run_report`
자체는 로그 루트 전체를 스캔한 뒤 필터링한다. 파일 단위로 먼저 찾아 읽는 최적화는
웹 조회 API 쪽 책임이다).

## 사용법

JSON 보고서만 만들려면:

```powershell
PYTHONIOENCODING=utf-8 .venv/Scripts/python -m fdt.cli eval report --log-dir log/turns
# 저장 경로를 지정하려면 --out을 추가한다.
PYTHONIOENCODING=utf-8 .venv/Scripts/python -m fdt.cli eval report --log-dir log/turns --out data/out/eval/turn-report.json
```

파이썬에서 출력 경로를 지정할 때는 다음과 같다.

```python
from pathlib import Path
from fdt.eval.report import run_report

report = run_report(Path("log/turns"), Path("data/out/eval/turn-report.json"))
```

`render_markdown(report)`는 같은 집계를 표 중심 Markdown 문자열로 반환한다. JSON 파일
저장은 선택 사항이며 보고서 생성은 로그를 읽는 읽기 전용 작업이다.
