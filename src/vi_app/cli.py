# src/vi_app/cli.py
from __future__ import annotations

import typer

from vi_app.commands.cleanup import app as cleanup_app
from vi_app.commands.convert import app as convert_app
from vi_app.commands.dedup import app as dedup_app

app = typer.Typer(help="Venture Image CLI")

app.add_typer(cleanup_app, name="cleanup")
app.add_typer(convert_app, name="convert")
app.add_typer(dedup_app, name="dedup")


if __name__ == "__main__":
    app()
