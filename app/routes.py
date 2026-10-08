import hashlib
import json
import secrets
import time
import uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit, backup, config, lote, security
from .database import get_db
from .models import AuditLog, Candidato, Comparecimento, Eleitor, TentativaLogin, Voto, VotoPendente

router = APIRouter(prefix="/api")

class CadastroIn(BaseModel):
    cpf: str = Field(max_length=20)
    senha: str = Field(max_length=128)

class VotoIn(BaseModel):
    tipo: Literal["candidato", "branco", "nulo"]
    numero: Optional[int] = Field(default=None, ge=1, le=99)

class ComprovanteIn(BaseModel):
    codigo: str = Field(max_length=64)

def _definir_cookies(resp: Response, token: str, csrf: str) -> None:
    # TODO: verificar se o httponly tá funcionando mesmo na apresentação
    resp.set_cookie(security.COOKIE_SESSAO, token, httponly=True, secure=config.COOKIE_SECURE,
                    samesite="strict", max_age=config.SESSAO_MINUTOS * 60, path="/")
    resp.set_cookie(security.COOKIE_CSRF, csrf, httponly=False, secure=config.COOKIE_SECURE,
                    samesite="strict", max_age=config.SESSAO_MINUTOS * 60, path="/")

def _limpar_cookies(resp: Response) -> None:
    resp.delete_cookie(security.COOKIE_SESSAO, path="/")
    resp.delete_cookie(security.COOKIE_CSRF, path="/")

@router.post("/cadastro", status_code=201, dependencies=[Depends(security.limite_auth)])
def cadastro(dados: CadastroIn, db: Session = Depends(get_db)):
    if not security.validar_cpf(dados.cpf):
        raise HTTPException(422, "CPF inválido.")
    erro = security.validar_senha(dados.senha, dados.cpf)
    if erro:
        raise HTTPException(422, erro)
        
    db.add(Eleitor(cpf_hmac=security.hash_cpf(dados.cpf), senha_hash=security.hash_senha(dados.senha),
                   criado_em=datetime.now(timezone.utc).isoformat(timespec="seconds")))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # print("erro ao inserir eleitor")
        raise HTTPException(409, "CPF já cadastrado.")
        
    audit.registrar(db, "cadastro", detalhe="novo eleitor")
    db.commit()
    return {"mensagem": "Cadastro realizado."}

@router.post("/login", dependencies=[Depends(security.limite_auth)])
def login(dados: CadastroIn, resp: Response, db: Session = Depends(get_db)):
    chave = security.hash_cpf(dados.cpf)
    tentativa = db.get(TentativaLogin, chave)
    agora = time.time()
    
    if tentativa and tentativa.bloqueado_ate > agora:
        raise HTTPException(429, "Conta temporariamente bloqueada por tentativas falhas.")

    eleitor = db.scalar(select(Eleitor).where(Eleitor.cpf_hmac == chave)) if security.validar_cpf(dados.cpf) else None
    
    if not security.conferir_senha(dados.senha, eleitor.senha_hash if eleitor else None):
        if tentativa is None:
            tentativa = TentativaLogin(chave=chave, falhas=0, bloqueado_ate=0.0)
            db.add(tentativa)
        tentativa.falhas += 1
        if tentativa.falhas >= config.MAX_FALHAS_LOGIN:
            tentativa.falhas = 0
            tentativa.bloqueado_ate = agora + config.BLOQUEIO_SEGUNDOS
            audit.registrar(db, "conta_bloqueada", ator=chave[:16], detalhe="falhas consecutivas")
        audit.registrar(db, "login_falha", ator=chave[:16])
        db.commit()
        raise HTTPException(401, "CPF ou senha incorretos.")

    if tentativa:
        tentativa.falhas = 0
        tentativa.bloqueado_ate = 0.0
        
    papel = security.papel_do_cpf(dados.cpf)
    token, csrf = security.criar_token(eleitor.id, papel)
    audit.registrar(db, "login_ok", ator=security.ator_id(eleitor.id), detalhe=papel)
    
    ja_votou = db.get(Comparecimento, eleitor.id) is not None
    db.commit()
    
    _definir_cookies(resp, token, csrf)
    return {"papel": papel, "ja_votou": ja_votou}

@router.post("/logout")
def logout(resp: Response):
    _limpar_cookies(resp)
    return {"mensagem": "Sessão encerrada."}

@router.get("/me")
def me(usuario: dict = Depends(security.usuario_atual), db: Session = Depends(get_db)):
    return {"papel": usuario["papel"], "ja_votou": db.get(Comparecimento, usuario["id"]) is not None}

@router.get("/candidatos")
def candidatos(_: dict = Depends(security.usuario_atual), db: Session = Depends(get_db)):
    return [{"numero": c.numero, "nome": c.nome, "partido": c.partido, "foto": f"/fotos/{c.numero}.jpg"}
            for c in db.scalars(select(Candidato).order_by(Candidato.numero))]

@router.post("/votar", status_code=201)
def votar(dados: VotoIn, resp: Response, usuario: dict = Depends(security.usuario_csrf),
          db: Session = Depends(get_db)):
    candidato = None
    if dados.tipo == "candidato":
        candidato = db.scalar(select(Candidato).where(Candidato.numero == dados.numero))
        if candidato is None:
            raise HTTPException(422, "Candidato inexistente.")
    elif dados.numero is not None:
        raise HTTPException(422, "Branco e nulo não levam número.")

    hoje = date.today().isoformat()
    ator = security.ator_id(usuario["id"])
    db.add(Comparecimento(eleitor_id=usuario["id"], data=hoje))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        audit.registrar(db, "voto_duplicado_bloqueado", ator=ator)
        db.commit()
        raise HTTPException(409, "Este CPF já votou.")

    codigo = secrets.token_urlsafe(12)
    db.add(VotoPendente(conteudo=security.cifrar_voto({
        "tipo": dados.tipo, "candidato_id": candidato.id if candidato else None,
        "voto_hash": hashlib.sha256(codigo.encode()).hexdigest()})))
        
    audit.registrar(db, "voto_registrado", ator=ator)
    lote.liberar(db, config.LOTE_MINIMO)
    db.commit()
    
    _limpar_cookies(resp) # mata a sessão pra não votar de novo
    return {"mensagem": "Voto registrado.", "comprovante": codigo}

@router.post("/comprovante/verificar")
def verificar_comprovante(dados: ComprovanteIn, db: Session = Depends(get_db),
                          _: dict = Depends(security.limite_auth)):
    h = hashlib.sha256(dados.codigo.encode()).hexdigest()
    contabilizado = db.scalar(select(Voto.id).where(Voto.voto_hash == h)) is not None
    aguardando = not contabilizado and lote.hash_pendente(db, h)
    return {"contabilizado": contabilizado, "aguardando_lote": aguardando}

# ---- Auditoria e apuração ----
auditor = security.exigir_papel("auditor", "admin")

def _acesso(db: Session, usuario: dict, rota: str) -> None:
    audit.registrar(db, "auditor_acesso", ator=security.ator_id(usuario["id"]), detalhe=rota)
    db.commit()

@router.get("/auditoria/verificar")
def auditoria_verificar(usuario: dict = Depends(auditor), db: Session = Depends(get_db)):
    resultado = audit.verificar_cadeia(db)
    _acesso(db, usuario, "verificar")
    return resultado

@router.get("/auditoria/log")
def auditoria_log(limite: int = 100, usuario: dict = Depends(auditor), db: Session = Depends(get_db)):
    limite = max(1, min(limite, 500))
    linhas = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limite)).all()
    _acesso(db, usuario, "log")
    return [{"id": l.id, "ts": l.ts, "evento": l.evento, "ator": l.ator, "detalhe": l.detalhe,
             "hash": l.hash} for l in linhas]

@router.get("/auditoria/conferencia")
def auditoria_conferencia(usuario: dict = Depends(auditor), db: Session = Depends(get_db)):
    comparecimentos = db.scalar(select(func.count()).select_from(Comparecimento))
    votos = db.scalar(select(func.count()).select_from(Voto))
    pendentes = lote.contar_pendentes(db)
    _acesso(db, usuario, "conferencia")
    return {"comparecimentos": comparecimentos, "votos": votos, "aguardando_lote": pendentes,
            "consistente": comparecimentos == votos + pendentes}

@router.get("/apuracao/boletim")
def boletim(usuario: dict = Depends(auditor), db: Session = Depends(get_db)):
    por_candidato = {c.numero: 0 for c in db.scalars(select(Candidato))}
    nomes = {c.numero: f"{c.nome} ({c.partido})" for c in db.scalars(select(Candidato))}
    
    for numero, qtd in db.execute(
            select(Candidato.numero, func.count(Voto.id)).join(Voto, Voto.candidato_id == Candidato.id)
            .group_by(Candidato.numero)):
        por_candidato[numero] = qtd
        
    branco = db.scalar(select(func.count()).select_from(Voto).where(Voto.tipo == "branco"))
    nulo = db.scalar(select(func.count()).select_from(Voto).where(Voto.tipo == "nulo"))
    
    corpo = {
        "cargo": "PRESIDENTE",
        "candidatos": [{"numero": n, "nome": nomes[n], "votos": q} for n, q in sorted(por_candidato.items())],
        "branco": branco, "nulo": nulo,
        "total": sum(por_candidato.values()) + branco + nulo,
        "aguardando_lote": lote.contar_pendentes(db),
    }
    
    corpo["hash"] = hashlib.sha256(json.dumps(corpo, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    audit.registrar(db, "boletim_gerado", ator=security.ator_id(usuario["id"]), detalhe=corpo["hash"][:16])
    db.commit()
    return corpo

@router.post("/admin/backup")
def admin_backup(usuario: dict = Depends(security.exigir_papel("admin")), db: Session = Depends(get_db)):
    resultado = backup.fazer_backup()
    audit.registrar(db, "backup", ator=security.ator_id(usuario["id"]), detalhe=resultado["arquivo"][-60:])
    db.commit()
    return resultado

@router.post("/admin/liberar-lote")
def admin_liberar_lote(usuario: dict = Depends(security.exigir_papel("admin")), db: Session = Depends(get_db)):
    # TODO: professor disse que só pode rodar no fim da eleição, implementar trava de horário?
    qtd = lote.liberar(db, 0, forcar=True)
    audit.registrar(db, "lote_forçado", ator=security.ator_id(usuario["id"]), detalhe=f"{qtd} votos")
    db.commit()
    return {"mensagem": f"{qtd} votos liberados.", "quantidade": qtd}
