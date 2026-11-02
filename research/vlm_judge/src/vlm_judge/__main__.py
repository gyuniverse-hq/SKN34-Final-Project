from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from vlm_judge.images import discover, import_existing, lip_box, load_image
from vlm_judge.judge_adapter import GeminiJudge
from vlm_judge.pipeline import PROJECT, make_plan, run
from vlm_judge.report import generate_report

app = typer.Typer(no_args_is_help=True)
DEFAULT_DATA = PROJECT.parent / 'data' / 'vlm_judge'
CONFIG = PROJECT / 'judges.json'
ROOT_ENV = PROJECT.parents[1] / '.env'


def config() -> dict:
    return json.loads(CONFIG.read_text(encoding='utf-8'))


def check(data: Path):
    sets, errors = discover(data)
    for error in errors:
        typer.echo('ERROR ' + error, err=True)
    return sets, errors


@app.command()
def validate(data: Path = DEFAULT_DATA):
    """검사만 수행합니다. 네트워크를 사용하지 않습니다."""
    sets, errors = check(data)
    settings = config()
    model = Path(settings['landmarker_model']) if settings.get('landmarker_model') else None
    typer.echo('set | bare | real px | ar px | crop')
    for s in sets:
        real, ar = load_image(s.real), load_image(s.ar)
        _, crop = lip_box(load_image(s.bare) if s.bare else real, model)
        typer.echo(f'{s.id} | {bool(s.bare)} | {real.size} | {ar.size} | {crop}')
    typer.echo(f'valid={len(sets)} errors={len(errors)}')
    if errors or not sets:
        raise typer.Exit(1)


@app.command('import-existing')
def import_command(src: Annotated[Path, typer.Option(exists=True, file_okay=False)], data: Path = DEFAULT_DATA):
    count = import_existing(src.resolve(), data.resolve())
    typer.echo(f'Copied {count} explicitly named sets. Existing source files unchanged.')


@app.command()
def plan(data: Path = DEFAULT_DATA, seed: int = 42):
    sets, errors = check(data)
    tasks = make_plan(sets, config(), {'color', 'placement', 'texture', 'naturalness'}, seed)
    typer.echo(f'sets={len(sets)} calls={len(tasks)}; 예상 비용: 알 수 없음 (토큰 수 사전 미측정)')
    if errors or not sets:
        raise typer.Exit(1)


@app.command('run')
def run_command(data: Path = DEFAULT_DATA, sets: str = '', only: str = 'color,placement,texture,naturalness', seed: int = 42, no_cache: bool = False):
    data = data.resolve()
    selected, errors = check(data)
    if errors:
        raise typer.BadParameter('Fix invalid sets before run')
    if sets:
        wanted = set(sets.split(','))
        missing = wanted - {s.id for s in selected}
        if missing:
            raise typer.BadParameter('Unknown set IDs: ' + ', '.join(sorted(missing)))
        selected = [s for s in selected if s.id in wanted]
    selected_only = set(only.split(','))
    if not selected or not selected_only or selected_only - {'color', 'placement', 'texture', 'naturalness'}:
        raise typer.BadParameter('No valid sets or unknown --only value')
    cfg = config()
    client = GeminiJudge(cfg, ROOT_ENV)

    async def execute():
        await client.verify_model()
        return await run(data, selected, cfg, client, selected_only, seed, no_cache)

    try:
        typer.echo(str(asyncio.run(execute())))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None


@app.command()
def report(run: Annotated[Path, typer.Option(exists=True, file_okay=False)]):
    generate_report(run)
    typer.echo(str(run / 'report.md'))


if __name__ == '__main__':
    app()
