/* Maria Helena: front-end sem dependências. Tudo que vem do servidor entra na página como texto (nunca como HTML). */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const estado = { token: null, usuario: null, sessao: null, ocupado: false };
  const CHAVE_TOKEN = "mh_token";

  /* ---------------------------------------------------------------- util */
  function el(tag, props = {}, ...filhos) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v;
      else if (k === "texto") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    for (const f of filhos) if (f != null) e.append(f);
    return e;
  }

  function avisar(texto, ms = 3500) {
    const a = $("aviso");
    a.textContent = texto;
    a.hidden = false;
    clearTimeout(avisar._t);
    avisar._t = setTimeout(() => (a.hidden = true), ms);
  }

  const brl = (n) => Number(n).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  const dataBr = (iso) => (/^\d{4}-\d{2}-\d{2}/.test(iso) ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : iso);

  async function api(caminho, { metodo = "GET", corpo, form, tipo } = {}) {
    const cab = {};
    if (estado.token) cab.Authorization = `Bearer ${estado.token}`;
    let body;
    if (corpo !== undefined) { cab["Content-Type"] = "application/json"; body = JSON.stringify(corpo); }
    if (form) body = form;
    const r = await fetch(caminho, { method: metodo, headers: cab, body });
    if (r.status === 401 && estado.token) { sair(false); throw new Error("Sua sessão expirou. Entre de novo."); }
    if (tipo === "blob" && r.ok) return r.blob();
    let dados = null;
    try { dados = await r.json(); } catch (_) { /* resposta sem JSON */ }
    if (!r.ok) {
      const d = dados && (dados.detail || dados.mensagem || dados.falha);
      const err = new Error(typeof d === "string" ? d : "Não foi possível concluir a operação.");
      err.status = r.status; err.dados = dados;
      throw err;
    }
    return dados;
  }

  /* --------------------------------------------------------------- sessão */
  function mostrarLogin() { $("app").hidden = true; $("tela-login").hidden = false; $("usuario").focus(); }
  function mostrarApp() { $("tela-login").hidden = true; $("app").hidden = false; }

  async function entrar(usuario, senha) {
    const corpo = new URLSearchParams({ username: usuario, password: senha });
    const r = await fetch("/token", { method: "POST", body: corpo });
    const dados = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(dados.detail || "Não consegui entrar.");
    estado.token = dados.access_token;
    sessionStorage.setItem(CHAVE_TOKEN, estado.token);
    await carregarUsuario();
  }

  async function carregarUsuario() {
    estado.usuario = await api("/users/me");
    $("quem").textContent = `${estado.usuario.username} · ${estado.usuario.tenant_id}`;
    mostrarApp();
    if (!$("mensagens").children.length) boasVindas();
    carregarPainel();
  }

  async function sair(chamarServidor = true) {
    if (chamarServidor && estado.token) { try { await api("/logout", { metodo: "POST" }); } catch (_) { /* já inválido */ } }
    estado.token = null; estado.usuario = null; estado.sessao = null;
    sessionStorage.removeItem(CHAVE_TOKEN);
    $("mensagens").replaceChildren();
    mostrarLogin();
  }

  /* ---------------------------------------------------------------- chat */
  function adicionar(classe, conteudo) {
    const m = el("div", { class: `msg ${classe}` });
    if (typeof conteudo === "string") m.textContent = conteudo; else m.append(conteudo);
    $("mensagens").append(m);
    $("mensagens").scrollTop = $("mensagens").scrollHeight;
    return m;
  }

  function boasVindas() {
    adicionar("ela", `Oi, ${estado.usuario.username}! Eu calculo rescisão, férias, 13º, INSS, IRRF, FGTS e folha, e confiro documentos (holerite, TRCT, guias, SPED, NF-e e outros). Escolha um atalho ou escreva o que precisa. Sou uma assistente virtual (IA): em decisões importantes, confira com o contador responsável.`);
  }

  function baixar(blob, nome) {
    const url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: nome });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  function botaoPdf() {
    return el("button", {
      type: "button", class: "botao",
      onclick: async (ev) => {
        const b = ev.currentTarget; b.disabled = true;
        try { baixar(await api(`/api/chat/${estado.sessao}/pdf`, { tipo: "blob" }), "calculo.pdf"); }
        catch (e) { avisar(e.message); }
        finally { b.disabled = false; }
      },
    }, "Baixar PDF do cálculo");
  }

  async function enviar(texto) {
    texto = texto.trim();
    if (!texto || estado.ocupado) return;
    estado.ocupado = true; $("botao-enviar").disabled = true;
    adicionar("eu", texto);
    const pensando = adicionar("ela", el("span", { class: "digitando", "aria-label": "Digitando" }, el("i"), el("i"), el("i")));
    try {
      const r = await api("/api/chat", { metodo: "POST", corpo: { message: texto, session_id: estado.sessao } });
      estado.sessao = r.session_id;
      pensando.textContent = r.response;
      if (r.dados_calculados) {
        const acoes = el("div", { class: "acoes" }, botaoPdf());
        pensando.append(acoes);
      }
    } catch (e) {
      pensando.className = "msg erro-msg"; pensando.textContent = e.message;
    } finally {
      estado.ocupado = false; $("botao-enviar").disabled = false;
      $("mensagens").scrollTop = $("mensagens").scrollHeight;
      $("texto").focus();
    }
  }

  /* ----------------------------------------------------------- documentos */
  function cartaoDocumento(d) {
    const raiz = el("div", { class: "doc" });
    const rotulo = d.nome_tipo || "Documento não identificado";
    const sev = (d.alertas || []).map((a) => a.severidade);
    const selo = d.falha ? el("span", { class: "selo erro", texto: "falhou" })
      : sev.includes("erro") ? el("span", { class: "selo erro", texto: "erro de conferência" })
      : d.requer_revisao || sev.includes("aviso") ? el("span", { class: "selo aviso", texto: "conferir" })
      : el("span", { class: "selo ok", texto: "ok" });
    raiz.append(el("h3", {}, rotulo, " ", selo));
    raiz.append(el("div", { class: "meta", texto: `${d.formato.toUpperCase()}${d.paginas ? ` · ${d.paginas} pág.` : ""} · confiança ${Math.round((d.confianca || 0) * 100)}% · SHA-256 ${d.sha256.slice(0, 12)}…` }));
    if (d.resumo) raiz.append(el("p", { texto: d.resumo }));
    const linhas = Object.entries(d.extracted_data || {}).filter(([, v]) => typeof v !== "object");
    if (linhas.length) {
      const tb = el("table");
      for (const [k, v] of linhas) {
        const valor = /^\d+\.\d{2}$/.test(String(v)) ? brl(v) : dataBr(String(v));
        tb.append(el("tr", {}, el("td", { texto: k.replaceAll("_", " ") }), el("td", { texto: valor })));
      }
      raiz.append(tb);
    }
    if ((d.alertas || []).length) {
      raiz.append(el("div", { class: "alertas" }, ...d.alertas.map((a) => el("div", { class: `alerta ${a.severidade}`, texto: a.mensagem }))));
    }
    if (d.falha) raiz.append(el("div", { class: "alerta erro", texto: d.falha }));
    if ((d.avisos || []).length) raiz.append(el("div", { class: "meta", texto: d.avisos.join(" ") }));
    if (d.audit_trail_id) raiz.append(el("div", { class: "meta", texto: `Trilha de auditoria: ${d.audit_trail_id}` }));
    return raiz;
  }

  async function enviarDocumento(arquivo) {
    if (!arquivo) return;
    adicionar("eu", `📎 ${arquivo.name}`);
    const m = adicionar("ela", el("span", { class: "digitando" }, el("i"), el("i"), el("i")));
    try {
      const form = new FormData();
      form.append("arquivo", arquivo);
      const d = await api("/api/v1/documentos", { metodo: "POST", form });
      m.replaceChildren(cartaoDocumento(d));
    } catch (e) {
      if (e.dados && e.dados.sha256) { m.replaceChildren(cartaoDocumento(e.dados)); }
      else { m.className = "msg erro-msg"; m.textContent = e.message; }
    } finally {
      $("arquivo").value = "";
      $("mensagens").scrollTop = $("mensagens").scrollHeight;
    }
  }

  /* --------------------------------------------------------------- painel */
  async function carregarPainel() {
    carregarPendentes();
    carregarConsentimento();
  }

  async function carregarPendentes() {
    const lista = $("lista-pendentes");
    try {
      const { pendentes } = await api("/api/v1/governanca/pendentes");
      if (!pendentes.length) { lista.replaceChildren(el("p", { class: "nota", texto: "Nenhuma decisão aguardando aprovação." })); return; }
      lista.replaceChildren(...pendentes.map((p) => {
        const resolver = (acao) => async (ev) => {
          ev.currentTarget.disabled = true;
          try { await api(`/api/v1/governanca/decisoes/${p.id}/${acao}`, { metodo: "POST", corpo: { comentario: "" } }); avisar(acao === "aprovar" ? "Decisão aprovada." : "Decisão rejeitada."); }
          catch (e) { avisar(e.message); }
          carregarPendentes();
        };
        return el("div", { class: "item" },
          el("strong", { texto: `${p.tipo} · ${brl(p.valor)}` }),
          el("span", { class: "nota", texto: `${p.descricao || "sem descrição"} · pedido por ${p.solicitante.slice(0, 12)}…` }),
          el("div", { class: "acoes" }, el("button", { class: "botao primario", type: "button", onclick: resolver("aprovar") }, "Aprovar"), el("button", { class: "botao", type: "button", onclick: resolver("rejeitar") }, "Rejeitar")));
      }));
    } catch (e) {
      lista.replaceChildren(el("p", { class: "nota", texto: e.status === 403 ? "Seu perfil não aprova decisões." : e.message }));
    }
  }

  async function carregarConsentimento() {
    const caixa = $("consentimento-ia");
    try {
      const { historico } = await api("/api/v1/lgpd/consentimentos");
      const ultimo = historico.filter((h) => h.finalidade === "envio_a_provedor_de_ia").pop();
      caixa.checked = !!(ultimo && ultimo.concedido);
    } catch (_) { caixa.checked = false; }
    caixa.disabled = !/tenant_admin|super_admin/.test((estado.usuario.roles || []).join(","));
  }

  async function alterarConsentimento(ev) {
    const caixa = ev.currentTarget, st = $("status-lgpd");
    try {
      await api("/api/v1/lgpd/consentimentos", { metodo: "POST", corpo: { finalidade: "envio_a_provedor_de_ia", concedido: caixa.checked } });
      st.className = "status ok"; st.textContent = caixa.checked ? "Consentimento registrado." : "Consentimento revogado.";
    } catch (e) { caixa.checked = !caixa.checked; st.className = "status falha"; st.textContent = e.message; }
  }

  async function acompanharJob(id) {
    const st = $("status-fgts");
    for (let i = 0; i < 400; i++) {
      const j = await api(`/api/v1/rpa/jobs/${id}`);
      const rotulos = { ENFILEIRADO: "Na fila…", EXECUTANDO: "Executando…", AGUARDANDO_HUMANO: j.mensagem || "Aguardando uma pessoa resolver o desafio na janela do navegador.", CONCLUIDO: "Concluído: extrato baixado e arquivado.", FALHOU: `Falhou: ${j.mensagem}` };
      st.className = `status ${j.estado === "CONCLUIDO" ? "ok" : j.estado === "FALHOU" ? "falha" : "espera"}`;
      st.textContent = rotulos[j.estado] || j.estado;
      if (j.estado === "CONCLUIDO" || j.estado === "FALHOU") return;
      await new Promise((r) => setTimeout(r, 2000));
    }
  }

  async function pedirExtrato(ev) {
    ev.preventDefault();
    const st = $("status-fgts"); st.className = "status"; st.textContent = "Enviando…";
    try {
      const r = await api("/api/v1/rpa/fgts", { metodo: "POST", corpo: { cpf: $("cpf-fgts").value } });
      $("cpf-fgts").value = "";
      await acompanharJob(r.job_id);
    } catch (e) { st.className = "status falha"; st.textContent = e.message; }
  }

  async function verificarAuditoria() {
    const st = $("status-auditoria"); st.className = "status"; st.textContent = "Verificando…";
    try {
      const r = await api("/api/v1/auditoria/verificar");
      st.className = `status ${r.ok ? "ok" : "falha"}`;
      st.textContent = r.ok ? `Íntegra: ${r.entradas} registro(s) encadeados.` : `ADULTERAÇÃO DETECTADA: ${r.problemas[0]}`;
    } catch (e) { st.className = "status falha"; st.textContent = e.status === 403 ? "Seu perfil não consulta a trilha de auditoria." : e.message; }
  }

  /* ---------------------------------------------------------------- abas */
  function trocarAba(nome) {
    for (const b of document.querySelectorAll(".aba")) { const ativa = b.dataset.aba === nome; b.classList.toggle("ativa", ativa); b.setAttribute("aria-selected", String(ativa)); }
    $("aba-chat").hidden = nome !== "chat"; $("aba-painel").hidden = nome !== "painel";
    if (nome === "painel") carregarPainel();
  }

  /* ----------------------------------------------------------------- init */
  function ajustarAltura() { const t = $("texto"); t.style.height = "auto"; t.style.height = `${Math.min(t.scrollHeight, 144)}px`; }

  function iniciar() {
    $("form-login").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const erro = $("erro-login"), botao = $("botao-entrar");
      erro.hidden = true; botao.disabled = true; botao.textContent = "Entrando…";
      try { await entrar($("usuario").value.trim(), $("senha").value); $("senha").value = ""; }
      catch (e) { erro.textContent = e.message; erro.hidden = false; }
      finally { botao.disabled = false; botao.textContent = "Entrar"; }
    });
    $("botao-sair").addEventListener("click", () => sair(true));
    $("form-chat").addEventListener("submit", (ev) => { ev.preventDefault(); const t = $("texto"); const v = t.value; t.value = ""; ajustarAltura(); enviar(v); });
    $("texto").addEventListener("input", ajustarAltura);
    $("texto").addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); $("form-chat").requestSubmit(); } });
    $("botao-anexo").addEventListener("click", () => $("arquivo").click());
    $("arquivo").addEventListener("change", (ev) => enviarDocumento(ev.target.files[0]));
    $("atalhos").addEventListener("click", (ev) => { const c = ev.target.closest(".chip"); if (c) enviar(c.dataset.texto); });
    for (const b of document.querySelectorAll(".aba")) b.addEventListener("click", () => trocarAba(b.dataset.aba));
    $("form-fgts").addEventListener("submit", pedirExtrato);
    $("consentimento-ia").addEventListener("change", alterarConsentimento);
    $("botao-auditoria").addEventListener("click", verificarAuditoria);

    const guardado = sessionStorage.getItem(CHAVE_TOKEN);
    if (guardado) { estado.token = guardado; carregarUsuario().catch(() => sair(false)); }
    else mostrarLogin();
  }

  iniciar();
})();
