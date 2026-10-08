from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base, Candidato

config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{config.DB_PATH}", connect_args={"timeout": 30})


@event.listens_for(engine, "connect")
def _ao_conectar(dbapi_conn, _):
    # Controle manual de transação: permite BEGIN IMMEDIATE (escritores serializados entre processos).
    dbapi_conn.isolation_level = None
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=FULL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


@event.listens_for(engine, "begin")
def _ao_iniciar(conn):
    conn.exec_driver_sql("BEGIN IMMEDIATE")


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

CANDIDATOS = [
    (13, "Lula", "PT"),
    (14, "Renan Santos", "Missão"),
    (16, "Hertz Dias", "PSTU"),
    (21, "Edmilson Costa", "PCB"),
    (22, "Flávio Bolsonaro", "PL"),
    (27, "Clariana Barão", "DC"),
    (28, "Pablo Marçal", "PRTB"),
    (29, "Rui Costa Pimenta", "PCO"),
    (30, "Zema", "Novo"),
    (35, "Veterinário Wilson Grassi", "Democrata"),
    (55, "Ronaldo Caiado", "PSD"),
    (70, "Escritor Augusto Cury", "Avante"),
    (80, "Samara Martins", "UP"),
]

# Votos e log de auditoria são append-only: o banco recusa UPDATE e DELETE.
TRIGGERS = [
    ("trg_votos_sem_update", "BEFORE UPDATE ON votos"),
    ("trg_votos_sem_delete", "BEFORE DELETE ON votos"),
    ("trg_audit_sem_update", "BEFORE UPDATE ON audit_log"),
    ("trg_audit_sem_delete", "BEFORE DELETE ON audit_log"),
]


def _migrar_remover_data_dos_votos():
    """Bancos criados antes desta versão guardavam a data do voto; ela facilitava ligar voto a eleitor."""
    with engine.begin() as conn:
        colunas = [r[1] for r in conn.execute(text("PRAGMA table_info(votos)"))]
        if "data" in colunas:
            for nome, _ in TRIGGERS:
                conn.execute(text(f"DROP TRIGGER IF EXISTS {nome}"))
            conn.execute(text("ALTER TABLE votos DROP COLUMN data"))


def init_db():
    Base.metadata.create_all(engine)
    _migrar_remover_data_dos_votos()
    with engine.begin() as conn:
        for nome, quando in TRIGGERS:
            conn.execute(text(
                f"CREATE TRIGGER IF NOT EXISTS {nome} {quando} "
                "BEGIN SELECT RAISE(ABORT, 'registro imutavel'); END"
            ))
    with SessionLocal() as db:
        existentes = {c.numero for c in db.query(Candidato).all()}
        for numero, nome, partido in CANDIDATOS:
            if numero not in existentes:
                db.add(Candidato(numero=numero, nome=nome, partido=partido))
        db.commit()


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
