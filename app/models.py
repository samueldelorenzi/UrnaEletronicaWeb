from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Eleitor(Base):
    __tablename__ = "eleitores"
    id: Mapped[int] = mapped_column(primary_key=True)
    cpf_hmac: Mapped[str] = mapped_column(String(64), unique=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    criado_em: Mapped[str] = mapped_column(String(32))


class Candidato(Base):
    __tablename__ = "candidatos"
    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[int] = mapped_column(unique=True)
    nome: Mapped[str] = mapped_column(String(100))
    partido: Mapped[str] = mapped_column(String(30))


class Comparecimento(Base):
    # guarda só quem votou pra não votar duas vezes
    # a data foi tirada pq dava pra ligar o voto ao eleitor pelo horario
    __tablename__ = "comparecimento"
    eleitor_id: Mapped[int] = mapped_column(ForeignKey("eleitores.id"), primary_key=True)
    data: Mapped[str] = mapped_column(String(10))


class Voto(Base):
    # tabela de votos (anônimo, sem relação com eleitor)
    __tablename__ = "votos"
    __table_args__ = (
        CheckConstraint("tipo IN ('candidato','branco','nulo')", name="ck_voto_tipo"),
        CheckConstraint("(tipo = 'candidato') = (candidato_id IS NOT NULL)", name="ck_voto_candidato"),
        {"sqlite_with_rowid": False}, # desabilita rowid pra não dar pra saber a ordem de inserção
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(10))
    candidato_id: Mapped[Optional[int]] = mapped_column(ForeignKey("candidatos.id"), nullable=True)
    voto_hash: Mapped[str] = mapped_column(String(64), unique=True)


class VotoPendente(Base):
    # fica criptografado aqui até o lote encher
    __tablename__ = "votos_pendentes"
    id: Mapped[int] = mapped_column(primary_key=True)
    conteudo: Mapped[str] = mapped_column(String(500))


class AuditLog(Base):
    # tabela do log em cadeia (blockchain style)
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[str] = mapped_column(String(32))
    evento: Mapped[str] = mapped_column(String(50))
    ator: Mapped[str] = mapped_column(String(64))
    detalhe: Mapped[str] = mapped_column(String(300))
    hash_anterior: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class TentativaLogin(Base):
    __tablename__ = "tentativas_login"
    chave: Mapped[str] = mapped_column(String(64), primary_key=True)
    falhas: Mapped[int] = mapped_column(default=0)
    bloqueado_ate: Mapped[float] = mapped_column(default=0.0)
