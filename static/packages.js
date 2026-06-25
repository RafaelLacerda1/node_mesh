// --- Integracao da tela de instalacao de pacotes (templates/packages.html) ---
// Arquivo isolado de static/script.js de proposito: nao compartilha estado nem
// elementos DOM com o dashboard principal, eliminando risco de regressao la.
(function () {
    'use strict';

    const POLL_INTERVAL_MS = 3000;
    const FINAL_STATUSES = ['completed', 'completed_partial', 'failed', 'error'];
    const JOBS_PAGE_SIZE = 10;

    const nodesGrid = document.getElementById('packages-nodes-grid');
    const selectAllCheckbox = document.getElementById('select-all-packages-nodes');
    const packageNameInput = document.getElementById('package-name-input');
    const validateBtn = document.getElementById('validate-package-btn');
    const installBtn = document.getElementById('install-package-btn');
    const resultBox = document.getElementById('install-form-result');
    const cacheInfo = document.getElementById('packages-cache-info');
    const jobsTableBody = document.getElementById('packages-jobs-table-body');
    const jobsPaginationInfo = document.getElementById('packages-jobs-pagination-info');
    const jobsPrevBtn = document.getElementById('packages-jobs-prev-btn');
    const jobsNextBtn = document.getElementById('packages-jobs-next-btn');

    let pollTimer = null;
    let jobsOffset = 0;

    // --- HELPERS ---
    function formatDateTime(isoString) {
        if (!isoString) return '—';
        return new Date(isoString).toLocaleString('pt-BR');
    }

    async function apiFetch(url, options) {
        const res = await fetch(url, options);
        if (res.status === 401) {
            window.location.href = '/login';
            throw new Error('not_authenticated');
        }
        const contentType = res.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            throw new Error(`Resposta inesperada do servidor (${res.status}).`);
        }
        const data = await res.json();
        return { ok: res.ok, status: res.status, data };
    }

    function showResult(html, kind) {
        const colors = { info: 'text-slate-600', success: 'text-green-600', error: 'text-red-600' };
        resultBox.className = `mt-4 text-sm ${colors[kind] || colors.info}`;
        resultBox.innerHTML = html;
        resultBox.classList.remove('hidden');
    }

    function jobStatusBadge(status) {
        const map = {
            completed: 'bg-green-100 text-green-700',
            completed_partial: 'bg-amber-100 text-amber-700',
            failed: 'bg-red-100 text-red-700',
            error: 'bg-red-100 text-red-700',
            success: 'bg-green-100 text-green-700',
            offline: 'bg-slate-200 text-slate-600',
            skipped: 'bg-slate-200 text-slate-600',
        };
        const cls = map[status] || 'bg-blue-100 text-blue-700';
        return `<span class="text-xs font-bold px-2 py-1 rounded-full ${cls}">${status}</span>`;
    }

    // --- NOS DISPONIVEIS ---
    function renderNodes(nodes) {
        if (!nodes.length) {
            nodesGrid.innerHTML = '<p class="text-sm text-slate-400 col-span-full">Nenhum nó online disponível.</p>';
            return;
        }
        nodesGrid.innerHTML = nodes.map(n => `
            <label class="flex items-center gap-2 p-2 border border-slate-200 rounded-lg hover:bg-slate-50 cursor-pointer">
                <input type="checkbox" class="packages-node-checkbox w-4 h-4 text-primary border-gray-300 rounded focus:ring-primary"
                       data-node-ip="${n.ip}">
                <span class="text-sm text-slate-700 truncate">${n.nome}</span>
                <span class="text-xs text-slate-400 font-mono ml-auto">${n.ip}</span>
            </label>
        `).join('');
    }

    async function loadNodes() {
        try {
            const { data } = await apiFetch('/api/packages/nodes');
            renderNodes(data.nodes || []);
        } catch (e) {
            nodesGrid.innerHTML = '<p class="text-sm text-red-500 col-span-full">Erro ao carregar nós.</p>';
        }
    }

    function toggleSelectAllNodes() {
        document.querySelectorAll('.packages-node-checkbox').forEach(cb => { cb.checked = selectAllCheckbox.checked; });
    }

    function getSelectedNodeIps() {
        return Array.from(document.querySelectorAll('.packages-node-checkbox:checked')).map(cb => cb.getAttribute('data-node-ip'));
    }

    // --- CACHE ---
    function renderCache(info) {
        cacheInfo.innerHTML = `
            <div class="flex items-center justify-between"><span>Pacotes em cache</span><span class="font-mono font-semibold text-slate-800">${info.total_packages}</span></div>
            <div class="flex items-center justify-between"><span>Tamanho total</span><span class="font-mono font-semibold text-slate-800">${info.total_size_mb} MB</span></div>
            <div class="flex items-center justify-between"><span>Última atualização</span><span class="font-mono text-xs text-slate-500">${formatDateTime(info.last_updated)}</span></div>
        `;
    }

    async function loadCache() {
        try {
            const { data } = await apiFetch('/api/packages/cache');
            renderCache(data);
        } catch (e) {
            cacheInfo.innerHTML = '<p class="text-red-500">Erro ao carregar informações de cache.</p>';
        }
    }

    // --- JOBS (LISTAGEM + PAGINACAO) ---
    function renderJobs(jobs) {
        if (!jobs.length) {
            jobsTableBody.innerHTML = '<tr><td colspan="5" class="px-6 py-8 text-center text-slate-400">Nenhum job de instalação ainda.</td></tr>';
            return;
        }
        jobsTableBody.innerHTML = jobs.map(j => `
            <tr class="hover:bg-slate-50">
                <td class="px-6 py-3">${jobStatusBadge(j.status)}</td>
                <td class="px-6 py-3 font-mono text-slate-700">${j.package_name}</td>
                <td class="px-6 py-3 text-slate-500 text-xs">${j.requested_by}</td>
                <td class="px-6 py-3 text-xs text-slate-500" title="Sucesso/Falha/Offline/Incompatível">
                    ${j.success_nodes}/${j.failed_nodes}/${j.offline_nodes}/${j.skipped_nodes}
                </td>
                <td class="px-6 py-3 text-xs text-slate-500">${formatDateTime(j.created_at)}</td>
            </tr>
        `).join('');
    }

    async function loadJobs() {
        try {
            const { data } = await apiFetch(`/api/packages/jobs?limit=${JOBS_PAGE_SIZE}&offset=${jobsOffset}`);
            renderJobs(data.jobs || []);

            const total = data.total || 0;
            const start = total === 0 ? 0 : jobsOffset + 1;
            const end = Math.min(jobsOffset + JOBS_PAGE_SIZE, total);
            jobsPaginationInfo.textContent = `Mostrando ${start}-${end} de ${total}`;

            jobsPrevBtn.disabled = jobsOffset === 0;
            jobsNextBtn.disabled = jobsOffset + JOBS_PAGE_SIZE >= total;
        } catch (e) {
            jobsTableBody.innerHTML = '<tr><td colspan="5" class="px-6 py-8 text-center text-red-400">Erro ao carregar jobs.</td></tr>';
        }
    }

    function goToPrevJobsPage() {
        jobsOffset = Math.max(0, jobsOffset - JOBS_PAGE_SIZE);
        loadJobs();
    }

    function goToNextJobsPage() {
        jobsOffset += JOBS_PAGE_SIZE;
        loadJobs();
    }

    // --- VALIDAR PACOTE ---
    async function validatePackage() {
        const name = packageNameInput.value.trim();
        if (!name) {
            showResult('Digite o nome do pacote antes de validar.', 'error');
            return;
        }

        const original = validateBtn.textContent;
        validateBtn.disabled = true;
        validateBtn.textContent = 'Validando...';

        try {
            const { data } = await apiFetch('/api/packages/validate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package_name: name })
            });

            if (data.exists) {
                const versionTxt = data.version ? `, versão ${data.version}` : '';
                const descTxt = data.description ? ` — ${data.description}` : '';
                showResult(`✓ Pacote encontrado (${data.type}${versionTxt})${descTxt}`, 'success');
            } else {
                showResult(`✗ Pacote "${data.name}" não encontrado nos repositórios Debian arm64 nem no catálogo externo.`, 'error');
            }
        } catch (e) {
            showResult('Erro de conexão ao validar pacote.', 'error');
        } finally {
            validateBtn.disabled = false;
            validateBtn.textContent = original;
        }
    }

    // --- INSTALAR ---
    async function installPackage() {
        const name = packageNameInput.value.trim();
        const ips = getSelectedNodeIps();

        if (!name) {
            showResult('Digite o nome do pacote.', 'error');
            return;
        }
        if (!ips.length) {
            showResult('Selecione pelo menos um nó.', 'error');
            return;
        }

        const original = installBtn.textContent;
        installBtn.disabled = true;
        validateBtn.disabled = true;
        installBtn.textContent = 'Iniciando...';

        try {
            const { data, status } = await apiFetch('/api/packages/install', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package_name: name, nodes: ips })
            });

            if (status === 202 && data.success) {
                showResult(`Job #${data.job_id} iniciado. Acompanhando status...`, 'info');
                startPolling(data.job_id);
                return; // mantem os botoes desabilitados ate o job finalizar
            }
            if (status === 409) {
                showResult(`Já existe um job de instalação em andamento (#${data.current_job_id}). Aguarde finalizar.`, 'error');
            } else if (status === 403) {
                showResult(data.message || 'Instalação de pacotes está desabilitada (PACKAGES_ENABLED=false).', 'error');
            } else {
                showResult(data.message || 'Erro ao iniciar a instalação.', 'error');
            }
        } catch (e) {
            showResult('Erro de conexão ao iniciar a instalação.', 'error');
        } finally {
            // so reabilita aqui se NAO entramos em polling (early return acima cobre o caso de sucesso)
            installBtn.disabled = false;
            validateBtn.disabled = false;
            installBtn.textContent = original;
        }
    }

    // --- POLLING DE STATUS DO JOB ---
    function renderJobProgress(job) {
        const nodeRows = (job.nodes || []).map(n => `
            <div class="flex items-center justify-between text-xs py-1 border-b border-slate-100 last:border-0">
                <span class="font-mono text-slate-600">${n.node_ip}</span>
                ${jobStatusBadge(n.status)}
            </div>
        `).join('');

        showResult(`
            <div class="flex items-center justify-between mb-2">
                <span>Job #${job.id} — <strong>${job.package_name}</strong></span>
                ${jobStatusBadge(job.status)}
            </div>
            <div class="text-xs text-slate-500 mb-2">
                Sucesso: ${job.success_nodes} · Falha: ${job.failed_nodes} · Offline: ${job.offline_nodes} · Incompatíveis: ${job.skipped_nodes}
            </div>
            <div class="max-h-40 overflow-y-auto">${nodeRows}</div>
        `, 'info');
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function startPolling(jobId) {
        stopPolling();

        async function poll() {
            try {
                const { data } = await apiFetch(`/api/packages/jobs/${jobId}`);
                renderJobProgress(data);

                if (FINAL_STATUSES.includes(data.status)) {
                    stopPolling();
                    installBtn.disabled = false;
                    validateBtn.disabled = false;
                    jobsOffset = 0;
                    loadJobs();
                    loadCache();
                }
            } catch (e) {
                stopPolling();
                installBtn.disabled = false;
                validateBtn.disabled = false;
            }
        }

        poll();
        pollTimer = setInterval(poll, POLL_INTERVAL_MS);
    }

    // --- INICIALIZACAO ---
    document.addEventListener('DOMContentLoaded', () => {
        selectAllCheckbox.addEventListener('change', toggleSelectAllNodes);
        validateBtn.addEventListener('click', validatePackage);
        installBtn.addEventListener('click', installPackage);
        jobsPrevBtn.addEventListener('click', goToPrevJobsPage);
        jobsNextBtn.addEventListener('click', goToNextJobsPage);

        loadNodes();
        loadCache();
        loadJobs();
    });
})();
