import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog

GENESIS = "0" * 64


def _calcular(anterior: str, ts: str, evento: str, ator: str, detalhe: str) -> str:
    return hashlib.sha256("|".join([anterior, ts, evento, ator, detalhe]).encode("utf-8")).hexdigest()


def registrar(db: Session, evento: str, ator: str = "-", detalhe: str = "") -> None:
    """Acrescenta uma linha à cadeia. Deve rodar na mesma transação (BEGIN IMMEDIATE serializa)."""
    ultimo = db.scalar(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)) or GENESIS
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.add(AuditLog(
        ts=ts, evento=evento, ator=ator, detalhe=detalhe[:300],
        hash_anterior=ultimo, hash=_calcular(ultimo, ts, evento, ator, detalhe[:300]),
    ))


def verificar_cadeia(db: Session) -> dict:
    anterior = GENESIS
    total = 0
    for linha in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        esperado = _calcular(anterior, linha.ts, linha.evento, linha.ator, linha.detalhe)
        if linha.hash_anterior != anterior or linha.hash != esperado:
            return {"integra": False, "total": total, "primeira_linha_invalida": linha.id}
        anterior = linha.hash
        total += 1
    return {"integra": True, "total": total, "primeira_linha_invalida": None}
