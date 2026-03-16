"""Thin CLI wrapper around the pydoglog library.

Install with: pip install pydoglog[cli]
"""

from __future__ import annotations

import json
import sys

try:
    import click
except ImportError:
    print("Error: click is required for the CLI.  Install with: pip install pydoglog[cli]")
    sys.exit(1)

from pydoglog import DogLogClient, DogLogAuthError, DogLogAPIError, EventType
from pydoglog.auth import login_email_password, signup_email_password, run_oauth_flow, save_config


@click.group()
@click.option("--config", "config_path", default=None, help="Path to config JSON file.")
@click.pass_context
def cli(ctx, config_path):
    """DogLog CLI - interact with the DogLog pet tracking service."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


def _client(ctx) -> DogLogClient:
    return DogLogClient(config_path=ctx.obj.get("config_path"))


# ── Auth commands ──


@cli.command()
@click.option("--email", required=True, prompt=True)
@click.option("--password", required=True, prompt=True, hide_input=True)
@click.pass_context
def login(ctx, email, password):
    """Login with email and password."""
    try:
        creds = login_email_password(email, password)
        save_config(creds, ctx.obj.get("config_path"))
        click.echo(f"Logged in as {creds['email']} (uid: {creds['uid']})")
    except DogLogAuthError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@cli.command()
@click.option("--email", required=True, prompt=True)
@click.option("--password", required=True, prompt=True, hide_input=True)
@click.pass_context
def signup(ctx, email, password):
    """Create a new account with email and password."""
    try:
        creds = signup_email_password(email, password)
        save_config(creds, ctx.obj.get("config_path"))
        click.echo(f"Account created: {creds['email']} (uid: {creds['uid']})")
    except DogLogAuthError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@cli.command("login-google")
@click.pass_context
def login_google(ctx):
    """Login via Google Sign-In (opens browser)."""
    try:
        creds = run_oauth_flow(config_path=ctx.obj.get("config_path"))
        click.echo(f"Logged in as {creds['email']} (uid: {creds['uid']})")
    except DogLogAuthError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@cli.command()
@click.pass_context
def logout(ctx):
    """Clear saved credentials."""
    from pathlib import Path
    from pydoglog.auth import DEFAULT_CONFIG_PATH
    path = Path(ctx.obj.get("config_path") or DEFAULT_CONFIG_PATH)
    if path.exists():
        path.unlink()
    click.echo("Logged out.")


# ── Info commands ──


@cli.command()
@click.pass_context
def whoami(ctx):
    """Show current user info."""
    try:
        client = _client(ctx)
        client.ensure_token()
        click.echo(f"UID:   {client.uid}")
        click.echo(f"Email: {client.email}")
        data = client.get_user_data()
        click.echo(f"Name:  {data.get('name', 'N/A')}")
        click.echo(f"Premium: {data.get('premium', False)}")
    except (DogLogAuthError, DogLogAPIError) as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@cli.command()
@click.pass_context
def packs(ctx):
    """List your packs."""
    try:
        client = _client(ctx)
        for pack in client.get_packs():
            click.echo(f"  [{pack.id}] {pack.name} (owner: {pack.owner})")
    except (DogLogAuthError, DogLogAPIError) as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@cli.command()
@click.option("--pack", "pack_id", default=None, help="Filter by pack ID.")
@click.pass_context
def pets(ctx, pack_id):
    """List pets (dogs)."""
    try:
        client = _client(ctx)
        for dog in client.get_dogs(pack_id):
            free_str = " [free]" if dog.free else ""
            click.echo(f"  [{dog.id}] {dog.name}{free_str} (pack: {dog.pack_id})")
    except (DogLogAuthError, DogLogAPIError) as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


# ── Event commands ──


@cli.command()
@click.argument("pack_id")
@click.option("--pet", "pet_id", default=None, help="Filter by pet ID.")
@click.option("--type", "event_type", default=None,
              type=click.Choice([e.name.lower() for e in EventType], case_sensitive=False),
              help="Filter by event type.")
@click.option("--limit", default=20, show_default=True, help="Max events to show.")
@click.pass_context
def events(ctx, pack_id, pet_id, event_type, limit):
    """List events for a pack."""
    try:
        client = _client(ctx)
        et = EventType.from_name(event_type) if event_type else None
        for ev in client.list_events(pack_id, pet_id, limit, et):
            date_str = ev.timestamp.strftime("%Y-%m-%d %H:%M")
            note_str = f' "{ev.note}"' if ev.note else ""
            click.echo(f"  [{date_str}] {ev.event_type.name:<15} {ev.pet_name:<12} by {ev.created_by_name}{note_str}")
    except (DogLogAuthError, DogLogAPIError, ValueError) as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@cli.command("log")
@click.argument("pack_id")
@click.argument("pet_id")
@click.argument("event_type", type=click.Choice([e.name.lower() for e in EventType], case_sensitive=False))
@click.option("--comment", default="", help="Optional note.")
@click.option("--pet-name", default="", help="Display name for the pet.")
@click.option("--weight-kg", type=float, default=None)
@click.option("--weight-lb", type=float, default=None)
@click.option("--temp-c", type=float, default=None)
@click.option("--temp-f", type=float, default=None)
@click.option("--vaccine", default=None)
@click.option("--glucose", type=float, default=None)
@click.option("--glucose-unit", type=click.Choice(["mg/dL", "mmol/L"]), default=None)
@click.pass_context
def log_event(ctx, pack_id, pet_id, event_type, comment, pet_name,
              weight_kg, weight_lb, temp_c, temp_f, vaccine, glucose, glucose_unit):
    """Log a new event."""
    try:
        client = _client(ctx)
        extra = {}
        if weight_kg is not None:
            extra["weightKg"] = weight_kg
            extra["weightMeasure"] = "Kilograms"
        if weight_lb is not None:
            extra["weightPound"] = weight_lb
            extra["weightMeasure"] = "Pounds"
        if temp_c is not None:
            extra["temperatureCelsius"] = temp_c
            extra["temperatureMeasure"] = "Celsius"
        if temp_f is not None:
            extra["temperatureFahrenheit"] = temp_f
            extra["temperatureMeasure"] = "Fahrenheit"
        if vaccine is not None:
            extra["vaccine"] = vaccine
        if glucose is not None:
            extra["glucose"] = glucose
            extra["glucoseUnit"] = glucose_unit or "mg/dL"

        eid = client.create_event(pack_id, pet_id, event_type, note=comment,
                                   dog_name=pet_name, **extra)
        click.echo(f"Event logged: {event_type.upper()} for {pet_name or pet_id} (id: {eid})")
    except (DogLogAuthError, DogLogAPIError, ValueError) as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


def main():
    cli()


if __name__ == "__main__":
    main()
