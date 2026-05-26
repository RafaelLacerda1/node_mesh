// --- REFERENCIAS DOM ---
const nodesGrid = document.getElementById('nodes-grid');
const refreshBtn = document.getElementById('refresh-btn');
const refreshBtnText = document.getElementById('refresh-btn-text');
const refreshIcon = document.getElementById('refresh-icon');
const lastUpdatedEl = document.getElementById('last-updated');
const errorBanner = document.getElementById('error-banner');
const errorMessage = document.getElementById('error-message');
const selectAllCheckbox = document.getElementById('select-all-nodes');
const commandInput = document.getElementById('command-input');
const sendCommandBtn = document.getElementById('send-command-btn');
const logArea = document.getElementById('log-area');

// Modais
const passwordModalOverlay = document.getElementById('password-modal-overlay');
const passwordModal = document.getElementById('password-modal');
const passwordModalInput = document.getElementById('password-modal-input');
const passwordModalOk = document.getElementById('password-modal-ok');
const passwordModalCancel = document.getElementById('password-modal-cancel');
const passwordModalText = document.getElementById('password-modal-text');

const terminalModalOverlay = document.getElementById('terminal-modal-overlay');
const terminalIframe = document.getElementById('terminal-iframe');
const closeTerminalBtn = document.getElementById('close-terminal-btn');

let terminalCheckInterval = null;

// --- RENDERIZACAO ---
function renderNodes(nodes = []) {
    nodesGrid.innerHTML = '';

    if (nodes.length === 0) {
        // Skeleton Loading
        for (let i = 1; i <= 12; i++) {
            nodesGrid.innerHTML += `
                <div class="bg-white p-4 rounded-lg border border-slate-200 flex items-center justify-between animate-pulse h-[74px]">
                    <div class="flex items-center gap-3">
                        <div class="w-5 h-5 bg-slate-200 rounded"></div>
                        <div class="w-3 h-3 bg-slate-200 rounded-full"></div>
                        <div class="w-24 h-4 bg-slate-200 rounded"></div>
                    </div>
                </div>`;
        }
    } else {
        nodes.forEach(node => {
            const isOnline = node.online;
            const statusColor = isOnline ? 'bg-green-500' : 'bg-red-500';
            
            const btnClass = isOnline 
                ? 'bg-slate-50 hover:bg-blue-600 hover:text-white text-slate-600 border-slate-300 hover:border-blue-600 cursor-pointer' 
                : 'bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed opacity-60';
            
            const btnDisabledAttr = isOnline ? '' : 'disabled';
            const btnTitle = isOnline ? 'Abrir Terminal' : 'Terminal indisponível (Offline)';

            nodesGrid.innerHTML += `
                <div class="group bg-white p-4 rounded-lg border border-slate-200 shadow-sm hover:shadow-md transition-all duration-200 flex items-center justify-between h-[74px] ${isOnline ? 'hover:border-blue-300' : ''}">
                    <div class="flex items-center gap-3 min-w-0">
                        <div class="relative flex items-center justify-center">
                            <input type="checkbox" class="node-checkbox w-5 h-5 text-blue-600 rounded border-slate-300 focus:ring-blue-500 cursor-pointer peer transition-transform active:scale-90" 
                                   data-node-ip="${node.ip}" 
                                   data-node-name="${node.nome}">
                        </div>
                        <div class="flex items-center gap-2 min-w-0">
                            <span class="relative flex h-3 w-3">
                                ${isOnline ? '<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>' : ''}
                                <span class="relative inline-flex rounded-full h-3 w-3 ${statusColor}"></span>
                            </span>
                            <span class="font-bold text-slate-700 text-sm truncate" title="${node.nome}">
                                ${node.nome}
                            </span>
                        </div>
                    </div>
                    <button class="terminal-btn flex-shrink-0 ml-3 border text-xs font-semibold py-1.5 px-3 rounded transition-all flex items-center gap-1 ${btnClass}"
                            data-node-ip="${node.ip}"
                            title="${btnTitle}"
                            ${btnDisabledAttr}>
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                        Terminal
                    </button>
                </div>
            `;
        });
    }
}

// --- COMUNICACAO COM API ---
async function fetchStatus(isRefresh = false) {
    if(isRefresh) {
        setButtonState(true);
        renderNodes([]); 
    }
    updateErrorBanner(null);
    
    // Usa sempre /api/status. GET para load inicial, POST para forcar update.
    const url = '/api/status'; 
    const method = isRefresh ? 'POST' : 'GET';
    
    try {
        const response = await fetch(url, { method });
        
        if (response.status === 401) return window.location.href = '/login';

        // --- PROTECAO CONTRA HTML/ERRO 500 ---
        const contentType = response.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
            const text = await response.text();
            console.error("Erro do servidor (Não é JSON):", text);
            throw new Error(`Erro no servidor (${response.status}). Verifique os logs.`);
        }

        const data = await response.json();
        updateErrorBanner(data.error);
        
        if(data.nodes && data.nodes.length > 0) {
            renderNodes(data.nodes);
            updateLastUpdated();
        } else {
             if(!data.error) renderNodes([]);
        }
    } catch (error) {
        console.error("Falha no fetch:", error);
        updateErrorBanner('fetch_error');
        renderNodes([]);
    } finally {
        setButtonState(false);
    }
}

function setButtonState(isLoading) {
    refreshBtn.disabled = isLoading;
    refreshBtnText.textContent = isLoading ? 'Verificando...' : 'Reverificar';
    if (isLoading) refreshIcon.classList.add('animate-spin');
    else refreshIcon.classList.remove('animate-spin');
}

function updateErrorBanner(errorCode) {
    const msgs = {
        'ssh_failed': 'Falha na conexão SSH.',
        'ansible_timeout': 'Timeout: Rede lenta ou nó offline.',
        'fetch_error': 'Erro de conexão com o servidor ou dados inválidos.'
    };
    if (errorCode) {
        errorMessage.textContent = msgs[errorCode] || `Erro: ${errorCode}`;
        errorBanner.classList.remove('hidden');
    } else {
        errorBanner.classList.add('hidden');
    }
}

function updateLastUpdated() {
    lastUpdatedEl.textContent = `Atualizado às ${new Date().toLocaleTimeString()}`;
}

// --- FUNCOES DE SELECAO E COMANDO ---
function toggleSelectAll() {
    const isChecked = selectAllCheckbox.checked;
    document.querySelectorAll('.node-checkbox').forEach(cb => cb.checked = isChecked);
}

function updateSelectAllState() {
    const all = document.querySelectorAll('.node-checkbox');
    const checked = document.querySelectorAll('.node-checkbox:checked');
    if(all.length === 0) return;
    selectAllCheckbox.checked = (all.length === checked.length);
    selectAllCheckbox.indeterminate = (checked.length > 0 && checked.length < all.length);
}

async function enviarComando() {
    const command = commandInput.value.trim();
    const checked = document.querySelectorAll('.node-checkbox:checked');
    
    if (!command || checked.length === 0) return alert('Digite um comando e selecione nós.');
    
    logArea.innerHTML = `<div class="text-slate-400 border-b border-slate-700 pb-2 mb-2">🚀 Executando: <span class="text-white font-mono">${command}</span></div>` + logArea.innerHTML;
    sendCommandBtn.disabled = true;
    sendCommandBtn.textContent = 'Enviando...';
    
    const ips = Array.from(checked).map(cb => cb.getAttribute('data-node-ip'));
    
    try {
        const res = await fetch('/api/command', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ command, nodes: ips })
        });
        const results = await res.json();
        
        let outputHTML = '';
        results.forEach(r => {
            const color = r.success ? 'text-green-400' : 'text-red-400';
            const icon = r.success ? '✔' : '✖';
            outputHTML += `
                <div class="mb-4 font-mono text-xs">
                    <div class="${color} font-bold flex items-center gap-2">
                        ${icon} [${r.ip}] <span class="text-slate-500 text-[10px] ml-auto">Exit: ${r.exit_code}</span>
                    </div>
                    <div class="pl-4 border-l-2 border-slate-700 mt-1 text-slate-300">${r.stdout || r.stderr || '(Sem saída)'}</div>
                </div>`;
        });
        logArea.innerHTML = outputHTML + '<hr class="border-slate-700 my-4">' + logArea.innerHTML;
        
    } catch (e) {
        alert('Erro ao enviar comando.');
    } finally {
        sendCommandBtn.disabled = false;
        sendCommandBtn.textContent = 'Enviar Comando';
    }
}

// --- TERMINAL ---
function launchTerminalInModal(url) {
    terminalIframe.src = url;
    terminalModalOverlay.classList.remove('hidden');
    terminalModalOverlay.focus();

    if (terminalCheckInterval) clearInterval(terminalCheckInterval);

    setTimeout(() => {
        terminalCheckInterval = setInterval(() => {
            try {
                const currentUrl = terminalIframe.contentWindow.location.href;
                const currentTitle = terminalIframe.contentDocument.title;
                
                const isLoginUrl = !currentUrl.includes('hostname=');
                const isRootUrl = currentUrl.endsWith('/terminal/') || currentUrl.endsWith('/terminal');
                const isLoginTitle = currentTitle.includes('WebSSH Terminal') && !currentUrl.includes('hostname=');

                if (isLoginUrl || isRootUrl || isLoginTitle) {
                    closeTerminalModal();
                }
            } catch (e) {}
        }, 200); 
    }, 2000);
}

function closeTerminalModal() {
    if (terminalCheckInterval) clearInterval(terminalCheckInterval);
    terminalModalOverlay.classList.add('hidden');
    terminalIframe.src = '';
}

function openWebTerminal(nodeIp) {
    const info = document.body.dataset;
    const baseUrl = (typeof WEBSSH_URL_BASE !== 'undefined' && WEBSSH_URL_BASE) ? WEBSSH_URL_BASE : '/terminal/';
    
    if (info.isAdmin === 'true') {
        const url = `${baseUrl}?hostname=${nodeIp}&username=fitpath&password=Y2VmZXRtZw==`;
        launchTerminalInModal(url);
    } else {
        passwordModalText.textContent = `Senha para ${info.username} no nó ${nodeIp}:`;
        passwordModal.dataset.nodeIp = nodeIp;
        passwordModalOverlay.classList.remove('hidden');
        passwordModalInput.focus();
    }
}

async function handlePasswordModalOk() {
    const pwd = passwordModalInput.value;
    if(!pwd) return;
    
    const ip = passwordModal.dataset.nodeIp;
    const user = document.body.dataset.username;
    const baseUrl = (typeof WEBSSH_URL_BASE !== 'undefined' && WEBSSH_URL_BASE) ? WEBSSH_URL_BASE : '/terminal/';
    
    const originalText = passwordModalOk.textContent;
    passwordModalOk.textContent = 'Verificando...';
    passwordModalOk.disabled = true;

    try {
        const response = await fetch('/api/verify_password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pwd })
        });
        const data = await response.json();

        if (data.valid) {
            const b64 = btoa(pwd);
            const url = `${baseUrl}?hostname=${ip}&username=${user}&password=${b64}`;
            launchTerminalInModal(url);
            passwordModalOverlay.classList.add('hidden');
            passwordModalInput.value = '';
        } else {
            alert('Senha incorreta! Tente novamente.');
            passwordModalInput.value = '';
            passwordModalInput.focus();
        }
    } catch(e) { 
        alert('Erro de conexão ao verificar senha.'); 
    } finally {
        passwordModalOk.textContent = originalText;
        passwordModalOk.disabled = false;
    }
}

function initIdleTimer() {
    let idleTimer;
    const timeoutDuration = (typeof SESSION_TIMEOUT_MS !== 'undefined') ? SESSION_TIMEOUT_MS : 900000;
    function resetTimer() {
        clearTimeout(idleTimer);
        idleTimer = setTimeout(() => window.location.href = '/logout', timeoutDuration);
    }
    window.onload = resetTimer;
    document.onmousemove = resetTimer;
    document.onkeydown = resetTimer;
    document.onclick = resetTimer;
}

document.addEventListener('DOMContentLoaded', () => {
    refreshBtn.addEventListener('click', () => fetchStatus(true));
    selectAllCheckbox.addEventListener('change', toggleSelectAll);
    sendCommandBtn.addEventListener('click', enviarComando);
    
    nodesGrid.addEventListener('click', (e) => {
        const btn = e.target.closest('.terminal-btn');
        if(btn && !btn.disabled) openWebTerminal(btn.getAttribute('data-node-ip'));
    });
    
    nodesGrid.addEventListener('change', (e) => {
        if(e.target.classList.contains('node-checkbox')) updateSelectAllState();
    });
    
    closeTerminalBtn.addEventListener('click', closeTerminalModal);
    terminalModalOverlay.addEventListener('click', (e) => { if(e.target === terminalModalOverlay) closeTerminalModal(); });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (!terminalModalOverlay.classList.contains('hidden')) closeTerminalModal();
            if (!passwordModalOverlay.classList.contains('hidden')) passwordModalOverlay.classList.add('hidden');
        }
    });

    passwordModalOk.addEventListener('click', handlePasswordModalOk);
    passwordModalCancel.addEventListener('click', () => passwordModalOverlay.classList.add('hidden'));
    passwordModalInput.addEventListener('keydown', (e) => { if(e.key==='Enter') handlePasswordModalOk(); });
    
    initIdleTimer();
    fetchStatus(false);
});
