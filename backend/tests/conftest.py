"""测试夹具：内存 SQLite。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.appsettings import init_settings


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    init_settings(session)
    yield session
    session.close()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    import app.main as main_mod
    from app.db import get_db

    main_mod.app.dependency_overrides[get_db] = lambda: db
    # 跳过 startup 种子（测试自备数据）
    with TestClient(main_mod.app, raise_server_exceptions=True) as c:
        yield c
    main_mod.app.dependency_overrides.clear()
