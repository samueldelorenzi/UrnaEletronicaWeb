"""Configuração da urna. Segredos vêm do ambiente ou são gerados uma vez e guardados em data/.secrets."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("URNA_DB", str(BASE_DIR / "data" / "urna.db")))
BACKUP_DIR = Path(os.getenv("URNA_BACKUP_DIR", str(BASE_DIR / "data" / "backups")))
REPLICA_DIR = Path(os.getenv("URNA_REPLICA_DIR", str(BASE_DIR / "data" / "replica")))
SECRETS_DIR = DB_PATH.parent / ".secrets"

COOKIE_SECURE = os.getenv("URNA_COOKIE_SECURE", "0") == "1"
RATE_LIMIT_ATIVO = os.getenv("URNA_RATE_LIMIT", "1") == "1"
SESSAO_MINUTOS = int(os.getenv("URNA_SESSAO_MINUTOS", "20"))
MAX_FALHAS_LOGIN = 5
BLOQUEIO_SEGUNDOS = 15 * 60


def _segredo(nome: str) -> str:
    valor = os.getenv(nome)
    if valor:
        return valor
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    arquivo = SECRETS_DIR / nome.lower()
    if not arquivo.exists():
        arquivo.write_text(secrets.token_hex(32), encoding="utf-8")
    return arquivo.read_text(encoding="utf-8").strip()


SECRET_KEY = _segredo("URNA_SECRET_KEY")
CPF_PEPPER = _segredo("URNA_CPF_PEPPER")
VOTO_CHAVE = _segredo("URNA_VOTO_CHAVE")

# Votos ficam cifrados e pendentes até juntar este número de votos; então saem embaralhados, todos de uma vez.
LOTE_MINIMO = int(os.getenv("URNA_LOTE_MIN", "5"))

# CPFs (separados por vírgula) que recebem os perfis ao fazer login.
AUDITOR_CPFS = [c.strip() for c in os.getenv("URNA_AUDITOR_CPFS", "").split(",") if c.strip()]
ADMIN_CPFS = [c.strip() for c in os.getenv("URNA_ADMIN_CPFS", "").split(",") if c.strip()]
