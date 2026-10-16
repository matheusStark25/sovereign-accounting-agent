/* Extracted from index_adapted.html - keep globals and public APIs unchanged */
// Avoid redeclaring `currentProfile` if it exists inline in the HTML.
if (typeof currentProfile === "undefined") currentProfile = "profissional";

// Declare key globals once at the top to avoid duplicate-declaration errors
// when `main.js` is included alongside inline scripts.
window.sessionId = window.sessionId || null;
window.isProcessing = window.isProcessing || false;
var sessionId = window.sessionId;
var isProcessing = window.isProcessing;
// Maintain an in-memory chat history to send to backend for context
window.chatHistory = window.chatHistory || [];

// Audio/recording globals
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let voiceModeEnabled = false;
let currentAudioElement = null;
let lastInputWasAudio = false;

// Gerar ou recuperar session ID
function getSessionId() {
    if (!sessionId) {
        sessionId = localStorage.getItem("rogio_session_id");
        if (!sessionId) {
            sessionId = generateUUID();
            localStorage.setItem("rogio_session_id", sessionId);
        }
    }
    return sessionId;
}

function generateUUID() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(
        /[xy]/g,
        function (c) {
            const r = (Math.random() * 16) | 0,
                v = c == "x" ? r : (r & 0x3) | 0x8;
            return v.toString(16);
        },
    );
}

function setProfile(profile) {
    document.body.className = profile;
    currentProfile = profile;

    // Atualizar controles visuais
    document.querySelectorAll(".profile-btn").forEach((btn) => {
        btn.classList.remove("active");
    });
    const profileBtn = document.querySelector(`.profile-btn.${profile}`);
    if (profileBtn) {
        profileBtn.classList.add("active");
    }

    // Personalizar conteúdo baseado no perfil
    updateContentForProfile(profile);

    // Feedback visual
    showToast(
        `Modo ${profile.charAt(0).toUpperCase() + profile.slice(1)} ativado!`,
    );
}

function updateContentForProfile(profile) {
    // Interface agora é fixa no perfil profissional
    // Esta função é mantida para compatibilidade futura
    console.log(`Perfil definido: ${profile}`);
}

// Show/hide chat helpers used by inline buttons and quick actions
function showChat() {
    try {
        const chatSection = document.getElementById('chat-section');
        if (chatSection) chatSection.style.display = '';
        const chatWidget = document.getElementById('chat-widget');
        if (chatWidget) chatWidget.classList.remove('hidden');
    } catch (e) {
        console.debug('showChat() failed:', e);
    }
}

function hideChat() {
    try {
        const chatSection = document.getElementById('chat-section');
        if (chatSection) chatSection.style.display = 'none';
        const chatWidget = document.getElementById('chat-widget');
        if (chatWidget) chatWidget.classList.add('hidden');
    } catch (e) {
        console.debug('hideChat() failed:', e);
    }
}

function sendQuickMessage(message) {
    // Guard: don't attempt to send an empty/invalid quick message
    try {
        if (message === null || typeof message === 'undefined' || String(message).trim() === '') {
            console.warn('sendQuickMessage called with empty/invalid message:', message);
            showToast('Ação inválida: mensagem vazia');
            return;
        }
    } catch (e) {
        console.debug('sendQuickMessage input validation failed', e);
        return;
    }

    showChat();
    setTimeout(() => {
        const input = document.getElementById("messageInput");
        if (input) {
            if (safeSetInputValue(input, message)) {
                sendMessage();
            } else {
                showToast('Ação inválida: mensagem vazia');
            }
        }
    }, 100);
}

function testarChat() {
    console.log("🧪 ========== TESTE DO CHAT ==========");
    alert("✅ PASSO 1: JavaScript ESTÁ FUNCIONANDO!");
    console.log("✅ PASSO 1: JavaScript OK");

    const input = document.getElementById("messageInput");
    if (!input) {
        alert("❌ PASSO 2: Campo de input NÃO ENCONTRADO!");
        console.error("❌ Campo messageInput não existe!");
        return;
    }
    alert("✅ PASSO 2: Campo de input ENCONTRADO!");
    console.log("✅ PASSO 2: Input encontrado:", input);

    safeSetInputValue(input, "Olá! Este é um teste automático.");
    alert("✅ PASSO 3: Mensagem inserida no campo!");
    console.log("✅ PASSO 3: Mensagem inserida");

    try {
        sendMessage();
        alert("✅ PASSO 5: sendMessage() executado! Aguarde a resposta...");
        console.log("✅ PASSO 5: Mensagem enviada com sucesso!");
    } catch (error) {
        alert("❌ ERRO ao enviar: " + error.message);
        console.error("❌ Erro:", error);
    }
}

async function sendMessage() {
    console.log("🚀 sendMessage() CHAMADA!");

    const chatSection = document.getElementById("chat-section");
    console.log("📍 Chat section encontrada:", chatSection);
    console.log("📍 Chat section display:", chatSection ? chatSection.style.display : "null");

    if (chatSection && chatSection.style.display === 'none') {
        console.warn("⚠️ Chat estava ESCONDIDO! Mostrando agora...");
        showChat();
        alert("⚠️ O chat estava escondido! Abrindo automaticamente...");
    }

    // Support either the main message input or the dashboard input (some pages
    // expose `dashboardMessageInput`). Prefer the visible/non-empty one.
    let input = document.getElementById("messageInput");
    const altInput = document.getElementById("dashboardMessageInput");
    if ((!input || !input.value || input.value.trim() === "") && altInput) {
        input = altInput;
    }
    console.log("📝 Input usado:", input && input.id);

    // Normalize input and treat literal strings 'undefined'/'null' as empty
    let rawMessage = (input && typeof input.value !== 'undefined') ? String(input.value) : "";
    rawMessage = rawMessage.trim();
    if (rawMessage.toLowerCase() === 'undefined' || rawMessage.toLowerCase() === 'null') rawMessage = '';
    const message = rawMessage;

    if (!message) {
        showToast("Por favor, digite uma mensagem!");
        return;
    }

    console.log("💬 Mensagem:", message);

    if (isProcessing) {
        console.warn("⚠️ Já processando outra mensagem!");
        return;
    }

    console.log("✅ Iniciando envio da mensagem...");

    addMessage(message, "user");
    input.value = "";
    isProcessing = true;

    // Disable send buttons to avoid duplicate submissions while processing
    const sendButtons = Array.from(document.querySelectorAll('button[onclick*="sendMessage"], button[onclick*="sendDashboardMessage"], button[onclick*="sendQuickMessage"]'));
    try {
        sendButtons.forEach((b) => {
            try {
                b.dataset._wasDisabled = b.disabled ? "1" : "0";
                b.disabled = true;
            } catch (e) {
                /* noop */
            }
        });
    } catch (e) {
        /* noop */
    }

    // Adicionar indicador visual de processamento e guardar o id para remoção posterior
    const processingId = addProcessingStatus();
    try {
        console.log("📡 Enviando para /api/chat...");

        // Ensure tenant/operator headers are sent to satisfy backend security checks.
        const tenantHeader = localStorage.getItem("X-Tenant-ID") || "PUBLIC";
        const operatorHeader = localStorage.getItem("X-Operator-ID") || "ANON";
        console.log("📎 Enviando headers:", { "X-Tenant-ID": tenantHeader, "X-Operator-ID": operatorHeader });

        // Robust fetch with timeout (30s) and automatic retry handling when
        // backend returns { status: 'retry' } (e.g., 429 or 401 translated by server).
        // Survival rule: backend returns 200 even on fallback, so perform a single attempt
        const maxRetries = 1;
        let attempt = 1;
        let data = null;
        while (attempt <= maxRetries) {
            // create abort controller for timeout
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s

            let response = null;
            try {
                response = await fetch("/api/chat", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json; charset=utf-8",
                        "X-Tenant-ID": tenantHeader,
                        "X-Operator-ID": operatorHeader,
                    },
                    body: JSON.stringify({
                        mensagem: message,
                        session_id: getSessionId(),
                        // send last ~30 messages for context
                        history: (window.chatHistory || []).slice(-30),
                    }),
                    signal: controller.signal,
                });
            } catch (err) {
                clearTimeout(timeoutId);
                console.warn(`Tentativa ${attempt} falhou ao conectar:`, err && err.name ? err.name : err);
                // If aborted due to timeout, treat as transient and retry
                if (attempt < maxRetries) {
                    await new Promise((r) => setTimeout(r, 1000));
                    attempt += 1;
                    continue;
                }
                throw err;
            }

            clearTimeout(timeoutId);

            try {
                if (!response.ok) {
                    // Non-JSON or non-OK responses are treated as errors; allow retry on 429/401
                    if ((response.status === 429 || response.status === 401) && attempt < maxRetries) {
                        console.warn(`Recebido ${response.status} — aguardando 2s e tentando novamente (${attempt}/${maxRetries})`);
                        await new Promise((r) => setTimeout(r, 2000));
                        attempt += 1;
                        continue;
                    }
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                data = await response.json().catch(() => null);
            } catch (err) {
                console.warn(`Erro ao processar resposta (tentativa ${attempt}):`, err && err.message ? err.message : err);
                if (attempt < maxRetries) {
                    await new Promise((r) => setTimeout(r, 1000));
                    attempt += 1;
                    continue;
                }
                throw err;
            }

            // If backend explicitly asks client to retry (status: 'retry'), then wait and retry
            if (data && data.status === 'retry' && attempt < maxRetries) {
                console.log(`Backend pediu retry — aguardando 1s antes de reenviar (tentativa ${attempt}/${maxRetries})`);
                await new Promise((r) => setTimeout(r, 1000));
                attempt += 1;
                continue;
            }

            // otherwise break the loop and continue processing `data`
            break;
        }
        console.log("✅ Dados parseados:", data);

        // Determine bot response text with fallbacks
        let botText = '';
        try {
            if (data && typeof data.resposta !== 'undefined' && data.resposta !== null && String(data.resposta).trim() !== '') {
                botText = String(data.resposta);
            } else if (data && data.status === 'retry') {
                // The server asked the client to retry but we've exhausted retries,
                // present a gentle message: however, don't surface the technical
                // 'indisponível' text; prefer a user-friendly note.
                botText = 'Estou com muita demanda agora, me dá um segundinho?';
            } else if (data && data.status === 'external_service_error') {
                botText = 'Desculpe, o serviço de inteligência está temporariamente indisponível. Tente novamente em alguns instantes.';
            } else if (data && data.erro) {
                botText = data.erro || 'Desculpe, ocorreu um erro ao gerar a resposta.';
            } else {
                botText = 'Desculpe, não consegui gerar uma resposta. Pode tentar novamente?';
            }
        } catch (e) {
            console.debug('Erro ao normalizar resposta do backend', e);
            botText = 'Desculpe, não consegui gerar uma resposta.';
        }

        console.log("🤖 Texto (final) que será exibido ao usuário:", botText);

        if (data.pensamento && currentProfile === "profissional") {
            addThinkingCard(data.pensamento);
        }

        const botMessageId = `msg_${Date.now()}`;
        const isErrorResponse = (data && data.status === 'external_service_error') || false;
        addMessage(botText, "bot", data && data.pdf_url ? data.pdf_url : null, isErrorResponse, botMessageId);

        if (voiceModeEnabled) {
            await speakResponse(botText);
        }

        detectContextAndSuggest(message, botText);

        if (data.session_id && data.session_id !== sessionId) {
            sessionId = data.session_id;
            localStorage.setItem("rogio_session_id", sessionId);
            console.log("✅ Session ID atualizado:", sessionId);
        }
    } catch (error) {
        console.error("Erro ao processar mensagem:", error);
        try { removeProcessingStatus(processingId); } catch (e) { /* noop */ }

        let errorMessage = "";
        switch (currentProfile) {
            case "rural":
                errorMessage =
                    "Desculpe, tivemos um problema ao processar sua solicitação. Por favor, tente novamente.";
                break;
            case "idoso":
                errorMessage =
                    "Ocorreu um erro. Não se preocupe, tente enviar sua mensagem novamente que vou ajudar.";
                break;
            default:
                errorMessage =
                    "Erro ao conectar com o servidor. Verifique sua conexão e tente novamente.";
        }

        addMessage(errorMessage, "bot", null, true);
    } finally {
        try { removeProcessingStatus(processingId); } catch (e) { /* noop */ }
        // Re-enable previously disabled send buttons
        try {
            sendButtons.forEach((b) => {
                try {
                    if (b && b.dataset && b.dataset._wasDisabled === "0") b.disabled = false;
                } catch (e) {
                    /* noop */
                }
            });
        } catch (e) {
            /* noop */
        }
        isProcessing = false;
    }
}

function addMessage(text, type, pdfUrl = null, isError = false, messageId = null) {
    // Normalize text to avoid showing literal 'undefined' or 'null' in the UI
    try {
        if (typeof text === 'undefined' || text === null) {
            text = '';
        }
    } catch (e) {
        text = '';
    }
    console.log("📨 addMessage() CHAMADA!", { text, type, pdfUrl, isError, messageId });

    const chatMessages = document.getElementById("chatMessages");
    console.log("📦 Container chatMessages:", chatMessages);

    if (!chatMessages) {
        console.error("❌ ERRO: Container chatMessages NÃO ENCONTRADO!");
        alert("❌ ERRO: Área de chat não encontrada! O elemento 'chatMessages' não existe no DOM.");
        return;
    }

    const messageDiv = document.createElement("div");
    messageDiv.className = `message ${type}`;
    if (messageId) messageDiv.dataset.messageId = messageId;

    let safe = escapeHTML(text || '');
    let formattedText = safe
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.*?)\*/g, "<em>$1</em>")
        .replace(/\n/g, "<br>");

    messageDiv.innerHTML = formattedText;
    console.log("✅ Mensagem criada:", messageDiv);

    if (isError) {
        messageDiv.style.borderLeft = "3px solid var(--danger)";
    }

    chatMessages.appendChild(messageDiv);
    console.log("✅ Mensagem ADICIONADA ao DOM! Total:", chatMessages.children.length);

    if (pdfUrl) {
        const pdfDiv = document.createElement("div");
        pdfDiv.className = "pdf-attachment";
        pdfDiv.innerHTML = `
            <div class="pdf-icon">📄</div>
            <div class="pdf-meta">
              <strong>Documento Oficial Gerado</strong>
              <span>Pronto para download</span>
            </div>
            <button class="btn-view" onclick="window.open('${pdfUrl}', '_blank')">
              Baixar PDF
            </button>
          `;
        messageDiv.appendChild(pdfDiv);
    }

    chatMessages.scrollTop = chatMessages.scrollHeight;
    console.log("🎯 Scroll ajustado. Altura:", chatMessages.scrollHeight);

    if (type === 'bot' && !isError) {
        setTimeout(() => {
            speakText(text);
        }, 500);
    }
    // Push into in-memory history for context (keep max 100 entries)
    try {
        window.chatHistory.push({ role: type === 'user' ? 'user' : 'assistant', content: String(text) });
        if (window.chatHistory.length > 100) window.chatHistory.shift();
    } catch (e) {
        /* noop */
    }
}

function addThinkingCard(pensamento) {
    const chatMessages = document.getElementById("chatMessages");
    const thinkingCard = document.createElement("div");
    thinkingCard.className = "status-card";
    thinkingCard.style.background = "rgba(45, 206, 137, 0.1)";
    thinkingCard.style.borderLeft = "3px solid var(--accent-green)";
    thinkingCard.innerHTML = `
        <div class="status-step">
          <div class="spinner"></div>
          ${pensamento}
        </div>
      `;
    chatMessages.appendChild(thinkingCard);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addProcessingStatus() {
    const chatMessages = document.getElementById("chatMessages");
    if (!chatMessages) return null;

    const statusId = "status-" + Date.now();
    const statusCard = document.createElement("div");
    statusCard.id = statusId;
    statusCard.className = "ai-thinking";
    statusCard.innerHTML = `
        <div style="font-size: 1.5rem; filter: drop-shadow(0 0 10px rgba(99, 102, 241, 0.6));">🧠</div>
        <div style="flex: 1;">
          <div style="font-weight: 600; color: var(--accent-neon); margin-bottom: 5px;">🤖 IA Pensando...</div>
          <div style="font-size: 0.9rem; color: var(--text-gray); margin-bottom: 8px;">Analisando sua pergunta e preparando resposta especializada</div>
          <div style="display: flex; gap: 10px; flex-wrap: wrap; font-size: 0.85rem; color: var(--text-muted);">
            <span>✓ Processando contexto</span>
            <span>✓ Consultando base de conhecimento</span>
            <span>✓ Gerando resposta</span>
          </div>
        </div>
        <div class="thinking-dots">
          <div class="thinking-dot"></div>
          <div class="thinking-dot"></div>
          <div class="thinking-dot"></div>
        </div>
      `;
    chatMessages.appendChild(statusCard);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return statusId;
}

function removeProcessingStatus(statusId) {
    const statusCard = document.getElementById(statusId);
    if (statusCard) {
        statusCard.remove();
    }
}

function escapeHTML(str) {
    return String(str).replace(/[&<>"']/g, function (s) {
        return ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        })[s];
    });
}

function showToast(message) {
    const toast = document.createElement("div");
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: var(--accent-green);
        color: white;
        padding: 12px 20px;
        border-radius: 8px;
        font-weight: 500;
        z-index: 1001;
        animation: slideIn 0.3s ease;
      `;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// Utility: safely set input value, rejecting literal 'undefined'/'null' or empty values
function safeSetInputValue(el, val) {
    try {
        if (!el) return false;
        if (val === null || typeof val === 'undefined') {
            console.warn('safeSetInputValue rejected null/undefined value');
            return false;
        }
        const s = String(val).trim();
        if (s === '' || s.toLowerCase() === 'undefined' || s.toLowerCase() === 'null') {
            console.warn('safeSetInputValue rejected empty/invalid string:', val);
            return false;
        }
        el.value = val;
        return true;
    } catch (e) {
        console.debug('safeSetInputValue error', e);
        return false;
    }
}

async function checkServerHealth() {
    // Prevent parallel health checks
    if (window.__healthCheckInProgress) {
        console.debug('Health check already in progress — skipping parallel call');
        return;
    }
    window.__healthCheckInProgress = true;

    // Backoff control: when server requests pause (429/401) we raise interval
    if (typeof window.__healthPauseUntil === 'number' && Date.now() < window.__healthPauseUntil) {
        console.debug('Health check paused until', new Date(window.__healthPauseUntil).toISOString());
        window.__healthCheckInProgress = false;
        return;
    }
    // Timeout + fallback health check to handle connection refused in some envs
    const tryFetchWithTimeout = async (url, ms = 3000) => {
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), ms);
        try {
            const resp = await fetch(url, { signal: controller.signal });
            clearTimeout(id);
            return resp;
        } catch (e) {
            clearTimeout(id);
            throw e;
        }
    };

    const statusElement = document.getElementById("connectionStatus");

    try {
        let response;
        try {
            // First try: relative path (works when frontend and backend are proxied)
            response = await tryFetchWithTimeout("/api/health", 2500);
        } catch (err) {
            // Fallback: try explicit local backend URL (common dev setup)
            try {
                response = await tryFetchWithTimeout("http://localhost:5000/api/health", 2500);
            } catch (err2) {
                // Both attempts failed
                throw err2 || err;
            }
        }

        if (!response) {
            throw new Error('Health endpoint returned no response');
        }

        // Handle rate-limit or unauthorized: immediately switch to a short retry (30s)
        if (response.status === 429 || response.status === 401) {
            // Immediate short backoff to avoid tight loop but allow quick recovery
            window.__healthBackoffMs = 30000; // 30 seconds
            window.__healthPauseUntil = Date.now() + window.__healthBackoffMs;
            console.warn('Health check received', response.status, '— setting short backoff 30s');
            throw new Error('Health endpoint rate limited or unauthorized (' + response.status + ')');
        }

        if (!response.ok) {
            const text = await response.text().catch(() => null);
            throw new Error(`Health endpoint error: ${response.status} ${text || ''}`);
        }

        // Ensure content-type is JSON before parsing
        const ct = response.headers.get('content-type') || '';
        let data = {};
        if (ct.toLowerCase().indexOf('application/json') !== -1) {
            data = await response.json().catch(() => ({}));
        } else {
            console.warn('Health endpoint returned non-JSON content-type:', ct);
        }
        console.log("💚 Health check:", data);

        if (statusElement) {
            if (data && data.status === "online") {
                statusElement.textContent = "Sistema Conectado ✓";
                statusElement.style.color = "#2dce89";
            } else {
                statusElement.textContent = "Conectado (sem status explícito)";
                statusElement.style.color = "#2dce89";
            }
        }
    } catch (error) {
        // Log reduzido para evitar poluição de console, mas com detalhe quando útil
        console.warn("❌ Health check falhou:", error && error.message ? error.message : error);
        // mark failure so finally can preserve backoff
        window.__lastHealthCheckFailed = true;

        if (statusElement) {
            statusElement.textContent = "Offline - Verifique a conexão com o backend";
            statusElement.style.color = "#ff4d4d";
        }
    }
    finally {
        // Schedule next run: on success reset backoff, on error schedule with current backoff
        try {
            if (!window.__healthBackoffMs) window.__healthBackoffMs = window.__healthBackoffBaseMs || 300000;
            // If last check succeeded, reset backoff
            if (!window.__lastHealthCheckFailed) {
                window.__healthBackoffMs = window.__healthBackoffBaseMs;
            }
        } catch (e) { }
        scheduleNextHealthCheck(window.__healthBackoffMs);
        // reset transient flag and clear in-progress
        window.__lastHealthCheckFailed = false;
        window.__healthCheckInProgress = false;
    }
}

console.log("📋 Session ID:", getSessionId());

setProfile("profissional");

// Hide TTS retries and telemetry from the UI for production stability,
// keep telemetry only in developer logs.
try {
    const ttsElem = document.getElementById('ttsSettings');
    if (ttsElem) {
        ttsElem.style.display = 'none';
        console.debug('TTS settings hidden from UI for stability');
    }
    const telemetryCheckbox = document.getElementById('ttsTelemetryCheckbox');
    if (telemetryCheckbox) {
        telemetryCheckbox.checked = false;
    }
    const retriesInput = document.getElementById('ttsRetriesInput');
    if (retriesInput) retriesInput.value = '';
} catch (e) {
    console.debug('Could not hide TTS UI elements:', e);
}

// Health check backoff configuration
if (!window.__healthBackoffMs) window.__healthBackoffMs = 300000; // 5 minutes
if (!window.__healthBackoffBaseMs) window.__healthBackoffBaseMs = 300000;
if (!window.__healthBackoffMaxMs) window.__healthBackoffMaxMs = 15 * 60 * 1000; // 15 minutes max

function scheduleNextHealthCheck(delayMs) {
    try {
        if (window.__healthCheckTimer) {
            clearTimeout(window.__healthCheckTimer);
        }
        window.__healthCheckTimer = setTimeout(() => {
            checkServerHealth();
        }, delayMs);
    } catch (e) {
        // ignore scheduling errors
    }
}

// start the loop using scheduling (exponential backoff applied on errors)
scheduleNextHealthCheck(window.__healthBackoffMs);

function quickAction(action, element) {
    const actionMessages = {
        'dp': '📂 Preciso calcular férias de um funcionário com 1 ano de trabalho, salário R$ 3.000',
        'rescisao': '💼 Como calcular rescisão trabalhista completa? Preciso de um exemplo prático.',
        'fiscal': '📊 Quais são os principais impostos para uma empresa no Simples Nacional?',
        'inss': '🏥 Como calcular INSS e IRRF sobre folha de pagamento?',
        'documento': '📄 Preciso gerar um documento formal com cálculos contábeis',
        'limpar': null,
        'ajuda': '❓ Como você pode me ajudar? Quais são suas principais funcionalidades?'
    };

    if (element) {
        element.style.transform = 'scale(0.95)';
        setTimeout(() => {
            element.style.transform = 'scale(1)';
        }, 150);
    }

    if (action === 'limpar') {
        if (confirm('Deseja realmente limpar toda a conversa?')) {
            const chatMessages = document.getElementById('chatMessages');
            if (chatMessages) {
                chatMessages.innerHTML = '';
            }
            localStorage.removeItem('rogio_session_id');
            sessionId = null;
            showToast('🗑️ Conversa limpa! Nova sessão iniciada.');
            location.reload();
        }
        return;
    }

    const message = actionMessages[action];
    if (message) {
        showChat();
        setTimeout(() => {
            const input = document.getElementById("messageInput");
            if (input) {
                if (safeSetInputValue(input, message)) {
                    sendMessage();
                    showToast(`✅ Ação selecionada: ${element?.textContent?.trim() || action}`);
                } else {
                    showToast('Ação inválida: mensagem vazia');
                }
            }
        }, 500);
    } else {
        console.error('Ação não encontrada:', action);
    }
}

function rateBotResponse(messageId, rating, button) {
    button.style.transform = 'scale(1.2)';
    setTimeout(() => {
        button.style.transform = 'scale(1)';
    }, 200);

    const feedbackBtns = button.parentElement.querySelectorAll('.feedback-btn');
    feedbackBtns.forEach(btn => {
        btn.classList.remove('liked', 'disliked');
    });

    if (rating === 'like') {
        button.classList.add('liked');
        showToast('✅ Obrigado pelo feedback positivo!');
        console.log(`👍 Mensagem ${messageId} avaliada positivamente`);
    } else {
        button.classList.add('disliked');
        showToast('Vou tentar melhorar! Pode pedir mais detalhes.');
        console.log(`👎 Mensagem ${messageId} avaliada negativamente`);

        setTimeout(() => {
            const input = document.getElementById("messageInput");
            input.placeholder = "Como posso melhorar a resposta anterior?";
            input.focus();
        }, 1500);
    }
}

function requestMoreDetails(messageId) {
    showToast('📝 Solicitando mais detalhes...');
    const message = "Pode me dar mais detalhes sobre sua última resposta? Preciso entender melhor.";
    const inp = document.getElementById("messageInput");
    if (safeSetInputValue(inp, message)) {
        setTimeout(() => sendMessage(), 500);
    } else {
        showToast('Não foi possível preparar a solicitação de detalhes.');
    }
}

function addSuggestions(suggestions) {
    const chatMessages = document.getElementById("chatMessages");
    const suggestionsBox = document.createElement("div");
    suggestionsBox.className = "suggestions-box";

    let suggestionsHTML = '<div class="suggestion-title">💡 Sugestões para você:</div><div class="suggestion-items">';

    suggestions.forEach(suggestion => {
        suggestionsHTML += `
          <div class="suggestion-item" onclick="applySuggestion('${suggestion}')">
            ${suggestion}
          </div>
        `;
    });

    suggestionsHTML += '</div>';
    suggestionsBox.innerHTML = suggestionsHTML;

    chatMessages.appendChild(suggestionsBox);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function applySuggestion(suggestion) {
    const inp = document.getElementById("messageInput");
    if (safeSetInputValue(inp, suggestion)) {
        showToast('💡 Sugestão aplicada!');
        setTimeout(() => sendMessage(), 300);
    } else {
        console.warn('applySuggestion rejected invalid suggestion:', suggestion);
        showToast('Sugestão inválida');
    }
}

function detectContextAndSuggest(userMessage, botResponse) {
    // Defensive: ensure inputs are strings to avoid "cannot read properties of undefined"
    try {
        const u = (typeof userMessage === 'string' ? userMessage : String(userMessage || '')).toLowerCase();
        const b = (typeof botResponse === 'string' ? botResponse : String(botResponse || '')).toLowerCase();

        const suggestions = [];

        if (b.includes('férias') || u.includes('férias')) {
            suggestions.push('Calcular 13º salário proporcional');
            suggestions.push('Quanto é 1/3 de férias?');
            suggestions.push('Gerar documento de concessão de férias');
        }

        if (b.includes('rescisão') || u.includes('rescisão')) {
            suggestions.push('Calcular aviso prévio indenizado');
            suggestions.push('Multa FGTS 40%');
            suggestions.push('Gerar termo de rescisão em PDF');
        }

        if (b.includes('imposto') || b.includes('tributo') || u.includes('imposto') || u.includes('tributo')) {
            suggestions.push('Como reduzir carga tributária?');
            suggestions.push('Comparar Simples vs Lucro Presumido');
            suggestions.push('Calcular economia fiscal');
        }

        if (b.includes('salário') || b.includes('salario') || b.includes('folha') || u.includes('salário') || u.includes('salario') || u.includes('folha')) {
            suggestions.push('Calcular horas extras');
            suggestions.push('Adicional noturno');
            suggestions.push('Descontos obrigatórios');
        }

        if (suggestions.length > 0) {
            setTimeout(() => addSuggestions(suggestions), 1000);
        }
    } catch (e) {
        console.debug('detectContextAndSuggest skipped due to unexpected input', e);
    }
}

// Health checks scheduled via scheduleNextHealthCheck — no global setInterval

const _msgInputEl = document.getElementById("messageInput");
if (_msgInputEl && !_msgInputEl.dataset.enterBound) {
    _msgInputEl.addEventListener("keypress", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    _msgInputEl.dataset.enterBound = "1";
}

getSessionId();

console.log("✅ Interface pronta para uso!");
console.log("💡 Dica: Abra DevTools (F12) para ver logs de debug");

async function toggleAudioRecording() {
    const audioBtn = document.getElementById('audioBtn');
    const indicator = document.getElementById('recordingIndicator');

    if (!isRecording) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = (event) => {
                audioChunks.push(event.data);
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                await sendAudioToBackend(audioBlob);
                stream.getTracks().forEach(track => track.stop());
            };

            mediaRecorder.start();
            isRecording = true;
            indicator.style.display = 'block';
            audioBtn.style.color = 'red';
            showToast('🎤 Gravando... Clique novamente para parar');
        } catch (error) {
            console.error('Erro ao acessar microfone:', error);
            showToast('❌ Erro ao acessar microfone. Permita o acesso.');
        }
    } else {
        mediaRecorder.stop();
        isRecording = false;
        indicator.style.display = 'none';
        audioBtn.style.color = '';
        showToast('⏹️ Processando áudio...');
    }
}

async function sendAudioToBackend(audioBlob) {
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');
    formData.append('session_id', getSessionId());

    try {
        const response = await fetch('/api/transcribe', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.texto_transcrito) {
            const inp = document.getElementById('messageInput');
            if (safeSetInputValue(inp, data.texto_transcrito)) {
                // Auto-send valid transcriptions to improve UX when recording audio
                lastInputWasAudio = true;
                showToast('✅ Áudio transcrito e enviado!');
                setTimeout(() => {
                    try { sendMessage(); } catch (e) { console.debug('auto-send failed', e); }
                    lastInputWasAudio = false;
                }, 350);
            } else {
                showToast('❌ Transcrição inválida');
            }
        } else {
            showToast('❌ Não consegui entender o áudio');
        }
    } catch (error) {
        console.error('Erro ao transcrever áudio:', error);
        showToast('❌ Erro ao processar áudio');
    }
}

// NOTE: rest of functions preserved in main.js to keep parity with original behavior

// Simple, safe TTS wrappers — no-op when voice mode is disabled or unavailable.
function speakText(text) {
    try {
        if (!voiceModeEnabled) return;
        if (typeof text !== 'string') text = String(text || '');
        if (!('speechSynthesis' in window)) return;
        // Cancel any existing utterances to avoid overlaps
        try { window.speechSynthesis.cancel(); } catch (e) { /* noop */ }
        const utter = new SpeechSynthesisUtterance(text);
        utter.lang = 'pt-BR';
        // Lightweight error handling: don't throw to UI
        try { window.speechSynthesis.speak(utter); } catch (e) { console.debug('TTS speak failed', e); }
    } catch (e) {
        // swallow to avoid breaking UI when TTS is unavailable
        console.debug('speakText() error:', e);
    }
}

// Async wrapper used by sendMessage() for compatibility with previous implementations
async function speakResponse(text) {
    try {
        // keep compatibility: simply call speakText synchronously
        speakText(text);
    } catch (e) {
        console.debug('speakResponse() error:', e);
    }
}
