"""Polecenia `flask …` do administracji instancją."""
import os

import click
from flask import current_app

from .extensions import db
from .models import Admin
from .security import hash_password


def register_cli(app) -> None:
    @app.cli.command("create-admin")
    @click.option("--username", default=lambda: os.environ.get("ADMIN_USERNAME", "admin"), show_default="admin")
    @click.option("--password", default=lambda: os.environ.get("ADMIN_PASSWORD"),
                  help="Domyślnie z ADMIN_PASSWORD; gdy brak – pytanie interaktywne.")
    @click.option("--if-missing", is_flag=True, help="Nie zmieniaj hasła, jeśli konto już istnieje.")
    def create_admin(username, password, if_missing):
        """Tworzy konto administratora albo ustawia mu nowe hasło."""
        admin = Admin.query.filter_by(username=username).first()
        if admin and if_missing:
            click.echo(f"Administrator „{username}” już istnieje – bez zmian.")
            return
        if not password:
            password = click.prompt("Hasło", hide_input=True, confirmation_prompt=True)
        if len(password) < 8:
            raise click.ClickException("Hasło musi mieć co najmniej 8 znaków.")
        if admin:
            admin.password_hash = hash_password(password)
            click.echo(f"Zmieniono hasło administratora „{username}”.")
        else:
            db.session.add(Admin(username=username, password_hash=hash_password(password)))
            click.echo(f"Utworzono administratora „{username}”.")
        db.session.commit()

    @app.cli.command("init-influx")
    def init_influx():
        """Tworzy bazę w InfluxDB (jeśli nie istnieje) i sprawdza połączenie."""
        store = current_app.extensions["measurement_store"]
        store.init()
        if not store.ping():
            raise click.ClickException("Brak połączenia z magazynem wyników (InfluxDB).")
        click.echo("Magazyn wyników gotowy.")
