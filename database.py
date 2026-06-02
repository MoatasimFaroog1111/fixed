from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///guardian.db"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


class TradeLog(Base):
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50))
    side = Column(String(10))
    quantity = Column(Float)
    price = Column(Float)
    status = Column(String(50))
    bot_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


class BotStatus(Base):
    __tablename__ = "bot_status"

    id = Column(Integer, primary_key=True, index=True)
    bot_name = Column(String(100))
    status = Column(String(50))
    message = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)
