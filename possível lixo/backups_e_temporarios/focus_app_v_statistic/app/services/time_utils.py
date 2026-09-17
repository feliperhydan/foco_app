"""
Utilitário mínimo de tempo.

`utcnow_naive` existe como um único ponto de verdade para "agora" sem
timezone, usado como default em todos os campos DateTime do modelo —
trocar a implementação aqui (ex.: para um relógio mockável em teste)
nunca exige tocar em app/models.py.
"""
from datetime import datetime


def utcnow_naive() -> datetime:
    return datetime.utcnow()
