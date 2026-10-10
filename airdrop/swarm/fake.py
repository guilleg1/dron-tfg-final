"""Autopiloto de mentira para los tests.

Implementa la misma interfaz que ``MavlinkDroneLink`` pero vuela al instante:
``goto`` teletransporta y anota el waypoint, ``arm_and_takeoff`` y ``land``
cambian la altitud. Permite probar el ejecutor, el planificador y el servicio
sin levantar SITL, que es lo que hace que este subsistema tenga tests de
verdad y no solo una lista de comprobación manual.
"""

from __future__ import annotations

import threading


class FakeDroneLink:
    def __init__(self, drone_id, home_lat, home_lon, connection="fake://",
                 fail_on_connect=False, fail_on_goto=False, steps_per_leg=1,
                 stale_telemetry_s=0.0, speed_mps=None, step_s=0.5):
        self.drone_id = drone_id
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.connection = connection
        self.fail_on_connect = fail_on_connect
        self.fail_on_goto = fail_on_goto
        # Edad simulada de la telemetría, para probar la pérdida de enlace.
        self.stale_telemetry_s = stale_telemetry_s

        self._connected = False
        self._lock = threading.Lock()
        self._lat = home_lat
        self._lon = home_lon
        self._alt = 0.0

        # steps_per_leg=1 reproduce el vuelo instantáneo original, de modo que
        # los tests que no prueban deconflicción no notan el cambio.
        self.steps_per_leg = max(1, int(steps_per_leg))
        # Con speed_mps, cada tramo dura lo que tardaría a esa velocidad: el
        # número de pasos sale de la distancia y del periodo de control del
        # ejecutor (step_s). Es el modo de demostración del portal desplegado.
        self.speed_mps = speed_mps
        self.step_s = step_s
        self._target = None
        self._origin = None
        self._step = 0
        self._holding = False

        # Registro para las aserciones de los tests.
        self.visited: list[tuple[float, float, float]] = []
        self.aborted: str | None = None
        self.takeoffs: list[float] = []
        self.landings = 0
        self.held_times = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self.fail_on_connect:
            raise ConnectionError(f"{self.drone_id}: no se pudo conectar")
        self._connected = True

    def telemetry(self) -> dict:
        with self._lock:
            return {
                "lat": self._lat, "lon": self._lon, "alt": self._alt,
                "heading": 0.0, "groundSpeed": 0.0,
                "state": "flying" if self._alt > 0.5 else "connected",
            }

    def arm_and_takeoff(self, alt: float) -> None:
        self._require()
        with self._lock:
            self._alt = float(alt)
        self.takeoffs.append(float(alt))

    def goto(self, lat: float, lon: float, alt: float) -> None:
        """Ordena el desplazamiento y vuelve, como el enlace real."""
        self._require()
        if self.fail_on_goto:
            raise RuntimeError(f"{self.drone_id}: goto rechazado")
        with self._lock:
            self._origin = (self._lat, self._lon, self._alt)
            self._target = (float(lat), float(lon), float(alt))
            self._step = 0
            if self.speed_mps:
                from core.geo import haversine_km  # noqa: PLC0415
                metros = haversine_km(self._origin[0], self._origin[1],
                                      self._target[0], self._target[1]) * 1000.0
                metros = max(metros, abs(self._target[2] - self._origin[2]))
                self.steps_per_leg = max(2, int(round(
                    metros / (self.speed_mps * self.step_s))))
        self.visited.append((float(lat), float(lon), float(alt)))

    def has_arrived(self, lat: float, lon: float, tol_m: float) -> bool:
        """Avanza un paso hacia el destino y dice si ya llegó.

        Avanzar aquí, y no en un hilo, mantiene los tests deterministas: el
        dron se mueve exactamente cuando el ejecutor comprueba.
        """
        self._require()
        with self._lock:
            if self._holding or self._target is None:
                return False
            self._step += 1
            fraccion = min(1.0, self._step / self.steps_per_leg)
            ox, oy, oz = self._origin
            tx, ty, tz = self._target
            self._lat = ox + (tx - ox) * fraccion
            self._lon = oy + (ty - oy) * fraccion
            self._alt = oz + (tz - oz) * fraccion
            return fraccion >= 1.0

    def telemetry_age_s(self):
        """Edad de la telemetría. Los tests la fuerzan para simular enlace caído."""
        return self.stale_telemetry_s

    def hold(self) -> None:
        self._holding = True
        self.held_times += 1

    def resume(self) -> None:
        self._holding = False

    def land(self) -> None:
        self._require()
        with self._lock:
            self._alt = 0.0
        self.landings += 1

    def abort(self, mode: str = "RTL") -> None:
        self.aborted = mode
        if mode == "RTL":
            with self._lock:
                self._lat, self._lon, self._alt = self.home_lat, self.home_lon, 0.0

    def close(self) -> None:
        self._connected = False

    def _require(self) -> None:
        if not self._connected:
            raise RuntimeError(f"{self.drone_id}: no conectado")
