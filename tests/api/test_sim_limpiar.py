"""Vaciar clientes desde la consola respeta las claves ajenas, como en PostgreSQL."""
from sqlalchemy import event, func, select

from airdrop.api.data import DataStore, clients, orders, users
from simtools import sim


def _con_claves_ajenas(engine):
    """SQLite no comprueba las claves ajenas salvo que se le pida."""
    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


def test_borrar_clientes_borra_sus_cuentas_y_pedidos(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'banco.db'}"
    store = DataStore(url)
    cliente = store.create_client("Cliente", "Castelldefels", 41.28, 1.98)
    cliente_id = cliente["id"] if isinstance(cliente, dict) else cliente
    store.create_user("cliente1", "hash", cliente_id)
    store.create_order(cliente_id, 1.2)

    banco = sim.Banco(url)
    engine = _con_claves_ajenas(banco.engine)
    monkeypatch.setattr(sim.Banco, "engine", property(lambda self: engine))

    resultado = sim.limpiar(banco, pedidos=False, clientes=True)

    assert resultado["borrados"]["clientes"] == 1
    with engine.connect() as conn:
        for tabla in (clients, users, orders):
            assert conn.execute(select(func.count()).select_from(tabla)).scalar_one() == 0
