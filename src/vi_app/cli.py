# src/vi_app/cli.py
import typer

from vi_app.modules.dedup.schemas import DedupRequest, DedupStrategy
from vi_app.modules.dedup.service import apply as dapply
from vi_app.modules.dedup.service import plan as dplan
from vi_app.modules.sort.schemas import SortRequest, SortStrategy
from vi_app.modules.sort.service import apply as sapply
from vi_app.modules.sort.service import plan as splan

app = typer.Typer()


@app.command()
def dedup(
    root: str, strategy: DedupStrategy = DedupStrategy.content, dry_run: bool = True
):
    req = DedupRequest(root=root, strategy=strategy, dry_run=dry_run)
    result = dplan(req) if dry_run else dapply(req)
    typer.echo(f"clusters={len(result)} strategy={strategy}")


@app.command()
def sort(
    src_root: str, strategy: SortStrategy = SortStrategy.date, dry_run: bool = True
):
    req = SortRequest(src_root=src_root, strategy=strategy, dry_run=dry_run)
    moves = splan(req) if dry_run else sapply(req)
    typer.echo(f"moves={len(moves)} strategy={strategy}")


if __name__ == "__main__":
    app()
