# FDT 운영 지표

턴 로거가 남긴 JSONL을 집계해 에이전트 운영 상태를 확인하는 보고서다. 보고서 생성기는
`fdt.eval.report.run_report`이며, 금융 원장이나 트윈 계산에는 관여하지 않는다.

## 입력 로그

기본 경로는 `log/turns/YYYY-MM-DD.jsonl`이고 `FDT_TURN_LOG_DIR` 환경변수로 바꿀 수 있다.
`run_report`는 지정한 디렉터리 아래의 모든 `*.jsonl` 파일을 읽는다. 한 줄은 한 대화 턴이며
UTF-8과 `ensure_ascii=False`를 사용한다.

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
