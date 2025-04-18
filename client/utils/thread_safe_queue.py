#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Implementazione di una coda thread-safe per lo scambio di dati tra thread.
"""

import queue
import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


class ThreadSafeQueue:
    """
    Coda thread-safe per lo scambio di dati tra thread.
    Implementa una coda FIFO con la possibilità di specificare una dimensione massima.
    """

    def __init__(self, maxsize: int = 10):
        """
        Inizializza una nuova coda thread-safe.

        Args:
            maxsize: Dimensione massima della coda. Se 0, la coda è illimitata.
        """
        self._queue = queue.Queue(maxsize)

    def put(self, item: Any, block: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Inserisce un elemento nella coda.

        Args:
            item: Elemento da inserire nella coda
            block: Se True, blocca fino a quando non c'è spazio disponibile
            timeout: Timeout massimo per l'inserimento (in secondi)

        Returns:
            True se l'inserimento è riuscito, False in caso di timeout
        """
        try:
            self._queue.put(item, block=block, timeout=timeout)
            return True
        except queue.Full:
            # La coda è piena e si è verificato un timeout
            logger.debug("Coda piena, elemento scartato")
            return False

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Any:
        """
        Recupera un elemento dalla coda.

        Args:
            block: Se True, blocca fino a quando non c'è un elemento disponibile
            timeout: Timeout massimo per il recupero (in secondi)

        Returns:
            L'elemento recuperato, o None in caso di timeout
        """
        try:
            return self._queue.get(block=block, timeout=timeout)
        except queue.Empty:
            # La coda è vuota e si è verificato un timeout
            return None

    def empty(self) -> bool:
        """
        Verifica se la coda è vuota.

        Returns:
            True se la coda è vuota, False altrimenti
        """
        return self._queue.empty()

    def full(self) -> bool:
        """
        Verifica se la coda è piena.

        Returns:
            True se la coda è piena, False altrimenti
        """
        return self._queue.full()

    def qsize(self) -> int:
        """
        Restituisce il numero di elementi nella coda.

        Returns:
            Numero di elementi nella coda
        """
        return self._queue.qsize()

    def clear(self) -> None:
        """
        Svuota la coda.
        """
        try:
            while not self._queue.empty():
                self._queue.get_nowait()
        except queue.Empty:
            pass