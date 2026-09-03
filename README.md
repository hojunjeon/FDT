# Finance-Digital-Twin (FDT)

KeyFin 개인 금융 디지털 트윈의 결정론적 원장·전이·예측 엔진과 로컬 코칭 대시보드입니다. 현재 데이터는 `data/seed/`의 DEMO 프로필이며 실제 이체·결제를 실행하지 않습니다.

## 실행

```powershell
.venv\Scripts\python -m pytest -q
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python -m fdt.cli state data/seed/A_steady
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python -m fdt.cli analyze data/seed/A_steady
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python -m fdt.cli serve
```

브라우저에서 `http://127.0.0.1:8787`을 엽니다. 프로필(금융 데이터)과 코치 페르소나는 별도로 선택하며, Ollama가 없으면 규칙 라우팅·템플릿 코칭으로 자동 전환합니다. 숫자 계산은 FDT 코어가 담당하고 LLM은 툴 선택과 설명만 담당합니다.

주요 명령은 `gen`, `ingest`, `state`, `forecast`, `whatif`, `risk`, `goal`, `analyze`, `brief`, `chat`, `serve`, `eval`입니다. 구현 기준은 [`docs/03_FDT_설계.md`](docs/03_FDT_설계.md)입니다.
