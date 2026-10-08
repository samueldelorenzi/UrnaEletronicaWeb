"""Liberação dos votos em lote: quebra a ligação entre o momento em que o eleitor votou e o momento em que o voto aparece."""
import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit, security
from .models import Voto, VotoPendente


def contar_pendentes(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(VotoPendente)) or 0


def liberar(db: Session, minimo: int, forcar: bool = False) -> int:
    """Move os votos pendentes para `votos`, embaralhados e com ids novos. Retorna quantos foram liberados.

    Sem `forcar`, só libera quando há pelo menos `minimo` votos pendentes. Deve rodar na transação do chamador.
    """
    pendentes = db.scalars(select(VotoPendente)).all()
    if not pendentes or (not forcar and len(pendentes) < minimo):
        return 0
    votos = [security.decifrar_voto(p.conteudo) for p in pendentes]
    secrets.SystemRandom().shuffle(votos)
    for v in votos:
        db.add(Voto(id=str(uuid.uuid4()), tipo=v["tipo"], candidato_id=v["candidato_id"], voto_hash=v["voto_hash"]))
    for p in pendentes:
        db.delete(p)
    audit.registrar(db, "lote_liberado", detalhe=f"{len(votos)} votos")
    return len(votos)


def hash_pendente(db: Session, voto_hash: str) -> bool:
    """Informa se um comprovante pertence a um voto que ainda aguarda o lote."""
    return any(security.decifrar_voto(p.conteudo)["voto_hash"] == voto_hash
               for p in db.scalars(select(VotoPendente)))
