"""El planificador recibe los pedidos pendientes por orden de llegada (el voraz es FIFO)."""
from airdrop.api.main import _OrdersStore


class _Almacen:
    def list_orders(self, client_id=None):
        # el panel los quiere de más reciente a más antiguo
        return [{"id": 9, "status": "pendiente"}, {"id": 7, "status": "entregado"},
                {"id": 4, "status": "pendiente"}, {"id": 1, "status": "pendiente"}]


def test_pending_orders_come_oldest_first():
    assert [o["id"] for o in _OrdersStore(_Almacen()).list_pending()] == [1, 4, 9]
