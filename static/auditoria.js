"use strict";

const el = (id) => document.getElementById(id);

function lerCookie(nome) {
  const par = document.cookie.split("; ").find((c) => c.startsWith(nome + "="));
  return par ? decodeURIComponent(par.split("=")[1]) : "";
}

async function api(caminho, metodo = "GET", corpo = null) {
  const opcoes = { method: metodo, headers: {}, credentials: "same-origin" };
  if (corpo) {
    opcoes.headers["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }
  if (metodo !== "GET") {
    opcoes.headers["X-CSRF-Token"] = lerCookie("urna_csrf");
  }
  const resp = await fetch(caminho, opcoes);
  const dados = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(typeof dados.detail === "string" ? dados.detail : "Algo deu errado. Tente de novo.");
  }
  return dados;
}

function celula(tag, texto, classe) {
  const c = document.createElement(tag);
  c.textContent = texto;
  if (classe) {
    c.className = classe;
  }
  return c;
}

function tabela(colunas, linhas) {
  const t = document.createElement("table");
  const cab = document.createElement("tr");
  for (const [titulo, classe] of colunas) {
    cab.appendChild(celula("th", titulo, classe));
  }
  const thead = document.createElement("thead");
  thead.appendChild(cab);
  t.appendChild(thead);
  const corpo = document.createElement("tbody");
  for (const linha of linhas) {
    const tr = document.createElement("tr");
    linha.forEach((valor, i) => tr.appendChild(celula("td", valor, colunas[i][1])));
    corpo.appendChild(tr);
  }
  t.appendChild(corpo);
  return t;
}

function selo(texto, bom) {
  return celula("p", texto, "selo " + (bom ? "bom" : "ruim"));
}

function exibir(...nos) {
  el("Saida").replaceChildren(...nos);
}

const apresentadores = {
  verificar(r) {
    exibir(
      selo(r.integra ? "Registros íntegros." : `Registros adulterados a partir da linha ${r.primeira_linha_invalida}.`, r.integra),
      celula("p", `${r.total} registros verificados.`),
    );
  },
  conferir(r) {
    exibir(
      selo(r.consistente ? "Contagem consistente." : "Contagem divergente.", r.consistente),
      celula("p", `${r.comparecimentos} eleitores votaram e ${r.votos} votos foram registrados.`),
    );
  },
  boletim(r) {
    const linhas = r.candidatos.map((c) => [String(c.numero), c.nome, String(c.votos)]);
    linhas.push(["", "Brancos", String(r.branco)], ["", "Nulos", String(r.nulo)], ["", "Total", String(r.total)]);
    exibir(
      tabela([["Número", "num"], ["Candidato", ""], ["Votos", "num"]], linhas),
      celula("p", `Assinatura do boletim: ${r.hash}`, "hash"),
    );
  },
  log(r) {
    exibir(tabela(
      [["Nº", "num"], ["Quando", ""], ["Evento", ""], ["Detalhe", ""]],
      r.map((l) => [String(l.id), l.ts.replace("T", " ").slice(0, 19), l.evento, l.detalhe]),
    ));
  },
  backup(r) {
    const ok = r.sqlite_integro && r.cadeia_auditoria_integra && r.consistente;
    exibir(
      selo(ok ? "Backup criado e verificado." : "Backup criado, mas a verificação falhou.", ok),
      celula("p", r.arquivo, "hash"),
      celula("p", `SHA-256: ${r.sha256}`, "hash"),
    );
  },
  liberar_lote(r) {
    exibir(
      selo("Lote liberado.", true),
      celula("p", r.mensagem),
    );
  },
};

async function executar(caminho, apresentador, metodo = "GET") {
  el("Mensagem").textContent = "";
  try {
    apresentadores[apresentador](await api(caminho, metodo));
  } catch (e) {
    el("Mensagem").textContent = e.message;
    el("Mensagem").className = "erro";
  }
}

async function entrar() {
  el("Mensagem").textContent = "";
  try {
    const r = await api("/api/login", "POST", { cpf: el("Cpf").value, senha: el("Senha").value });
    el("Senha").value = "";
    if (r.papel === "eleitor") {
      await api("/api/logout", "POST");
      throw new Error("Este CPF não tem perfil de auditor.");
    }
    el("BotaoBackup").hidden = r.papel !== "admin";
    el("BotaoLiberarLote").hidden = r.papel !== "admin";
    el("Login").hidden = true;
    el("Painel").hidden = false;
  } catch (e) {
    el("Mensagem").textContent = e.message;
    el("Mensagem").className = "erro";
  }
}

el("Cpf").addEventListener("input", (e) => {
  const d = e.target.value.replace(/\D/g, "").slice(0, 11);
  e.target.value = d.replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d{1,2})$/, "$1-$2");
});
el("BotaoEntrar").addEventListener("click", entrar);
el("BotaoVerificar").addEventListener("click", () => executar("/api/auditoria/verificar", "verificar"));
el("BotaoConferir").addEventListener("click", () => executar("/api/auditoria/conferencia", "conferir"));
el("BotaoBoletim").addEventListener("click", () => executar("/api/apuracao/boletim", "boletim"));
el("BotaoLog").addEventListener("click", () => executar("/api/auditoria/log?limite=50", "log"));
el("BotaoBackup").addEventListener("click", () => executar("/api/admin/backup", "backup", "POST"));
el("BotaoLiberarLote").addEventListener("click", () => executar("/api/admin/liberar-lote", "liberar_lote", "POST"));
el("BotaoSair").addEventListener("click", async () => {
  await api("/api/logout", "POST").catch(() => {});
  el("Painel").hidden = true;
  el("Login").hidden = false;
  el("Saida").textContent = "Escolha uma ação acima.";
});
