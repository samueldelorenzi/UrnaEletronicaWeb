# Urna Eletrônica Online – Relatório Técnico

Estudo de caso: *Sistema de Votação* (Segurança e Auditoria de Sistemas – UNOESC). Escopo atual: cargo de **PRESIDENTE**, 13 candidatos da atividade (números conferidos no arquivo oficial de candidaturas do TSE, 2026), mais Branco e Nulo.

## Como executar
```
pip install -r requirements.txt
python -m pytest -q
# (opcional) perfis: $env:URNA_AUDITOR_CPFS="CPF1"; $env:URNA_ADMIN_CPFS="CPF2"
python -m uvicorn app.main:app --workers 2
```
Abra http://127.0.0.1:8000. O CPF de auditor/admin precisa antes se cadastrar normalmente; o perfil é concedido no login.
Em produção: TLS (`--ssl-keyfile/--ssl-certfile` ou proxy reverso) e `URNA_COOKIE_SECURE=1`.

## Arquitetura
- **Banco de dados:** SQLite (WAL, `synchronous=FULL`, chaves estrangeiras, `BEGIN IMMEDIATE`).
- **Site de votação:** HTML/JS puro (`static/`), com tela de urna (número, BRANCO, CORRIGE, CONFIRMA) e painel do auditor.
- **API:** FastAPI (`app/`).

## Mecanismos de segurança
| Mecanismo | Onde |
|---|---|
| Validação de CPF (dígitos verificadores) | `security.validar_cpf` |
| Senha com Argon2id + política (10+ caracteres, maiúscula, minúscula, número e símbolo, sem o CPF) | `security.py` |
| CPF armazenado só como HMAC-SHA256 com pepper secreto | `security.hash_cpf` |
| Sessão em JWT, cookie HttpOnly + SameSite=Strict (+ Secure em produção), expiração de 20 min | `security.py`, `routes.py` |
| Sessão encerrada logo após o voto | `routes.votar` |
| Proteção CSRF (token no JWT conferido com header `X-CSRF-Token`) | `security.usuario_csrf` |
| Bloqueio de conta após 5 falhas (15 min), persistido no banco | `routes.login` |
| Rate limit por IP em login/cadastro | `security._Limiter` |
| Resposta com tempo igual para CPF inexistente (anti-enumeração por tempo) | `security.conferir_senha` |
| Controle de acesso por perfil (eleitor, auditor, admin) | `security.exigir_papel` |
| Cabeçalhos: CSP restritiva, X-Frame-Options, nosniff, Referrer-Policy, no-store, HSTS | `main.py` |
| ORM parametrizado (sem SQL concatenado) e validação de entrada (Pydantic) | todo o código |
| Front sem `innerHTML` com dados, sem scripts inline (compatível com CSP) | `static/` |
| Segredos fora do código (ambiente ou `data/.secrets`) | `config.py` |
| Documentação da API desativada em produção | `main.py` |

## Voto único e sigilo
- `comparecimento` guarda **quem votou** (chave primária = eleitor). `votos` guarda **o voto**, sem eleitor, sem hora, com UUID aleatório e sem `rowid` (`WITHOUT ROWID`), para não preservar a ordem de inserção.
- O registro de comparecimento e o voto entram **na mesma transação**. A chave primária de `comparecimento` garante o voto único mesmo com requisições concorrentes (testado com 10 requisições simultâneas: 1 aceita, 9 recusadas).
- **Comprovante:** código aleatório mostrado ao eleitor. O banco guarda só o SHA-256. O eleitor confirma que seu voto foi contado sem provar em quem votou.

## Auditoria
- **Log encadeado por hash** (`audit_log`): cada linha contém o SHA-256 da anterior. Eventos: cadastro, login ok e falha, bloqueio, voto registrado, voto duplicado bloqueado, acessos do auditor, boletim, backup. O CPF nunca entra no log (só identificadores derivados por HMAC).
- **Imutabilidade:** triggers do banco recusam UPDATE e DELETE em `votos` e `audit_log`. Quem tiver acesso privilegiado ao arquivo ainda pode removê-los, mas a adulteração é detectada pela cadeia (testado).
- **Rotas do auditor:** `/api/auditoria/verificar` (cadeia), `/api/auditoria/conferencia` (comparecimentos = votos), `/api/auditoria/log` e `/api/apuracao/boletim` (totais com hash).

## Redundância
- `python -m app.backup backup`: cópia consistente com o banco em uso (API de backup online do SQLite), com `integrity_check`, verificação da cadeia de auditoria e arquivo `.sha256`.
- `python -m app.backup replicar --intervalo 30`: réplica contínua para `URNA_REPLICA_DIR` (aponte para outro disco ou compartilhamento de rede).
- `python -m app.backup verificar ARQ` e `restaurar ARQ`: a restauração recusa backups corrompidos e guarda uma cópia do banco atual.
- **Aplicação:** `uvicorn --workers N` mantém vários processos sobre o mesmo banco (WAL e `BEGIN IMMEDIATE` serializam as escritas). Se um processo cair, os outros atendem. `/health` serve para monitoramento.

## Limitações
- Protótipo acadêmico: **não valida o eleitor** em base real (qualquer CPF válido se cadastra) e **não substitui a urna oficial**.
- O operador do servidor continua sendo ponto de confiança. O sigilo depende da separação das tabelas e de não registrar horário nem ordem.
- O rate limit por IP é em memória por processo (o bloqueio de conta é persistido no banco).
- SQLite limita a escrita a um processo por vez. Para escala nacional e réplica em tempo real, a evolução natural é PostgreSQL com replicação em streaming, balanceador (Nginx) e TLS no balanceador.
- O cadastro responde "CPF já cadastrado" (revela que o CPF existe). Isso é um trade-off de usabilidade.
