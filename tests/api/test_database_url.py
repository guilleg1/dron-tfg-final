from airdrop.api.data import _normalize_url


def test_postgres_urls_use_psycopg2():
    # Railway y otros proveedores sirven postgres:// o postgresql:// sin driver;
    # SQLAlchemy 2.1 elegiría psycopg 3, que no se instala.
    assert _normalize_url("postgres://u:p@h:5432/db") == "postgresql+psycopg2://u:p@h:5432/db"
    assert _normalize_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg2://u:p@h:5432/db"


def test_other_urls_are_left_alone():
    assert _normalize_url("sqlite:///x.db") == "sqlite:///x.db"
    assert _normalize_url("postgresql+psycopg2://h/db") == "postgresql+psycopg2://h/db"
