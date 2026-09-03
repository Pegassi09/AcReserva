const state = {
  access: null,
  sectorId: null,
  sectors: [],
  rooms: [],
  user: JSON.parse(sessionStorage.getItem('acReservaUser') || 'null'),
  token: sessionStorage.getItem('acReservaToken'),
};
const activeToasts = new Set();
let setupCheckInFlight = false;

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value = '') => String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[char]));

function toast(message, type = 'error') {
  const key = `${type}:${message}`;
  if (activeToasts.has(key)) return;
  activeToasts.add(key);
  const item = document.createElement('div');
  item.className = `toast ${type}`;
  item.textContent = message;
  $('#toast-region').append(item);
  window.setTimeout(() => { item.remove(); activeToasts.delete(key); }, 5500);
}

async function api(path, options = {}) {
  const headers = {...(options.body ? {'Content-Type':'application/json'} : {}), ...(options.headers || {})};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  let response;
  try {
    response = await fetch(path, {...options, headers});
  } catch {
    throw new Error('Não foi possível conectar ao servidor. Tente novamente em instantes.');
  }
  const raw = await response.text();
  let payload = {};
  try { payload = raw ? JSON.parse(raw) : {}; } catch { /* A plataforma pode retornar HTML para erros de Function. */ }
  if (!response.ok) {
    if (response.status === 401 && state.token) logout(false);
    const message = payload.error?.message
      || (response.status >= 500
        ? `A API da Vercel não respondeu corretamente (erro ${response.status}). Confirme MONGODB_URI e JWT_SECRET e consulte os logs da Function.`
        : `Não foi possível concluir a operação (erro ${response.status}).`);
    throw new Error(message);
  }
  return payload;
}

function setScreen(name) {
  $('#welcome-screen').classList.toggle('hidden', name !== 'welcome');
  $('#login-screen').classList.toggle('hidden', name !== 'login');
  $('#app-screen').classList.toggle('hidden', name !== 'app');
}

function showLogin(access, sectorId = null) {
  state.access = access;
  state.sectorId = sectorId;
  setScreen('login');
  $('#sector-picker').classList.add('hidden');
  $('#external-access').classList.add('hidden');
  $('#setup-form').classList.add('hidden');
  $('#login-form').classList.remove('hidden');
  $('#login-identifier-wrap').classList.toggle('hidden', access !== 'associate');
  $('#login-eyebrow').textContent = access === 'associate' ? 'ÁREA DO ASSOCIADO' : 'ACESSO INTERNO';
  $('#login-title').textContent = access === 'associate' ? 'Entre na sua conta' : 'Acesse o ambiente ACIM';
  $('#login-description').textContent = access === 'associate'
    ? 'Informe os dados vinculados ao cadastro da sua empresa.'
    : 'Use seu e-mail institucional e senha para continuar.';
  $('#login-email').focus();
}

async function showAcimSectors() {
  state.access = 'acim';
  setScreen('login');
  $('#login-form').classList.add('hidden');
  $('#external-access').classList.add('hidden');
  $('#setup-form').classList.add('hidden');
  $('#sector-picker').classList.remove('hidden');
  const list = $('#sector-list');
  list.innerHTML = '<div class="empty-state">Carregando setores autorizados…</div>';
  try {
    const {data} = await api('/api/public/sectors');
    state.sectors = data;
    renderSectors();
  } catch (error) {
    list.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}<br><br>Após corrigir a configuração, tente novamente.</div><button type="button" data-sector=""><span>Acesso administrativo</span><span aria-hidden="true">→</span></button>`;
  }
}

function renderSectors() {
  const filter = $('#sector-search').value.trim().toLocaleLowerCase('pt-BR');
  const sectors = state.sectors.filter(sector => sector.name.toLocaleLowerCase('pt-BR').includes(filter));
  const sectorButtons = sectors.map(sector => `<button type="button" data-sector="${sector.id}"><span>${escapeHtml(sector.name)}</span><span aria-hidden="true">→</span></button>`).join('');
  const empty = sectors.length ? '' : '<div class="empty-state">Nenhum setor cadastrado ainda.</div>';
  $('#sector-list').innerHTML = `${sectorButtons}${empty}<button type="button" data-sector=""><span>Acesso administrativo</span><span aria-hidden="true">→</span></button>`;
}

async function showFirstAccess() {
  if (setupCheckInFlight) return;
  setupCheckInFlight = true;
  try {
    const {data} = await api('/api/setup/status');
    if (!data.configuration_ready) {
      toast(data.configuration_message || 'A API ainda não foi configurada na Vercel.');
      return;
    }
    if (!data.needs_setup) {
      toast('A configuração inicial já foi concluída. Use seu e-mail e senha para entrar.');
      return;
    }
    state.access = 'acim';
    state.sectorId = null;
    setScreen('login');
    $('#sector-picker').classList.add('hidden');
    $('#login-form').classList.add('hidden');
    $('#external-access').classList.add('hidden');
    $('#setup-form').classList.remove('hidden');
    $('#setup-name').focus();
  } catch (error) {
    toast(error.message);
  } finally {
    setupCheckInFlight = false;
  }
}

function showExternal() {
  state.access = 'external';
  setScreen('login');
  $('#login-form').classList.add('hidden');
  $('#sector-picker').classList.add('hidden');
  $('#setup-form').classList.add('hidden');
  $('#external-access').classList.remove('hidden');
}

function role() {
  const roles = state.user?.roles || [];
  if (roles.includes('admin')) return 'admin';
  if (roles.includes('reception')) return 'reception';
  if (roles.includes('it')) return 'it';
  if (roles.includes('operational')) return 'operational';
  return 'associate';
}

const navByRole = {
  associate: [['home','⌂','Início'],['reservations','▣','Minhas reservas'],['new','＋','Agendar reserva'],['calendar','◫','Calendário'],['profile','◉','Meu perfil']],
  reception: [['home','⌂','Agenda de hoje'],['reservations','▣','Reservas'],['calendar','◫','Calendário'],['preparation','✓','Preparação das salas'],['profile','◉','Meu perfil']],
  it: [['home','⌂','Solicitações de TI'],['reservations','▣','Reservas com TI'],['equipment','◈','Equipamentos'],['calendar','◫','Agenda técnica'],['profile','◉','Meu perfil']],
  operational: [['home','⌂','Consulta de associados'],['reservations','▣','Histórico de reservas'],['calendar','◫','Calendário'],['profile','◉','Meu perfil']],
  admin: [['home','⌂','Dashboard'],['reservations','▣','Reservas'],['rooms','▤','Salas'],['calendar','◫','Calendário'],['reports','▥','Relatórios'],['settings','⚙','Configurações']],
};

function renderNavigation(active = 'home') {
  $('#main-nav').innerHTML = navByRole[role()].map(([id, icon, label]) => `<button class="${active === id ? 'active' : ''}" data-route="${id}"><span class="nav-icon">${icon}</span>${label}</button>`).join('');
}

function appTitle(title, kicker = 'VISÃO GERAL') {
  $('#page-title').textContent = title;
  $('#page-kicker').textContent = kicker;
}

function initials(name = '') {
  return name.split(/\s+/).slice(0,2).map(word => word[0]).join('').toUpperCase() || 'AR';
}

async function startApp() {
  setScreen('app');
  $('#year').textContent = new Date().getFullYear();
  $('#profile-initials').textContent = initials(state.user?.name);
  renderNavigation();
  await showDashboard();
}

function statusLabel(status) {
  return ({pending:'Em análise',approved:'Aprovada',confirmed:'Confirmada',rejected:'Rejeitada',cancelled:'Cancelada',draft:'Rascunho'})[status] || status;
}

function eventDate(date) {
  const value = new Date(date);
  return {day: new Intl.DateTimeFormat('pt-BR',{day:'2-digit',timeZone:'America/Sao_Paulo'}).format(value), month:new Intl.DateTimeFormat('pt-BR',{month:'short',timeZone:'America/Sao_Paulo'}).format(value).replace('.','').toUpperCase()};
}

function dateTime(date) {
  return new Intl.DateTimeFormat('pt-BR',{dateStyle:'short',timeStyle:'short',timeZone:'America/Sao_Paulo'}).format(new Date(date));
}

function loading() { $('#app-content').innerHTML = '<div class="panel blank-panel">Carregando informações…</div>'; }

async function showDashboard() {
  renderNavigation('home'); loading();
  appTitle(`Olá, ${state.user.name.split(' ')[0]}`, role() === 'associate' ? 'BEM-VINDO AO AC RESERVA' : 'PAINEL DE CONTROLE');
  try {
    const {data} = await api('/api/dashboard');
    if (role() === 'associate') renderAssociateDashboard(data);
    else renderStaffDashboard(data);
  } catch (error) { $('#app-content').innerHTML = `<div class="panel blank-panel">${escapeHtml(error.message)}</div>`; }
}

function renderAssociateDashboard(data) {
  const quota = data.quota || {used:0,limit:4,remaining:4};
  const meterClass = quota.used >= 4 ? 'quota-danger' : quota.used >= 3 ? 'quota-warning' : '';
  const next = data.upcoming?.[0];
  $('#app-content').innerHTML = `
    <div class="dashboard-grid">
      <section class="panel greeting"><div><h2>Organize seu próximo encontro.</h2><p>Confira seus espaços e envie uma nova solicitação em poucos passos.</p></div><button class="primary-button" data-open-reservation>+ Nova reserva</button></section>
      <section class="panel"><div class="panel-heading"><h2>Reservas do mês</h2><button data-route="reservations">Ver todas</button></div><div class="quota ${meterClass}"><div><strong>${quota.used} / ${quota.limit}</strong><span class="muted">${quota.remaining} ${quota.remaining === 1 ? 'reserva disponível' : 'reservas disponíveis'}</span></div><div class="quota-meter"><i style="width:${Math.min(100,(quota.used/quota.limit)*100)}%"></i></div></div></section>
      <section class="panel"><div class="panel-heading"><h2>Próxima reserva</h2></div>${next ? eventCard(next) : '<div class="blank-panel">Nenhuma reserva futura encontrada.</div>'}</section>
      <section class="panel wide"><div class="panel-heading"><h2>Próximos eventos</h2><button data-route="calendar">Ver calendário</button></div><div class="event-list">${data.upcoming?.length ? data.upcoming.map(eventCard).join('') : '<div class="blank-panel">Quando houver uma reserva, ela aparecerá aqui.</div>'}</div></section>
    </div>`;
}

function renderStaffDashboard(data) {
  $('#app-content').innerHTML = `<div class="dashboard-grid"><section class="panel greeting"><div><h2>Visão da operação.</h2><p>Acompanhe o volume de reservas e mantenha os eventos preparados.</p></div><button class="primary-button" data-route="reservations">Ver reservas</button></section><section class="panel"><div class="panel-heading"><h2>Reservas ativas</h2></div><div class="stat-card"><strong>${data.active_reservations || 0}</strong><span>aguardando ou confirmadas</span></div></section><section class="panel"><div class="panel-heading"><h2>Agenda de hoje</h2></div><div class="stat-card"><strong>${data.today || 0}</strong><span>eventos programados</span></div></section><section class="panel wide"><div class="blank-panel">Use o menu para consultar as reservas, salas e as tarefas do seu setor.</div></section></div>`;
}

function eventCard(event) {
  const date = eventDate(event.starts_at);
  return `<article class="event-row"><time class="event-date" datetime="${escapeHtml(event.starts_at)}"><span>${date.month}</span><strong>${date.day}</strong></time><div class="event-info"><strong>${escapeHtml(event.title)}</strong><span>${escapeHtml(event.room_name || '')} · ${dateTime(event.starts_at)}</span></div><span class="badge ${escapeHtml(event.status)}">${escapeHtml(statusLabel(event.status))}</span></article>`;
}

async function showReservations() {
  renderNavigation('reservations'); loading(); appTitle('Reservas', 'ACOMPANHAMENTO');
  try {
    const {data} = await api('/api/reservations');
    const allowCancel = role() === 'associate';
    $('#app-content').innerHTML = `<section class="panel"><div class="panel-heading"><h2>${role() === 'associate' ? 'Minhas reservas' : 'Todas as reservas'}</h2>${role() === 'associate' ? '<button class="primary-button" data-open-reservation>+ Nova reserva</button>' : ''}</div>${data.length ? `<table class="reservation-table"><thead><tr><th>PROTOCOLO</th><th>EVENTO</th><th>SALA</th><th>INÍCIO</th><th>STATUS</th>${allowCancel ? '<th></th>' : ''}</tr></thead><tbody>${data.map(item => `<tr><td>${escapeHtml(item.protocol)}</td><td><strong>${escapeHtml(item.title)}</strong></td><td>${escapeHtml(item.room_name)}</td><td>${dateTime(item.starts_at)}</td><td><span class="badge ${escapeHtml(item.status)}">${escapeHtml(statusLabel(item.status))}</span></td>${allowCancel ? `<td>${['pending','approved','confirmed'].includes(item.status) ? `<button data-cancel="${item.id}">Cancelar</button>` : ''}</td>` : ''}</tr>`).join('')}</tbody></table>` : '<div class="blank-panel">Nenhuma reserva encontrada.</div>'}</section>`;
  } catch(error) { $('#app-content').innerHTML = `<div class="panel blank-panel">${escapeHtml(error.message)}</div>`; }
}

function showPlaceholder(route) {
  renderNavigation(route);
  const labels = {calendar:'Calendário',profile:'Meu perfil',preparation:'Preparação das salas',equipment:'Equipamentos',rooms:'Salas',reports:'Relatórios',settings:'Configurações'};
  appTitle(labels[route] || 'AC Reserva', 'EM BREVE');
  $('#app-content').innerHTML = `<section class="panel blank-panel"><h2>${labels[route] || 'Módulo'}</h2><p>Este módulo estará disponível conforme os dados e permissões forem configurados pela administração.</p></section>`;
}

async function openReservationDialog() {
  const dialog = $('#reservation-dialog');
  try {
    if (!state.rooms.length) {
      const {data} = await api('/api/rooms');
      state.rooms = data;
    }
    $('#reservation-room').innerHTML = '<option value="">Selecione uma sala</option>' + state.rooms.map(room => `<option value="${room.id}">${escapeHtml(room.name)} · até ${room.capacity} pessoas</option>`).join('');
    dialog.showModal();
  } catch(error) { toast(error.message); }
}

function closeDialog() { $('#reservation-dialog').close(); }

function localIso(value) { return new Date(value).toISOString(); }

async function submitReservation(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const data = new FormData(form);
  const payload = {
    title:data.get('title'), room_id:data.get('room_id'), starts_at:localIso(data.get('starts_at')), ends_at:localIso(data.get('ends_at')),
    participant_count:Number(data.get('participant_count')), description:data.get('description') || null,
    needs_it:data.has('needs_it'), needs_reception:data.has('needs_reception'), needs_coffee:data.has('needs_coffee'),
  };
  const button = $('button[type="submit"]', form); const original = button.innerHTML;
  button.disabled = true; button.textContent = 'Validando…';
  try {
    const {data: created} = await api('/api/reservations',{method:'POST',body:JSON.stringify(payload)});
    closeDialog(); form.reset(); toast(`Solicitação ${created.protocol} enviada com sucesso.`, 'success'); showDashboard();
  } catch(error) { toast(error.message); }
  finally { button.disabled = false; button.innerHTML = original; }
}

async function cancelReservation(id) {
  if (!window.confirm('Deseja cancelar esta reserva? A cota será recalculada automaticamente.')) return;
  try { await api(`/api/reservations/${id}/cancel`,{method:'POST'}); toast('Reserva cancelada com sucesso.', 'success'); showReservations(); }
  catch(error) { toast(error.message); }
}

function logout(showMessage = true) {
  sessionStorage.removeItem('acReservaToken'); sessionStorage.removeItem('acReservaUser'); state.user = null; state.token = null; state.rooms = [];
  setScreen('welcome');
  if(showMessage) toast('Você saiu da sua conta.', 'success');
}

async function startSession(result) {
  state.token = result.token;
  state.user = result.user;
  sessionStorage.setItem('acReservaToken', state.token);
  sessionStorage.setItem('acReservaUser', JSON.stringify(state.user));
  await startApp();
}

document.addEventListener('click', async event => {
  const access = event.target.closest('[data-access]');
  if (access) { const kind = access.dataset.access; if(kind === 'associate') showLogin('associate'); else if(kind === 'acim') await showAcimSectors(); else showExternal(); return; }
  const sector = event.target.closest('[data-sector]'); if (sector) { showLogin('acim', sector.dataset.sector); return; }
  const route = event.target.closest('[data-route]'); if (route) { const id = route.dataset.route; if(id === 'home') showDashboard(); else if(id === 'reservations') showReservations(); else if(id === 'new') openReservationDialog(); else showPlaceholder(id); return; }
  if (event.target.closest('[data-open-reservation]')) { openReservationDialog(); return; }
  const cancel = event.target.closest('[data-cancel]'); if (cancel) { cancelReservation(cancel.dataset.cancel); return; }
  if (event.target.closest('[data-close-dialog]')) { closeDialog(); return; }
  if (event.target.closest('#logout-button')) { logout(); return; }
  if (event.target.closest('#menu-button')) { $('#sidebar').classList.add('open'); $('#scrim').classList.add('visible'); return; }
  if (event.target.closest('#scrim')) { $('#sidebar').classList.remove('open'); $('#scrim').classList.remove('visible'); return; }
  const help = event.target.closest('[data-help]');
  if (help) {
    if (help.dataset.help === 'access') showFirstAccess();
    else toast('Solicite à administração da ACIM a recuperação da sua senha.');
    return;
  }
  if (event.target.closest('[data-back-login]')) { showLogin('acim'); return; }
  if (event.target.closest('.external-options button')) toast('Solicite à recepção o convite e as permissões para seu acesso.');
});

$('#back-to-welcome').addEventListener('click', () => setScreen('welcome'));
$('#sector-search').addEventListener('input', renderSectors);
$('#show-password').addEventListener('click', () => { const input = $('#login-password'); input.type = input.type === 'password' ? 'text' : 'password'; });
$('#login-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget; if(!form.reportValidity()) return;
  const button = $('button[type="submit"]', form); button.disabled = true; button.textContent = 'Entrando…';
  try {
    const payload = {email:$('#login-email').value,password:$('#login-password').value,identifier:state.access === 'associate' ? $('#login-identifier').value : undefined,sector_id:state.sectorId || undefined,access_type:state.access === 'associate' ? 'associate' : 'acim'};
    const result = await api('/api/auth/login',{method:'POST',body:JSON.stringify(payload)});
    await startSession(result);
  } catch(error) { toast(error.message); }
  finally { button.disabled = false; button.innerHTML = 'Entrar <span aria-hidden="true">→</span>'; }
});
$('#setup-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const password = $('#setup-password').value;
  if (password !== $('#setup-password-confirmation').value) {
    toast('As senhas não coincidem.');
    return;
  }
  const button = $('button[type="submit"]', form);
  const original = button.innerHTML;
  button.disabled = true;
  button.textContent = 'Criando acesso…';
  try {
    const result = await api('/api/setup/admin', {method:'POST', body:JSON.stringify({name:$('#setup-name').value, email:$('#setup-email').value, password})});
    form.reset();
    toast('Acesso administrador criado com sucesso.', 'success');
    await startSession(result);
  } catch(error) { toast(error.message); }
  finally { button.disabled = false; button.innerHTML = original; }
});
$('#reservation-form').addEventListener('submit', submitReservation);

if (state.token && state.user) {
  api('/api/me').then(result => { state.user = result.data; sessionStorage.setItem('acReservaUser',JSON.stringify(state.user)); startApp(); }).catch(() => logout(false));
}
