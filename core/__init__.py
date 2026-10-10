"""Núcleo algorítmico de asignación dron↔pedido.

Modelo de energía, función de costes y los dos asignadores: el voraz
(`greedy`), que es el que ejecuta el enjambre en producción, y el global por
matriz de costes (`cost_matrix`), contra el que se compara experimentalmente.

Este paquete no importa de ninguna otra zona del proyecto. Tanto el producto
(`airdrop`) como la investigación (`research`) dependen de él, nunca al revés.
"""
