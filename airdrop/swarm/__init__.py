"""Orquestación del enjambre de drones de reparto.

Vacío a propósito. Es el punto de entrada del bloque B del TFG: modelo de
flota, planificación greedy en vivo, gestor de espacio aéreo (parkings, slots
de altitud, deconflicción por aproximación) y orquestador sobre N instancias
SITL.

El algoritmo de asignación no se implementa aquí: se reutiliza `core.greedy`,
el mismo que valida experimentalmente `research/`.
"""
