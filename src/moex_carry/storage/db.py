from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from moex_carry.config import AppSettings
from moex_carry.storage.models import Base


def create_engine_from_settings(settings: AppSettings):
    return create_engine(settings.database.url, echo=settings.database.echo, future=True)


def create_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
