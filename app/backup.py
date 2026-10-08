"""Redundância (SQLite): backup consistente, réplica em outro diretório/disco, verificação e restauração.

Uso:  python -m app.backup backup | replicar [--intervalo 30] | verificar ARQUIVO | restaurar ARQUIVO
"""
import argparse
import hashlib
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _cadeia_ok(caminho: Path) -> bool:
    """Reexecuta a verificação da cadeia de auditoria diretamente no arquivo."""
    from .audit import GENESIS, _calcular
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        anterior = GENESIS
        for _id, ts, evento, ator, detalhe, h_ant, h in con.execute(
                "SELECT id, ts, evento, ator, detalhe, hash_anterior, hash FROM audit_log ORDER BY id"):
            if h_ant != anterior or h != _calcular(anterior, ts, evento, ator, detalhe):
                return False
            anterior = h
        return True
    finally:
        con.close()


def verificar(caminho: Path) -> dict:
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        integridade = con.execute("PRAGMA integrity_check").fetchone()[0]
        votos = con.execute("SELECT COUNT(*) FROM votos").fetchone()[0]
        comp = con.execute("SELECT COUNT(*) FROM comparecimento").fetchone()[0]
    finally:
        con.close()
    return {"sqlite_integro": integridade == "ok", "cadeia_auditoria_integra": _cadeia_ok(caminho),
            "votos": votos, "comparecimentos": comp, "consistente": votos == comp}


def fazer_backup(destino_dir: Path | None = None) -> dict:
    destino_dir = destino_dir or config.BACKUP_DIR
    destino_dir.mkdir(parents=True, exist_ok=True)
    arquivo = destino_dir / f"urna-{datetime.now():%Y%m%d-%H%M%S}.db"
    origem = sqlite3.connect(config.DB_PATH)
    copia = sqlite3.connect(arquivo)
    try:
        origem.backup(copia)  # API de backup online do SQLite: cópia consistente com o banco em uso
    finally:
        copia.close()
        origem.close()
    resultado = verificar(arquivo)
    sha = _sha256(arquivo)
    Path(str(arquivo) + ".sha256").write_text(sha, encoding="utf-8")
    return {"arquivo": str(arquivo), "sha256": sha, **resultado}


def restaurar(arquivo: Path) -> None:
    arquivo = Path(arquivo)
    esperado = Path(str(arquivo) + ".sha256")
    if esperado.exists() and esperado.read_text(encoding="utf-8").strip() != _sha256(arquivo):
        raise SystemExit("Backup corrompido: SHA-256 não confere.")
    v = verificar(arquivo)
    if not (v["sqlite_integro"] and v["cadeia_auditoria_integra"]):
        raise SystemExit(f"Backup inválido: {v}")
    if config.DB_PATH.exists():
        shutil.copy2(config.DB_PATH, str(config.DB_PATH) + ".antes-restauracao")
    for sufixo in ("-wal", "-shm"):
        Path(str(config.DB_PATH) + sufixo).unlink(missing_ok=True)
    shutil.copy2(arquivo, config.DB_PATH)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.backup")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup")
    r = sub.add_parser("replicar")
    r.add_argument("--intervalo", type=int, default=30)
    sub.add_parser("verificar").add_argument("arquivo")
    sub.add_parser("restaurar").add_argument("arquivo")
    a = p.parse_args(argv)
    if a.cmd == "backup":
        print(fazer_backup())
    elif a.cmd == "replicar":
        while True:  # réplica contínua (aponte URNA_REPLICA_DIR para outro disco/servidor)
            print(fazer_backup(config.REPLICA_DIR), flush=True)
            time.sleep(a.intervalo)
    elif a.cmd == "verificar":
        print(verificar(Path(a.arquivo)))
    else:
        restaurar(Path(a.arquivo))
        print("Restauração concluída.")


if __name__ == "__main__":
    main(sys.argv[1:])
