"""
Olay Güdümlü Olay Veriyolu (Event Bus).

Sistemin bileşenleri (Veri hatları, Strateji motorları, Risk ve İletim)
arasındaki asenkron/senkron olayları sırayla koordine eder.
"""

from collections import deque
from typing import Any, Callable, Dict, List


class EventBus:
    """
    Olay Dağıtım ve Yayın/Abone (Pub/Sub) Veriyolu.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Any], None]]] = {}
        self._event_queue: deque = deque()

    def subscribe(self, event_type: str, handler: Callable[[Any], None]) -> None:
        """Belirtilen olay türüne dinleyici kaydeder."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def publish(self, event_type: str, payload: Any) -> None:
        """Olayı kuyruğa ekler ve dinleyicileri tetikler."""
        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            handler(payload)
