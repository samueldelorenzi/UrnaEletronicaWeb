import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from app import backup, config, security
from app.main import app
from conftest import ADMIN_CPF, AUDITOR_CPF, SENHA, cadastrar_e_entrar, csrf, gerar_cpf, novo_cliente


# ---- CPF e cadastro ----
def test_validacao_cpf():
    assert security.validar_cpf("529.982.247-25")
    assert not security.validar_cpf("529.982.247-24")
    assert not security.validar_cpf("111.111.111-11")
    assert not security.validar_cpf("123")


def test_cadastro_cpf_invalido():
    c = novo_cliente()
    assert c.post("/api/cadastro", json={"cpf": "111.111.111-11", "senha": SENHA}).status_code == 422


def test_cadastro_senha_fraca():
    c = novo_cliente()
    assert c.post("/api/cadastro", json={"cpf": gerar_cpf(), "senha": "curta"}).status_code == 422
    assert c.post("/api/cadastro", json={"cpf": gerar_cpf(), "senha": "semsimbolo1234"}).status_code == 422


def test_cadastro_duplicado():
    c, cpf = cadastrar_e_entrar()
    assert novo_cliente().post("/api/cadastro", json={"cpf": cpf, "senha": SENHA}).status_code == 409


def test_cpf_nao_armazenado_em_texto_puro():
    _, cpf = cadastrar_e_entrar()
    con = sqlite3.connect(config.DB_PATH)
    dump = "\n".join(con.iterdump())
    con.close()
    assert cpf not in dump


# ---- Votação ----
def test_voto_registrado_encerra_sessao():
    c, _ = cadastrar_e_entrar()
    r = c.post("/api/votar", json={"tipo": "candidato", "numero": 13}, headers=csrf(c))
    assert r.status_code == 201 and r.json()["comprovante"]
    assert c.get("/api/me").status_code == 401


def test_voto_duplicado_mesmo_cpf():
    c, cpf = cadastrar_e_entrar()
    assert c.post("/api/votar", json={"tipo": "branco"}, headers=csrf(c)).status_code == 201
    c2 = novo_cliente()
    assert c2.post("/api/login", json={"cpf": cpf, "senha": SENHA}).json()["ja_votou"] is True
    assert c2.post("/api/votar", json={"tipo": "nulo"}, headers=csrf(c2)).status_code == 409


def test_votar_sem_login():
    assert novo_cliente().post("/api/votar", json={"tipo": "branco"}).status_code == 401


def test_votar_sem_csrf(eleitor):
    assert eleitor.post("/api/votar", json={"tipo": "branco"}).status_code == 403
    assert eleitor.post("/api/votar", json={"tipo": "branco"}, headers={"X-CSRF-Token": "errado"}).status_code == 403


def test_candidato_inexistente_e_dados_invalidos(eleitor):
    assert eleitor.post("/api/votar", json={"tipo": "candidato", "numero": 99}, headers=csrf(eleitor)).status_code == 422
    assert eleitor.post("/api/votar", json={"tipo": "candidato"}, headers=csrf(eleitor)).status_code == 422
    assert eleitor.post("/api/votar", json={"tipo": "branco", "numero": 13}, headers=csrf(eleitor)).status_code == 422
    assert eleitor.post("/api/votar", json={"tipo": "xyz"}, headers=csrf(eleitor)).status_code == 422


def test_voto_concorrente_mesmo_cpf():
    _, cpf = cadastrar_e_entrar()
    clientes = []
    for _ in range(10):
        c = novo_cliente()
        assert c.post("/api/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200
        clientes.append(c)
    codigos = []

    def votar(c):
        codigos.append(c.post("/api/votar", json={"tipo": "candidato", "numero": 22}, headers=csrf(c)).status_code)

    threads = [threading.Thread(target=votar, args=(c,)) for c in clientes]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codigos.count(201) == 1
    assert codigos.count(409) == 9


def test_comprovante():
    c, _ = cadastrar_e_entrar()
    codigo = c.post("/api/votar", json={"tipo": "branco"}, headers=csrf(c)).json()["comprovante"]
    
    r = c.post("/api/comprovante/verificar", json={"codigo": codigo}).json()
    assert r["contabilizado"] is False and r["aguardando_lote"] is True
    
    admin = _admin()
    admin.post("/api/admin/liberar-lote", headers=csrf(admin))
    
    r = c.post("/api/comprovante/verificar", json={"codigo": codigo}).json()
    assert r["contabilizado"] is True and r["aguardando_lote"] is False


# ---- Anonimato ----
def test_nenhuma_tabela_liga_eleitor_a_voto():
    con = sqlite3.connect(config.DB_PATH)
    colunas_votos = {r[1] for r in con.execute("PRAGMA table_info(votos)")}
    colunas_comp = {r[1] for r in con.execute("PRAGMA table_info(comparecimento)")}
    con.close()
    assert not any("eleitor" in c for c in colunas_votos)
    assert not any("candidato" in c or "voto" in c for c in colunas_comp)


# ---- Imutabilidade e auditoria ----
def test_triggers_bloqueiam_alteracao():
    # Garantir que há registros para que o trigger (por linha) dispare
    c, _ = cadastrar_e_entrar()
    c.post("/api/votar", json={"tipo": "branco"}, headers=csrf(c))
    admin = _admin()
    admin.post("/api/admin/liberar-lote", headers=csrf(admin))
    
    con = sqlite3.connect(config.DB_PATH)
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE audit_log SET evento = 'x' WHERE id = 1")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM votos")
    con.close()


def _auditor():
    return cadastrar_e_entrar(AUDITOR_CPF)[0] if _primeira("a") else _login(AUDITOR_CPF)


_vistos = set()


def _primeira(chave):
    if chave in _vistos:
        return False
    _vistos.add(chave)
    return True


def _login(cpf):
    c = novo_cliente()
    assert c.post("/api/login", json={"cpf": cpf, "senha": SENHA}).status_code == 200
    return c


def test_eleitor_comum_nao_acessa_auditoria(eleitor):
    assert eleitor.get("/api/auditoria/verificar").status_code == 403
    assert eleitor.get("/api/apuracao/boletim").status_code == 403
    assert novo_cliente().get("/api/auditoria/log").status_code == 401


def test_cadeia_conferencia_e_boletim():
    for tipo in ("candidato", "branco", "nulo"):
        c, _ = cadastrar_e_entrar()
        corpo = {"tipo": tipo, "numero": 13} if tipo == "candidato" else {"tipo": tipo}
        c.post("/api/votar", json=corpo, headers=csrf(c))
        
    admin = _admin()
    admin.post("/api/admin/liberar-lote", headers=csrf(admin))
    
    a = _auditor()
    assert a.get("/api/auditoria/verificar").json()["integra"] is True
    conf = a.get("/api/auditoria/conferencia").json()
    assert conf["consistente"] is True and conf["votos"] == conf["comparecimentos"]
    assert conf["aguardando_lote"] == 0
    b = a.get("/api/apuracao/boletim").json()
    assert b["total"] == conf["votos"]
    assert sum(x["votos"] for x in b["candidatos"]) + b["branco"] + b["nulo"] == b["total"]
    assert len(b["candidatos"]) == 13 and len(b["hash"]) == 64


def test_adulteracao_do_log_e_detectada():
    a = _auditor()
    assert a.get("/api/auditoria/verificar").json()["integra"] is True
    con = sqlite3.connect(config.DB_PATH)
    con.isolation_level = None
    con.execute("DROP TRIGGER trg_audit_sem_update")  # atacante com acesso privilegiado ao arquivo
    original = con.execute("SELECT detalhe FROM audit_log WHERE id = 2").fetchone()[0]
    con.execute("UPDATE audit_log SET detalhe = 'adulterado' WHERE id = 2")
    r = a.get("/api/auditoria/verificar").json()
    assert r["integra"] is False and r["primeira_linha_invalida"] == 2
    # desfaz a adulteração e recria o trigger para não afetar outros testes
    con.execute("UPDATE audit_log SET detalhe = ? WHERE id = 2", (original,))
    con.execute("CREATE TRIGGER trg_audit_sem_update BEFORE UPDATE ON audit_log "
                "BEGIN SELECT RAISE(ABORT, 'registro imutavel'); END")
    con.close()
    assert a.get("/api/auditoria/verificar").json()["integra"] is True


# ---- Força bruta ----
def test_bloqueio_apos_falhas():
    _, cpf = cadastrar_e_entrar()
    c = novo_cliente()
    for _ in range(config.MAX_FALHAS_LOGIN):
        assert c.post("/api/login", json={"cpf": cpf, "senha": "Errada#12345"}).status_code == 401
    assert c.post("/api/login", json={"cpf": cpf, "senha": SENHA}).status_code == 429


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_ATIVO", True)
    monkeypatch.setattr(security.limite_auth, "maximo", 3)
    security.limite_auth.hits.clear()
    c = novo_cliente()
    codigos = [c.post("/api/login", json={"cpf": gerar_cpf(), "senha": "x"}).status_code for _ in range(5)]
    security.limite_auth.hits.clear()
    assert 429 in codigos


def test_headers_de_seguranca():
    r = novo_cliente().get("/health")
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_cookie_httponly():
    _, cpf = cadastrar_e_entrar()
    r = novo_cliente().post("/api/login", json={"cpf": cpf, "senha": SENHA})
    sessao = [h for h in r.headers.get_list("set-cookie") if h.startswith("urna_sessao")][0].lower()
    assert "httponly" in sessao and "samesite=strict" in sessao


# ---- Redundância ----
def test_backup_verificacao_e_restauracao(tmp_path):
    admin = _admin()
    admin.post("/api/admin/liberar-lote", headers=csrf(admin))
    r = admin.post("/api/admin/backup", headers=csrf(admin)).json()
    assert r["sqlite_integro"] and r["cadeia_auditoria_integra"] and r["consistente"]
    from pathlib import Path
    assert backup.verificar(Path(r["arquivo"]))["sqlite_integro"]
    # backup corrompido é recusado
    ruim = tmp_path / "ruim.db"
    ruim.write_bytes(Path(r["arquivo"]).read_bytes())
    Path(str(ruim) + ".sha256").write_text("0" * 64)
    with pytest.raises(SystemExit):
        backup.restaurar(ruim)


def _admin():
    if _primeira("admin"):
        return cadastrar_e_entrar(ADMIN_CPF)[0]
    return _login(ADMIN_CPF)


def test_health():
    assert novo_cliente().get("/health").json() == {"status": "ok"}

