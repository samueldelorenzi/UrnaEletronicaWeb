import os
import random
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="urna-teste-")
os.environ["URNA_DB"] = str(Path(_TMP) / "urna.db")
os.environ["URNA_BACKUP_DIR"] = str(Path(_TMP) / "backups")
os.environ["URNA_RATE_LIMIT"] = "0"


def gerar_cpf() -> str:
    n = [random.randint(0, 9) for _ in range(9)]
    for tam in (9, 10):
        soma = sum(n[i] * (tam + 1 - i) for i in range(tam))
        n.append((soma * 10 % 11) % 10)
    cpf = "".join(map(str, n))
    return gerar_cpf() if cpf == cpf[0] * 11 else cpf


AUDITOR_CPF = gerar_cpf()
ADMIN_CPF = gerar_cpf()
os.environ["URNA_AUDITOR_CPFS"] = AUDITOR_CPF
os.environ["URNA_ADMIN_CPFS"] = ADMIN_CPF

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SENHA = "Senha#Forte123"


@pytest.fixture(scope="session", autouse=True)
def _app_iniciado():
    with TestClient(app):
        yield


def novo_cliente() -> TestClient:
    return TestClient(app)


def cadastrar_e_entrar(cpf: str | None = None, senha: str = SENHA) -> tuple[TestClient, str]:
    cpf = cpf or gerar_cpf()
    c = novo_cliente()
    assert c.post("/api/cadastro", json={"cpf": cpf, "senha": senha}).status_code == 201
    assert c.post("/api/login", json={"cpf": cpf, "senha": senha}).status_code == 200
    return c, cpf


def csrf(c: TestClient) -> dict:
    return {"X-CSRF-Token": c.cookies.get("urna_csrf")}


@pytest.fixture
def eleitor():
    return cadastrar_e_entrar()[0]
