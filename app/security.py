import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request

from . import config

COOKIE_SESSAO = "urna_sessao"
COOKIE_CSRF = "urna_csrf"
_ph = PasswordHasher()
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(config.VOTO_CHAVE.encode()).digest()))
# Hash fixo para igualar o tempo de resposta quando o CPF não existe (evita enumeração por tempo).
_HASH_FALSO = _ph.hash("senha-falsa-para-igualar-tempo")


def normalizar_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", cpf or "")


def validar_cpf(cpf: str) -> bool:
    cpf = normalizar_cpf(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for tam in (9, 10):
        soma = sum(int(cpf[i]) * (tam + 1 - i) for i in range(tam))
        digito = (soma * 10 % 11) % 10
        if digito != int(cpf[tam]):
            return False
    return True


def hash_cpf(cpf: str) -> str:
    return hmac.new(config.CPF_PEPPER.encode(), normalizar_cpf(cpf).encode(), hashlib.sha256).hexdigest()


def ator_id(eleitor_id: int) -> str:
    return hmac.new(config.CPF_PEPPER.encode(), f"eleitor:{eleitor_id}".encode(), hashlib.sha256).hexdigest()[:16]


def cifrar_voto(voto: dict) -> str:
    return _fernet.encrypt(json.dumps(voto, sort_keys=True).encode()).decode()


def decifrar_voto(conteudo: str) -> dict:
    return json.loads(_fernet.decrypt(conteudo.encode()))


def validar_senha(senha: str, cpf: str) -> str | None:
    """Retorna a mensagem de erro, ou None se a senha é aceitável."""
    if len(senha) < 10:
        return "A senha deve ter pelo menos 10 caracteres."
    if not (re.search(r"[a-z]", senha) and re.search(r"[A-Z]", senha) and re.search(r"\d", senha)
            and re.search(r"[^\w\s]", senha)):
        return "A senha deve ter maiúscula, minúscula, número e símbolo."
    if normalizar_cpf(cpf) in re.sub(r"\D", "", senha):
        return "A senha não pode conter o CPF."
    return None


def hash_senha(senha: str) -> str:
    return _ph.hash(senha)


def conferir_senha(senha: str, hash_armazenado: str | None) -> bool:
    try:
        return _ph.verify(hash_armazenado or _HASH_FALSO, senha) and hash_armazenado is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def papel_do_cpf(cpf: str) -> str:
    h = hash_cpf(cpf)
    if any(hmac.compare_digest(h, hash_cpf(c)) for c in config.ADMIN_CPFS):
        return "admin"
    if any(hmac.compare_digest(h, hash_cpf(c)) for c in config.AUDITOR_CPFS):
        return "auditor"
    return "eleitor"


def criar_token(eleitor_id: int, papel: str) -> tuple[str, str]:
    csrf = secrets.token_urlsafe(24)
    agora = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": str(eleitor_id), "papel": papel, "csrf": csrf, "iat": agora,
         "exp": agora + timedelta(minutes=config.SESSAO_MINUTOS)},
        config.SECRET_KEY, algorithm="HS256",
    )
    return token, csrf


def usuario_atual(request: Request) -> dict:
    token = request.cookies.get(COOKIE_SESSAO)
    if not token:
        raise HTTPException(401, "Não autenticado.")
    try:
        dados = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Sessão inválida ou expirada.")
    return {"id": int(dados["sub"]), "papel": dados["papel"], "csrf": dados["csrf"]}


def usuario_csrf(request: Request, usuario: dict = Depends(usuario_atual)) -> dict:
    """Para rotas que alteram estado: exige o token CSRF no header."""
    enviado = request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(enviado, usuario["csrf"]):
        raise HTTPException(403, "Token CSRF inválido.")
    return usuario


def exigir_papel(*papeis: str):
    def dep(usuario: dict = Depends(usuario_atual)) -> dict:
        if usuario["papel"] not in papeis:
            raise HTTPException(403, "Acesso negado.")
        return usuario
    return dep


class _Limiter:
    def __init__(self, maximo: int, janela: int):
        self.maximo, self.janela = maximo, janela
        self.hits: dict[str, deque] = defaultdict(deque)

    def __call__(self, request: Request) -> None:
        if not config.RATE_LIMIT_ATIVO:
            return
        ip = request.client.host if request.client else "?"
        agora = time.monotonic()
        fila = self.hits[ip]
        while fila and agora - fila[0] > self.janela:
            fila.popleft()
        if len(fila) >= self.maximo:
            raise HTTPException(429, "Muitas requisições. Tente novamente em instantes.")
        fila.append(agora)


limite_auth = _Limiter(maximo=20, janela=60)
