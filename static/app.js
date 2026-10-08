"use strict";

const estado = { candidatos: [], digitos: "", branco: false };
const el = (id) => document.getElementById(id);
const TELAS = ["TelaAcesso", "TelaUrna", "TelaFim", "TelaJaVotou"];

function mostrarTela(nome) {
  for (const tela of TELAS) {
    el(tela).hidden = tela !== nome;
  }
  const votando = nome === "TelaUrna";
  el("PainelTeclas").hidden = !votando;
  el("Guia").hidden = !votando;
  const alvo = el(nome);
  alvo.tabIndex = -1;
  alvo.focus({ preventScroll: true });
}

function mensagem(texto, erro = true) {
  const m = el("Mensagem");
  m.textContent = texto || "";
  m.className = erro ? "erro" : "ok";
}

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
    const detalhe = Array.isArray(dados.detail) ? "Confira os dados informados." : dados.detail;
    throw new Error(detalhe || "Algo deu errado. Tente de novo.");
  }
  return dados;
}

function mascararCpf(valor) {
  const d = valor.replace(/\D/g, "").slice(0, 11);
  return d.replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d{1,2})$/, "$1-$2");
}

function candidatoAtual() {
  return estado.candidatos.find((x) => String(x.numero) === estado.digitos) || null;
}

function renderizarUrna() {
  const completo = estado.digitos.length === 2;
  const c = completo ? candidatoAtual() : null;

  el("Casa0").textContent = estado.digitos[0] || "";
  el("Casa1").textContent = estado.digitos[1] || "";
  el("Casa0").classList.toggle("ativa", !estado.branco && estado.digitos.length === 0);
  el("Casa1").classList.toggle("ativa", !estado.branco && estado.digitos.length === 1);

  const dados = el("Dados");
  const retrato = el("Retrato");
  const rodape = el("RodapeTela");
  dados.textContent = "";
  dados.classList.remove("alerta");

  const fotoAnterior = retrato.getAttribute("src");
  if (c) {
    const nome = document.createElement("p");
    nome.className = "nome";
    nome.textContent = c.nome;
    const partido = document.createElement("p");
    partido.textContent = c.partido;
    dados.append(nome, partido);
    if (fotoAnterior !== c.foto) {
      retrato.src = c.foto;
      retrato.classList.remove("entrando");
      void retrato.offsetWidth;
      retrato.classList.add("entrando");
    }
    retrato.alt = `Foto de ${c.nome}`;
    retrato.classList.remove("vazio");
    rodape.textContent = "Confira a foto e o nome. Confirma registra o voto. Corrige recomeça.";
  } else {
    retrato.classList.add("vazio");
    retrato.removeAttribute("src");
    retrato.alt = "";
    if (estado.branco) {
      dados.textContent = "Voto em branco";
      dados.classList.add("alerta");
      rodape.textContent = "Confirma registra o voto em branco. Corrige recomeça.";
    } else if (completo) {
      dados.textContent = "Número errado. O voto será nulo.";
      dados.classList.add("alerta");
      rodape.textContent = "Confirma registra voto nulo. Corrige recomeça.";
    } else {
      rodape.textContent = "Digite o número do candidato.";
    }
  }

  const temEntrada = estado.digitos.length > 0 || estado.branco;
  el("BotaoConfirma").disabled = !(completo || estado.branco);
  el("BotaoCorrige").disabled = !temEntrada;
  el("BotaoBranco").disabled = estado.digitos.length > 0 || estado.branco;
  for (const b of el("Teclado").querySelectorAll("button")) {
    b.disabled = estado.branco || completo;
  }
}

function digitar(d) {
  if (estado.branco || estado.digitos.length >= 2) {
    return;
  }
  estado.digitos += d;
  renderizarUrna();
}

function corrigir() {
  estado.digitos = "";
  estado.branco = false;
  renderizarUrna();
}

function montarGuia() {
  const lista = el("ListaCandidatos");
  lista.textContent = "";
  for (const c of estado.candidatos) {
    const li = document.createElement("li");
    const botao = document.createElement("button");
    botao.type = "button";
    const img = document.createElement("img");
    img.src = c.foto;
    img.alt = "";
    img.width = 40;
    img.height = 56;
    img.loading = "lazy";
    const numero = document.createElement("span");
    numero.className = "numero";
    numero.textContent = c.numero;
    const nome = document.createElement("span");
    nome.textContent = c.nome;
    const partido = document.createElement("span");
    partido.className = "partido";
    partido.textContent = c.partido;
    nome.appendChild(partido);
    botao.append(img, numero, nome);
    botao.addEventListener("click", () => {
      estado.branco = false;
      estado.digitos = String(c.numero);
      renderizarUrna();
      el("BotaoConfirma").focus();
    });
    li.appendChild(botao);
    lista.appendChild(li);
  }
}

async function iniciarUrna() {
  estado.candidatos = await api("/api/candidatos");
  montarGuia();
  estado.digitos = "";
  estado.branco = false;
  renderizarUrna();
  mostrarTela("TelaUrna");
}

async function entrar() {
  mensagem("");
  try {
    const r = await api("/api/login", "POST", { cpf: el("Cpf").value, senha: el("Senha").value });
    el("Senha").value = "";
    if (r.ja_votou) {
      mostrarTela("TelaJaVotou");
    } else {
      await iniciarUrna();
    }
  } catch (e) {
    mensagem(e.message);
  }
}

async function criarConta() {
  mensagem("");
  try {
    await api("/api/cadastro", "POST", { cpf: el("Cpf").value, senha: el("Senha").value });
    mensagem("Conta criada. Agora clique em Entrar.", false);
  } catch (e) {
    mensagem(e.message);
  }
}

async function conferirComprovante() {
  mensagem("");
  const codigo = el("CodigoConferir").value.trim();
  if (!codigo) {
    mensagem("Digite o código do comprovante.");
    return;
  }
  try {
    const r = await api("/api/comprovante/verificar", "POST", { codigo });
    if (r.contabilizado) {
      mensagem("Este voto já foi processado e contabilizado.", false);
    } else if (r.aguardando_lote) {
      mensagem("Seu voto foi recebido e está aguardando o processamento em lote.", false);
    } else {
      mensagem("Código não encontrado. Confira se digitou igual ao recebido.");
    }
  } catch (e) {
    // TODO: tratar erro de rede separado?
    mensagem(e.message);
  }
}

async function confirmar() {
  mensagem("");
  let corpo;
  if (estado.branco) {
    corpo = { tipo: "branco" };
  } else if (estado.digitos.length === 2) {
    const c = candidatoAtual();
    corpo = c ? { tipo: "candidato", numero: c.numero } : { tipo: "nulo" };
  } else {
    return;
  }
  el("BotaoConfirma").disabled = true;
  try {
    const r = await api("/api/votar", "POST", corpo);
    el("Comprovante").textContent = r.comprovante;
    mostrarTela("TelaFim");
  } catch (e) {
    mensagem(e.message);
    renderizarUrna();
  }
}

async function copiarCodigo() {
  try {
    await navigator.clipboard.writeText(el("Comprovante").textContent);
    mensagem("Código copiado.", false);
  } catch (e) {
    mensagem("Não foi possível copiar. Selecione o código e copie manualmente.");
  }
}

async function sair() {
  await api("/api/logout", "POST").catch(() => {});
  estado.digitos = "";
  estado.branco = false;
  el("Comprovante").textContent = "";
  mensagem("");
  mostrarTela("TelaAcesso");
}

function montarTeclado() {
  const teclado = el("Teclado");
  for (const d of ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", ""]) {
    if (d === "") {
      teclado.appendChild(document.createElement("span"));
      continue;
    }
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = d;
    b.setAttribute("aria-label", `Número ${d}`);
    b.addEventListener("click", () => digitar(d));
    teclado.appendChild(b);
  }
}

function aoPressionarTecla(e) {
  if (el("TelaUrna").hidden || e.ctrlKey || e.metaKey || e.altKey) {
    return;
  }
  if (/^[0-9]$/.test(e.key) && document.activeElement.tagName !== "INPUT") {
    digitar(e.key);
  } else if (e.key === "Backspace") {
    corrigir();
  }
}

async function iniciar() {
  montarTeclado();
  el("Cpf").addEventListener("input", (e) => { e.target.value = mascararCpf(e.target.value); });
  el("Senha").addEventListener("keydown", (e) => { if (e.key === "Enter") { entrar(); } });
  el("BotaoEntrar").addEventListener("click", entrar);
  el("BotaoCadastrar").addEventListener("click", criarConta);
  el("BotaoConferir").addEventListener("click", conferirComprovante);
  el("BotaoBranco").addEventListener("click", () => { estado.branco = true; renderizarUrna(); });
  el("BotaoCorrige").addEventListener("click", corrigir);
  el("BotaoConfirma").addEventListener("click", confirmar);
  el("BotaoCopiar").addEventListener("click", copiarCodigo);
  el("BotaoNovo").addEventListener("click", sair);
  el("BotaoSairJaVotou").addEventListener("click", sair);
  document.addEventListener("keydown", aoPressionarTecla);
  try {
    const eu = await api("/api/me");
    if (eu.ja_votou) {
      mostrarTela("TelaJaVotou");
    } else {
      await iniciarUrna();
    }
  } catch (e) {
    mostrarTela("TelaAcesso");
  }
}

iniciar();
