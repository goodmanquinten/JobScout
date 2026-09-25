"""Settings from .env, and the candidate profile + company watchlist from watchlist.toml."""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""
    anthropic_model: str = "claude-sonnet-5"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    gmail_credentials_path: Path = Path("credentials.json")
    gmail_token_path: Path = Path("token.json")
    handshake_enabled: bool = True
    handshake_sender: str = "joinhandshake.com"
    db_path: Path = Path("jobscout.db")
    watchlist_path: Path = Path("watchlist.toml")
    resume_path: Path = Path("profile/resume.md")


class Profile(BaseModel):
    available_from: date
    country: str = "US"
    max_years_required: int = 2
    targets: list[str] = Field(default_factory=list)
    summary: str = ""


class Company(BaseModel):
    name: str
    ats: Literal["greenhouse", "lever", "ashby"]
    token: str
    allow_non_us: bool = False
    # For big employers: only titles containing one of these (case-insensitive) are kept.
    title_include: list[str] = Field(default_factory=list)


class Watchlist(BaseModel):
    profile: Profile
    company: list[Company] = Field(default_factory=list)


def load_watchlist(path: Path) -> Watchlist:
    with path.open("rb") as f:
        return Watchlist.model_validate(tomllib.load(f))
