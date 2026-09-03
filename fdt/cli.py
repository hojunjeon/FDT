"""FDT 명령줄 도구."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

app = typer.Typer(help="KeyFin 개인 금융 디지털 트윈", no_args_is_help=True)
SEED_DIR = Path("data/seed")


@app.callback()
def _root() -> None:
    """서브커맨드 강제용 콜백."""


@app.command()
def gen(
    profile: str = typer.Argument("all", help="프로필 id (A_steady 등) 또는 all"),
    out: Path = typer.Option(SEED_DIR, help="출력 디렉터리"),
    seed: int | None = typer.Option(None, help="시드 덮어쓰기"),
    end: str | None = typer.Option(None, help="생성 종료일 YYYY-MM-DD"),
) -> None:
    """프로필로 금융망 형식 더미 데이터를 생성한다."""
    from fdt.data.generator import generate, list_profiles

    names = list_profiles() if profile == "all" else [profile]
    for n in names:
        d, summary = generate(n, out, seed=seed, end=date.fromisoformat(end) if end else None)
        typer.echo(f"[{n}] -> {d}")
        typer.echo(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    app()
