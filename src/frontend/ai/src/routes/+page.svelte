<script lang="ts">
	import { onDestroy, onMount, tick } from 'svelte';
	import { renderMarkdown, normalizePoint } from '$lib/markdown';
	type Source = {
		point: string;
		doc?: string;
		chapter?: string;
		page?: number;
		relevance?: number;
		version?: string;
		text_preview?: string;
	};
	type Message = {
		role: 'user' | 'assistant' | 'error' | 'clarification';
		content: string;
		sources?: Source[];
		no_answer?: boolean;
		retryable?: boolean;
		id?: string; // id записи messages в PocketBase (нужен для feedback)
		rating?: 'up' | 'down';
		feedbackId?: string;
		feedbackFailed?: boolean;
		feedbackBusy?: boolean;
	};
	type QuickReply = { id: string; title: string; doc_kind: string };
	type ChatResponse = {
		answer: string;
		sources?: Source[];
		no_answer?: boolean;
		clarification?: boolean;
		query_used?: string;
		latency_ms?: number;
	};
	type VersionStatus = 'draft' | 'indexing' | 'active' | 'archived' | 'failed';
	type DocVersion = {
		id: string;
		document: string;
		version_label: string;
		status: VersionStatus;
		access_level: number;
		effective_date?: string;
		indexed_at?: string;
		chunks_count?: number;
		comment?: string;
		created: string;
	};
	type Document = {
		id: string;
		title: string;
		doc_type: string;
		owner_dept?: string;
		current_version?: string;
		updated?: string;
		expand?: { current_version?: DocVersion };
	};
	// Адреса задаются на этапе сборки (Vite подставляет VITE_* в бандл), см. .env.example.
	// Значения по умолчанию только для dev-режима: в продакшене без переменных страница сообщит о неверной конфигурации.
	const env = import.meta.env;
	const cleanUrl = (u?: string) => (u ?? '').trim().replace(/\/+$/, '');
	const backendUrl = cleanUrl(env.VITE_BACKEND_URL) || (env.DEV ? 'http://127.0.0.1:8000' : '');
	const pbUrl = cleanUrl(env.VITE_PB_URL) || (env.DEV ? 'http://127.0.0.1:8090' : '');
	const configError = backendUrl && pbUrl ? '' : 'Не заданы VITE_BACKEND_URL и/или VITE_PB_URL (см. .env.example)';
	const api = `${pbUrl}/api`;
	const TOKEN_KEY = 'pb_token';
	const USER_KEY = 'pb_user';
	class AuthError extends Error {}
	class HttpError extends Error {
		status: number;
		constructor(status: number) {
			super(`HTTP ${status}`);
			this.status = status;
		}
	}
	const CHAT_TIMEOUT_MS = 30_000;
	const navItems = [
		{ label: 'Главная', icon: '⌂' },
		{ label: 'Документы', icon: '▣' },
		{ label: 'AI-чат', icon: '✧' }
	];
	let activeNav = 'Главная';
	let showMenu = false;
	let showAuth = false;
	let identity = '';
	let password = '';
	let authError = '';
	let authBusy = false;
	let token = '';
	let user: any = null;
	let sessionId = '';
	let draft = '';
	let messages: Message[] = [];
	let isLoading = false;
	let elapsed = 0;
	let quickReplies: QuickReply[] = [];
	let endEl: HTMLElement | undefined;
	let connectionState = 'Проверяю подключение…';
	let documents: Document[] = [];
	let selectedSource: Source | null = null;
	let selectedChunk = '';
	let chunkState: 'loading' | 'ready' | 'error' = 'loading';
	let chunkSeq = 0;
	let docsLoading = false;
	let uploadFile: File | null = null;
	let uploadVersionLabel = '';
	let uploadDocumentId = '';
	let uploadStatus = '';
	let uploadOk = false;
	let uploadAccess = 1;
	let uploadComment = '';
	let uploading = false;
	let fileInput: HTMLInputElement | undefined;
	let versions: Record<string, DocVersion[]> = {};
	let docsError = '';
	let pollTimer: ReturnType<typeof setTimeout> | undefined;
	const MAX_FILE_SIZE = 20 * 1024 * 1024; // maxSize поля file в document_versions
	const statusLabels: Record<string, string> = {
		draft: 'Ожидает индексации',
		indexing: 'Индексируется',
		active: 'Активна',
		archived: 'В архиве',
		failed: 'Ошибка индексации'
	};
	const docTypeLabels: Record<string, string> = { instruction: 'Инструкция', matrix: 'Матрица', module: 'Модуль', methodology: 'Методика' };
	const accessLabels: Record<number, string> = { 1: '1 · все сотрудники', 2: '2 · методологи и админы', 3: '3 · только админы' };

	// PocketBase принимает токен как есть, без префикса Bearer
	function pbHeaders(): Record<string, string> {
		return token ? { Authorization: token } : {};
	}
	function tokenExpired(t = token) {
		try {
			const payload = JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
			return typeof payload.exp !== 'number' || payload.exp * 1000 < Date.now() + 5000;
		} catch {
			return true;
		}
	}
	function saveAuth(t: string, record: any) {
		token = t;
		user = record;
		localStorage.setItem(TOKEN_KEY, t);
		localStorage.setItem(USER_KEY, JSON.stringify(record));
	}
	function logout() {
		token = '';
		user = null;
		sessionId = '';
		messages = [];
		documents = [];
		selectedSource = null;
		uploadStatus = '';
		localStorage.removeItem(TOKEN_KEY);
		localStorage.removeItem(USER_KEY);
	}
	function handle401(text = 'Сессия истекла. Войдите снова.') {
		logout();
		authError = text;
		showAuth = true;
	}
	function openAuth() {
		authError = '';
		showAuth = true;
	}
	// PocketBase на просроченный токен часто отвечает не 401, а пустым списком или 400/403,
	// поэтому срок жизни JWT проверяем сами, до запроса.
	function assertAuth() {
		if (!token) {
			openAuth();
			throw new AuthError('Войдите, чтобы продолжить');
		}
		if (tokenExpired()) {
			handle401();
			throw new AuthError('Сессия истекла. Войдите снова.');
		}
	}
	async function pb(path: string, init: RequestInit = {}) {
		assertAuth();
		const headers = new Headers(init.headers);
		headers.set('Authorization', token);
		if (typeof init.body === 'string' && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
		const res = await fetch(`${api}${path}`, { ...init, headers });
		if (res.status === 401) {
			handle401();
			throw new AuthError('Сессия истекла. Войдите снова.');
		}
		return res;
	}
	async function login() {
		if (authBusy) return;
		authError = '';
		if (configError) {
			authError = configError;
			return;
		}
		if (!identity.trim() || !password) {
			authError = 'Введите почту и пароль';
			return;
		}
		authBusy = true;
		try {
			const res = await fetch(`${api}/collections/users/auth-with-password`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ identity: identity.trim(), password })
			});
			if (!res.ok) throw new Error(res.status === 400 ? 'Неверная почта или пароль' : `Ошибка входа (${res.status})`);
			const data = await res.json();
			saveAuth(data.token, data.record);
			password = '';
			showAuth = false;
			await loadDocuments();
		} catch (e) {
			authError = e instanceof TypeError ? 'Нет связи с сервером авторизации' : e instanceof Error ? e.message : 'Не удалось войти';
		} finally {
			authBusy = false;
		}
	}
	async function restoreSession() {
		if (tokenExpired()) return handle401();
		try {
			const res = await fetch(`${api}/collections/users/auth-refresh`, { method: 'POST', headers: pbHeaders() });
			if (res.ok) {
				const data = await res.json();
				saveAuth(data.token, data.record);
			} else if ([400, 401, 403, 404].includes(res.status)) {
				return handle401();
			}
		} catch {
			/* PocketBase недоступен: работаем с сохранённым токеном */
		}
		await loadDocuments();
	}
	// session_id = id записи chat_sessions; создаём при первом вопросе диалога
	async function ensureSession(firstMessage: string) {
		if (sessionId) return sessionId;
		const res = await pb('/collections/chat_sessions/records', {
			method: 'POST',
			body: JSON.stringify({ user: user.id, title: firstMessage.slice(0, 80), status: 'active' })
		});
		if (!res.ok) throw new Error('Не удалось создать сессию чата');
		sessionId = (await res.json()).id;
		return sessionId;
	}
	function newChat() {
		const previous = sessionId;
		messages = [];
		sessionId = '';
		if (previous && token) {
			pb(`/collections/chat_sessions/records/${previous}`, { method: 'PATCH', body: JSON.stringify({ status: 'closed' }) }).catch(() => {});
		}
	}
	async function loadDocuments(silent = false) {
		if (!token) return;
		if (!silent) docsLoading = true;
		docsError = '';
		clearTimeout(pollTimer);
		try {
			const [docsRes, versionsRes] = await Promise.all([
				pb('/collections/documents/records?expand=current_version&sort=-updated&perPage=200'),
				pb('/collections/document_versions/records?sort=-created&perPage=500')
			]);
			if (!docsRes.ok || !versionsRes.ok) throw new Error('PocketBase вернул ошибку');
			documents = (await docsRes.json()).items ?? [];
			const grouped: Record<string, DocVersion[]> = {};
			for (const v of (await versionsRes.json()).items ?? []) (grouped[v.document] ??= []).push(v);
			versions = grouped;
		} catch (e) {
			if (!(e instanceof AuthError)) docsError = e instanceof TypeError ? 'Нет связи с PocketBase' : 'Не удалось загрузить документы';
		} finally {
			docsLoading = false;
			schedulePoll();
		}
	}
	// пока есть версии в draft/indexing, обновляем список раз в 5 секунд (пока открыт экран «Документы»)
	function schedulePoll() {
		clearTimeout(pollTimer);
		const pending = Object.values(versions).some((list) => list.some((v) => v.status === 'draft' || v.status === 'indexing'));
		if (pending && token && activeNav === 'Документы') pollTimer = setTimeout(() => loadDocuments(true), 5000);
	}
	function formatDate(value?: string) {
		const d = value ? new Date(value.replace(' ', 'T')) : null;
		return d && !isNaN(d.getTime()) ? d.toLocaleDateString('ru-RU') : '';
	}
	function canUpload() {
		return !!user && ['admin', 'methodologist'].includes(user.role);
	}
	function selectDocument(id: string) {
		uploadDocumentId = id;
		uploadAccess = documents.find((d) => d.id === id)?.expand?.current_version?.access_level ?? 1;
	}
	async function backendFetch(path: string, init: RequestInit = {}) {
		assertAuth();
		const headers = new Headers(init.headers);
		headers.set('Authorization', `Bearer ${token}`);
		if (typeof init.body === 'string' && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
		const res = await fetch(`${backendUrl}${path}`, { ...init, headers });
		if (res.status === 401) {
			handle401();
			throw new AuthError('Сессия истекла. Войдите снова.');
		}
		if (!res.ok) throw new HttpError(res.status);
		return res;
	}
	function describeError(e: unknown): string {
		if (e instanceof AuthError) return e.message;
		if (e instanceof DOMException && e.name === 'AbortError') return 'Ответ не получен за 30 секунд. Попробуйте ещё раз.';
		if (e instanceof HttpError)
			return e.status === 503 ? 'AI-сервис временно недоступен (503). Повторите запрос через минуту.' : `Ошибка AI-сервиса (${e.status})`;
		if (e instanceof TypeError) return 'Нет связи с AI-сервисом. Проверьте подключение.';
		return e instanceof Error ? e.message : 'Неизвестная ошибка';
	}
	async function submitQuery(override?: string) {
		const message = (override ?? draft).trim();
		if (!message || isLoading) return;
		if (!token) return openAuth();
		if (override === undefined) draft = '';
		messages = [...messages, { role: 'user', content: message }];
		await askBackend(message);
	}
	function scrollToEnd() {
		tick().then(() => endEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
	}
	// Быстрые кнопки уточнения: активные шаблоны модулей из PocketBase (бэкенд обычно уточняет, какой документ нужен)
	async function loadQuickReplies() {
		if (quickReplies.length) return;
		try {
			const res = await pb(
				`/collections/module_templates/records?filter=${encodeURIComponent('is_active=true')}&sort=title&perPage=20&fields=id,title,doc_kind`
			);
			if (res.ok) quickReplies = (await res.json()).items ?? [];
		} catch {
			/* без кнопок можно ответить текстом */
		}
	}
	async function askBackend(message: string) {
		isLoading = true;
		elapsed = 0;
		scrollToEnd();
		const started = Date.now();
		const ticker = setInterval(() => (elapsed = Math.floor((Date.now() - started) / 1000)), 500);
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);
		try {
			await ensureSession(message);
			// сообщения в PocketBase пишет бэкенд, фронт их не создаёт
			const res = await backendFetch('/chat', {
				method: 'POST',
				signal: controller.signal,
				body: JSON.stringify({ session_id: sessionId, message })
			});
			const data: ChatResponse = await res.json();
			const reply: Message = {
				role: data.clarification ? 'clarification' : 'assistant',
				content: data.answer || 'Ответ не найден.',
				sources: data.no_answer ? [] : (data.sources ?? []),
				no_answer: !!data.no_answer
			};
			messages = [...messages, reply];
			void attachMessageId(reply, sessionId);
			if (data.clarification) loadQuickReplies();
		} catch (e) {
			messages = [...messages, { role: 'error', content: describeError(e), retryable: !(e instanceof AuthError) }];
		} finally {
			clearTimeout(timer);
			clearInterval(ticker);
			isLoading = false;
			scrollToEnd();
		}
	}
	async function retryLast() {
		if (isLoading || messages[messages.length - 1]?.role !== 'error') return;
		const question = [...messages].reverse().find((m) => m.role === 'user')?.content;
		if (!question) return;
		messages = messages.slice(0, -1);
		await askBackend(question);
	}
	function roleLabel(m: Message) {
		if (m.role === 'user') return 'Вы';
		if (m.role === 'error') return 'Ошибка';
		if (m.role === 'clarification') return 'Свод AI · нужно уточнение';
		if (m.no_answer) return 'Свод AI · не найдено в документах';
		return 'Свод AI';
	}
	// Панель источника: сначала показываем text_preview из ответа, затем подгружаем полный текст пункта
	async function openSource(source: Source) {
		const seq = ++chunkSeq;
		selectedSource = source;
		selectedChunk = source.text_preview || '';
		chunkState = 'loading';
		try {
			const res = await backendFetch(`/chunks/${encodeURIComponent(source.point)}`);
			const data = await res.json();
			if (seq !== chunkSeq) return; // пользователь уже открыл другой пункт
			selectedChunk = data.text ?? data.content ?? data.text_preview ?? 'Текст отсутствует';
			chunkState = 'ready';
		} catch (e) {
			if (seq !== chunkSeq) return;
			chunkState = 'error';
			selectedChunk = e instanceof HttpError && e.status === 404 ? 'Пункт не найден в индексе.' : describeError(e);
		}
	}
	function closeSource() {
		chunkSeq++;
		selectedSource = null;
	}
	function formatRelevance(r?: number) {
		if (typeof r !== 'number') return '';
		return r <= 1 ? `${Math.round(r * 100)}%` : String(Math.round(r));
	}
	// Клик по [п. X.Y] в тексте ответа: ищем пункт среди источников этого ответа, иначе открываем по номеру
	function onContentClick(e: MouseEvent, message: Message) {
		const el = (e.target as HTMLElement).closest<HTMLElement>('[data-point]');
		if (!el) return;
		const point = el.dataset.point!;
		const sources = message.sources ?? [];
		const source =
			sources.find((s) => s.point === point || normalizePoint(s.point) === point) ??
			sources.find((s) => s.point.split(/[^\d.]+/).includes(point));
		openSource(source ?? { point });
	}
	// /chat не возвращает id сообщения, а feedback ссылается на запись messages, которую создал бэкенд:
	// находим самое новое ещё не привязанное сообщение ассистента в этой сессии
	async function attachMessageId(m: Message, sid: string) {
		for (let attempt = 0; attempt < 4 && !m.id; attempt++) {
			if (attempt) await new Promise((r) => setTimeout(r, 700));
			try {
				const filter = encodeURIComponent(`session="${sid}" && role="assistant"`);
				const res = await pb(`/collections/messages/records?filter=${filter}&sort=-created&perPage=10&fields=id`);
				if (!res.ok) continue;
				const taken = new Set(messages.map((x) => x.id));
				const fresh = ((await res.json()).items ?? []).find((x: { id: string }) => !taken.has(x.id));
				if (fresh) {
					m.id = fresh.id;
					messages = messages;
				}
			} catch {
				return;
			}
		}
	}
	async function feedback(message: Message, rating: 'up' | 'down') {
		if (!message.id || message.feedbackBusy || message.rating === rating) return;
		const previous = message.rating;
		message.feedbackBusy = true;
		message.rating = rating;
		message.feedbackFailed = false;
		messages = messages;
		try {
			const res = message.feedbackId
				? await pb(`/collections/feedback/records/${message.feedbackId}`, { method: 'PATCH', body: JSON.stringify({ rating }) })
				: await pb('/collections/feedback/records', {
						method: 'POST',
						body: JSON.stringify({ user: user.id, message: message.id, rating })
					});
			if (!res.ok) throw new Error(`feedback ${res.status}`);
			message.feedbackId = (await res.json()).id;
		} catch (e) {
			message.rating = previous;
			message.feedbackFailed = !(e instanceof AuthError);
		} finally {
			message.feedbackBusy = false;
			messages = messages;
		}
	}
	function uploadResult(ok: boolean, text: string) {
		uploadOk = ok;
		uploadStatus = text;
	}
	async function uploadDocumentVersion() {
		if (uploading || !canUpload()) return;
		const label = uploadVersionLabel.trim();
		if (!uploadDocumentId || !label || !uploadFile) return uploadResult(false, 'Выберите документ, укажите версию и файл');
		if (uploadFile.size > MAX_FILE_SIZE) return uploadResult(false, 'Файл больше 20 МБ');
		if (versions[uploadDocumentId]?.some((v) => v.version_label.toLowerCase() === label.toLowerCase()))
			return uploadResult(false, `Версия «${label}» у этого документа уже есть`);
		uploading = true;
		uploadResult(true, 'Загружаю…');
		const form = new FormData();
		form.append('document', uploadDocumentId);
		form.append('version_label', label);
		form.append('status', 'draft');
		form.append('access_level', String(uploadAccess));
		form.append('uploaded_by', user.id);
		if (uploadComment.trim()) form.append('comment', uploadComment.trim());
		form.append('file', uploadFile);
		try {
			const res = await pb('/collections/document_versions/records', { method: 'POST', body: form });
			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				const fields = Object.entries(body?.data ?? {}).map(([k, v]) => `${k}: ${(v as { message?: string }).message ?? ''}`);
				throw new Error(fields.join('; ') || body?.message || `Ошибка PocketBase (${res.status})`);
			}
			uploadResult(true, 'Версия загружена, ждёт индексации');
			uploadVersionLabel = '';
			uploadComment = '';
			uploadFile = null;
			if (fileInput) fileInput.value = '';
			await loadDocuments(true);
		} catch (e) {
			uploadResult(
				false,
				e instanceof TypeError ? 'Нет связи с PocketBase' : e instanceof Error ? e.message : 'Не удалось загрузить версию'
			);
		} finally {
			uploading = false;
		}
	}
	onDestroy(() => clearTimeout(pollTimer));
	onMount(async () => {
		token = localStorage.getItem(TOKEN_KEY) || '';
		try {
			user = JSON.parse(localStorage.getItem(USER_KEY) || 'null');
		} catch {
			user = null;
		}
		try {
			if (configError) throw new Error(configError);
			const health = await fetch(`${backendUrl}/health`);
			connectionState = health.status < 500 ? 'AI-сервис доступен' : 'AI-сервис отвечает с ошибкой';
		} catch {
			connectionState = 'AI-сервис недоступен';
		}
		if (token && user) await restoreSession();
		else if (token) logout();
	});
</script>

<svelte:head>
	<title>Свод — AI-помощник</title>
	<meta name="description" content="Внутренние знания и проверяемые ответы" />
</svelte:head>
<svelte:window onkeydown={(e) => e.key === 'Escape' && closeSource()} />
<div class="app-shell">
	<aside class:mobile-open={showMenu} class="sidebar">
		<div class="brand">
			<span class="brand-mark">⌁</span>
			<span class="brand-name">СВОД</span>
		</div>
		<nav class="main-nav">
			{#each navItems as item}<button
					class:active={activeNav === item.label}
					onclick={() => {
						activeNav = item.label;
						showMenu = false;
						if (item.label === 'Документы') loadDocuments();
					}}
				>
					<span class="nav-icon">{item.icon}</span>
					<span>{item.label}</span>
				</button>{/each}
		</nav>
		<div class="divider"></div>
		<div class="privacy-card">
			<span class="shield">♢</span>
			<strong>Внутренний контур</strong>
			<small>Данные доступны после входа</small>
		</div>
	</aside>
	<main class="content">
		<header class="topbar">
			<button class="mobile-menu" onclick={() => (showMenu = !showMenu)}>☰</button>
			<div class="search">
				<span>⌕</span>
				<input placeholder="Поиск по документам" />
			</div>
			<div class="top-actions">
				{#if user}<button class="profile-trigger" onclick={logout}>
						<div class="avatar">{(user.name || user.email || 'U').slice(0, 1).toUpperCase()}</div>
						<div class="user-info">
							<strong>{user.name || user.email}</strong>
							<small>Выйти</small>
						</div>
					</button>{:else}<button class="interactive-button secondary" onclick={openAuth}>Войти</button>{/if}
			</div>
		</header>
		<div class="page-wrap">
			{#if configError}<div class="login-hint">{configError}</div>{/if}
			{#if activeNav === 'Главная' || activeNav === 'AI-чат'}
				<div class="page-heading">
					<div>
						<div class="eyebrow">01 / ВНУТРЕННИЕ ЗНАНИЯ</div>
						<h1>{activeNav === 'Главная' ? 'Главная' : 'AI-чат'}</h1>
						<p>Задайте вопрос по документам и получите ответ с источниками.</p>
						<div class="connection-status">● {connectionState}</div>
					</div>
					<button class="interactive-button ghost-button" onclick={newChat} disabled={isLoading}>＋ Новый чат</button>
				</div>
				<div class="layout-grid">
					<section class="conversation">
						<div class="greeting">
							<div class="sparkle">✧</div>
							<div>
								<strong>Спросите Свод AI</strong>
								<span>Ответы формируются по актуальным документам вашей базы.</span>
							</div>
						</div>
						{#if !user}<div class="login-hint">Войдите, чтобы задавать вопросы и сохранять сессии.</div>{/if}
						<div class="history">
							{#each messages as message, i}
								<div
									class:from-user={message.role === 'user'}
									class:error-message={message.role === 'error'}
									class:no-answer={message.no_answer}
									class:clarification={message.role === 'clarification'}
									class="message"
								>
									<div class="message-role">{roleLabel(message)}</div>
									{#if message.role === 'error'}
										<p>{message.content}</p>
										{#if message.retryable && i === messages.length - 1}
											<button class="interactive-button retry" onclick={retryLast} disabled={isLoading}>↻ Повторить</button>
										{/if}
									{:else}
										{#if message.role === 'user'}
											<div class="message-content user-text">{message.content}</div>
										{:else}
											<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
											<div class="message-content" onclick={(e) => onContentClick(e, message)}>
												{@html renderMarkdown(message.content)}
											</div>
										{/if}
										{#if message.no_answer}
											<p class="state-note">В документах ответа нет. Попробуйте переформулировать вопрос или назвать документ.</p>
										{/if}
										{#if message.sources?.length && !message.no_answer}
											<div class="sources-inline">
												{#each message.sources as source}
													<button class="source-chip" onclick={() => openSource(source)}>
														п. {source.point} · {source.doc || 'Источник'} · стр. {source.page ?? '—'}
													</button>
												{/each}
											</div>
										{/if}
										{#if message.role === 'clarification' && i === messages.length - 1 && !isLoading && quickReplies.length}
											<div class="sources-inline">
												{#each quickReplies as q}
													<button class="source-chip" onclick={() => submitQuery(`${q.doc_kind} «${q.title}»`)}>{q.title}</button>
												{/each}
											</div>
										{/if}
										{#if message.role === 'assistant'}
											<div class="feedback">
												<button
													class:active={message.rating === 'up'}
													disabled={!message.id || message.feedbackBusy}
													title="Полезный ответ"
													aria-label="Полезный ответ"
													onclick={() => feedback(message, 'up')}
												>
													👍
												</button>
												<button
													class:active={message.rating === 'down'}
													disabled={!message.id || message.feedbackBusy}
													title="Ответ не помог"
													aria-label="Ответ не помог"
													onclick={() => feedback(message, 'down')}
												>
													👎
												</button>
												{#if message.feedbackFailed}<span class="fb-note">Не удалось сохранить оценку</span>{/if}
											</div>
										{/if}
									{/if}
								</div>
							{/each}
							{#if isLoading}
								<div class="answer-card loading-card" role="status" aria-live="polite">
									<div class="card-kicker">
										<span class="spinner"></span>
										Изучаю документы · {elapsed} с
									</div>
									<p>{elapsed < 15 ? 'Собираю ответ и проверяю источники…' : 'Ответ занимает дольше обычного, жду до 30 секунд…'}</p>
									<div class="progress"><span style="width: {Math.min(100, (elapsed / 30) * 100)}%"></span></div>
								</div>
							{/if}
							{#if !messages.length}
								<div class="welcome-card">
									<div class="welcome-symbol">✧</div>
									<h2>С чего начнём?</h2>
									<p>Спросите о регламенте, документе или рабочем процессе.</p>
								</div>
							{/if}
							<div bind:this={endEl}></div>
						</div>
						<div class="composer">
							<textarea
								bind:value={draft}
								onkeydown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), submitQuery())}
								placeholder="Задайте вопрос…"
								disabled={isLoading}></textarea>
							<div class="composer-bottom">
								<span class="attach">Enter — отправить · Shift+Enter — новая строка</span>
								<button class="interactive-button primary send" onclick={() => submitQuery()} disabled={isLoading}>↥ Отправить</button>
							</div>
						</div>
					</section>
					<aside class="right-rail">
						<div class="rail-card">
							<h3>⌁ Быстрые действия</h3>
							<button
								class="interactive-button"
								onclick={() => {
									activeNav = 'Документы';
									loadDocuments();
								}}
							>
								Открыть документы <span>↗</span>
							</button>
							<button class="interactive-button" onclick={() => (activeNav = 'AI-чат')}>
								Открыть AI-чат <span>↗</span>
							</button>
						</div>
					</aside>
				</div>
			{:else}
				<div class="page-heading">
					<div>
						<div class="eyebrow">02 / WORKSPACE · ДОКУМЕНТЫ</div>
						<h1>Документы</h1>
						<p>Документы и версии из PocketBase.</p>
					</div>
					<button class="interactive-button ghost-button" onclick={() => (activeNav = 'AI-чат')}>✧ К AI-чату</button>
				</div>
				<div class="workspace-grid">
					<section class="workspace-main">
						<div class="workspace-banner">
							<span class="workspace-icon">▣</span>
							<div>
								<strong>Единый каталог документов</strong>
								<p>
									{docsLoading
										? 'Загружаю данные…'
										: `${documents.length} документов · ${Object.values(versions).reduce((n, list) => n + list.length, 0)} версий`}
								</p>
							</div>
						</div>
						<div class="document-list">
							{#if docsError}
								<div class="empty-rail">
									<p class="error-text">{docsError}</p>
									<button class="interactive-button" onclick={() => loadDocuments()}>Повторить</button>
								</div>
							{:else if documents.length}
								{#each documents as doc}
									{@const current = doc.expand?.current_version}
									{@const list = versions[doc.id] ?? []}
									<article class="document-row">
										<span class="document-icon">▣</span>
										<span>
											<strong>{doc.title}</strong>
											<small>
												{docTypeLabels[doc.doc_type] ?? doc.doc_type}{#if doc.owner_dept}
													· {doc.owner_dept}{/if}
												· {current ? `версия ${current.version_label}` : 'версия не указана'}
											</small>
											{#if list.length}
												<details class="versions">
													<summary>Версии ({list.length})</summary>
													<ul>
														{#each list as v}
															<li>
																<strong>{v.version_label}</strong>
																{#if v.id === doc.current_version}<span class="cur">текущая</span>{/if}
																<span class="badge st-{v.status}">
																	{#if v.status === 'indexing'}<span class="spinner"></span>{/if}
																	{statusLabels[v.status] ?? v.status}
																</span>
																<small>
																	{v.chunks_count ? `${v.chunks_count} пунктов · ` : ''}{formatDate(v.indexed_at)
																		? `проиндексирована ${formatDate(v.indexed_at)} · `
																		: ''}доступ {v.access_level}
																</small>
																{#if v.status === 'failed' && v.comment}<small class="error-text">{v.comment}</small>{/if}
															</li>
														{/each}
													</ul>
												</details>
											{/if}
										</span>
										{#if current}
											<em class="badge st-{current.status}">{statusLabels[current.status] ?? current.status}</em>
										{/if}
									</article>
								{/each}
							{:else}
								<div class="empty-rail">
									{docsLoading ? 'Загружаю…' : token ? 'Документы не найдены или недоступны.' : 'Войдите, чтобы увидеть документы.'}
								</div>
							{/if}
						</div>
						{#if canUpload()}
							<div class="upload-card">
								<h2>Загрузить новую версию</h2>
								<div class="upload-fields">
									<select value={uploadDocumentId} onchange={(e) => selectDocument(e.currentTarget.value)}>
										<option value="">Выберите документ</option>
										{#each documents as doc}<option value={doc.id}>{doc.title}</option>{/each}
									</select>
									<input placeholder="Версия, например ОД-185" bind:value={uploadVersionLabel} />
									<select bind:value={uploadAccess} aria-label="Уровень доступа">
										{#each [1, 2, 3] as level}<option value={level}>{accessLabels[level]}</option>{/each}
									</select>
									<input type="file" bind:this={fileInput} onchange={(e) => (uploadFile = e.currentTarget.files?.[0] || null)} />
									<input placeholder="Комментарий (необязательно)" bind:value={uploadComment} />
									<button class="interactive-button primary" onclick={uploadDocumentVersion} disabled={uploading}>
										{uploading ? 'Загружаю…' : 'Загрузить'}
									</button>
								</div>
								{#if uploadStatus}<p class="upload-status" class:error-text={!uploadOk}>{uploadStatus}</p>{/if}
							</div>
						{/if}
					</section>
				</div>
			{/if}
		</div>
	</main>
	{#if selectedSource}<div class="source-backdrop" role="presentation" onclick={(e) => e.target === e.currentTarget && closeSource()}>
			<div class="source-panel" role="dialog" aria-modal="true" aria-label="Текст пункта">
				<button class="auth-close" aria-label="Закрыть" onclick={closeSource}>×</button>
				<div class="eyebrow">ИСТОЧНИК · {selectedSource.doc || 'Документ'}</div>
				<h2>{selectedSource.chapter || `Пункт ${selectedSource.point}`}</h2>
				<p class="source-meta">
					п. {selectedSource.point} · Страница {selectedSource.page ?? '—'} · версия {selectedSource.version ||
						'—'}{#if formatRelevance(selectedSource.relevance)}
						· релевантность {formatRelevance(selectedSource.relevance)}{/if}
				</p>
				<div class="source-text" class:muted={chunkState === 'loading'} class:failed={chunkState === 'error'}>
					{#if chunkState === 'loading'}<span class="spinner"></span>
						Загружаю полный текст…
						<br />
						<br />{/if}{selectedChunk}
				</div>
			</div>
		</div>{/if}
	{#if showAuth}<div class="auth-backdrop">
			<section class="auth-card">
				<button class="auth-close" onclick={() => (showAuth = false)}>×</button>
				<div class="auth-mark">⌁</div>
				<div class="eyebrow">СВОД · ВНУТРЕННИЙ КОНТУР</div>
				<h2>Войти</h2>
				<p>Используйте рабочую учётную запись PocketBase.</p>
				<label>
					Почта
					<input type="email" autocomplete="username" bind:value={identity} onkeydown={(e) => e.key === 'Enter' && login()} />
				</label>
				<label>
					Пароль
					<input type="password" autocomplete="current-password" bind:value={password} onkeydown={(e) => e.key === 'Enter' && login()} />
				</label>
				{#if authError}<p class="error-text">{authError}</p>{/if}
				<button class="interactive-button primary auth-submit" onclick={login} disabled={authBusy}>{authBusy ? 'Входим…' : 'Войти'}</button>
			</section>
		</div>{/if}
</div>

<style>
	:global(*) {
		box-sizing: border-box;
	}
	:global(body) {
		margin: 0;
		background: #070d1a;
		color: #e7edf7;
		font-family: Inter, ui-sans-serif, system-ui, sans-serif;
		font-size: 15px;
	}
	:global(button),
	:global(input),
	:global(textarea) {
		font: inherit;
	}
	.app-shell {
		min-height: 100vh;
		display: flex;
		background: radial-gradient(ellipse at 55% -10%, #14213d 0%, #080e1a 48%, #060b15 100%);
	}
	.sidebar {
		width: 286px;
		min-width: 286px;
		border-right: 1px solid #1a2945;
		background: rgba(9, 16, 31, 0.9);
		padding: 34px 22px 24px;
		display: flex;
		flex-direction: column;
	}
	.brand {
		display: flex;
		gap: 12px;
		align-items: center;
		margin: 4px 5px 42px;
	}
	.brand-mark {
		width: 38px;
		height: 38px;
		border: 1px solid #2dd6cb;
		color: #64ece2;
		border-radius: 11px;
		display: grid;
		place-items: center;
		font-size: 29px;
	}
	.brand-name {
		font-size: 19px;
		letter-spacing: 0.08em;
		font-weight: 700;
	}
	.main-nav {
		display: grid;
		gap: 8px;
	}
	.main-nav button {
		border: 0;
		background: transparent;
		color: #9eacc3;
		display: flex;
		align-items: center;
		gap: 15px;
		text-align: left;
		padding: 14px 13px;
		border-radius: 9px;
		cursor: pointer;
		font-size: 15px;
	}
	.main-nav button:hover,
	.main-nav button.active {
		background: #16464b;
		color: #79eee6;
	}
	.nav-icon {
		width: 20px;
		text-align: center;
		font-size: 19px;
	}
	.divider {
		height: 1px;
		background: #1b2943;
		margin: 28px 4px 16px;
	}
	.privacy-card {
		margin-top: auto;
		background: #111d33;
		border: 1px solid #263855;
		border-radius: 12px;
		padding: 16px 13px;
		display: grid;
		gap: 6px;
		color: #91a1b6;
	}
	.privacy-card strong {
		color: #d9e3ef;
		font-size: 13px;
	}
	.privacy-card small {
		font-size: 11px;
		line-height: 1.45;
	}
	.shield {
		color: #47e0d5;
		font-size: 16px;
	}
	.content {
		flex: 1;
		min-width: 0;
	}
	.topbar {
		height: 84px;
		border-bottom: 1px solid #1c2940;
		display: flex;
		align-items: center;
		gap: 20px;
		padding: 0 42px;
	}
	.search {
		height: 44px;
		border: 1px solid #253757;
		background: #101c31;
		border-radius: 9px;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0 14px;
		flex: 1;
		max-width: 760px;
		color: #7d8ea8;
	}
	.search input {
		border: 0;
		outline: 0;
		color: #dfe8f5;
		background: transparent;
		flex: 1;
		font-size: 14px;
	}
	.top-actions {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.profile-trigger {
		border: 0;
		background: transparent;
		color: inherit;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0;
		cursor: pointer;
		text-align: left;
	}
	.avatar {
		width: 34px;
		height: 34px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		background: #17294b;
		border: 1px solid #2b426b;
		color: #93c5e7;
		font-size: 13px;
	}
	.user-info {
		display: grid;
		gap: 3px;
	}
	.user-info strong {
		font-size: 13px;
	}
	.user-info small {
		color: #73839b;
		font-size: 11px;
	}
	.page-wrap {
		max-width: 1480px;
		margin: 0 auto;
		padding: 44px 48px 72px;
	}
	.page-heading {
		display: flex;
		justify-content: space-between;
		align-items: flex-end;
		margin-bottom: 32px;
	}
	.eyebrow {
		font-size: 11px;
		color: #788aa5;
		letter-spacing: 0.06em;
		margin-bottom: 17px;
	}
	.page-heading h1 {
		margin: 0 0 7px;
		font-size: 31px;
	}
	.page-heading p {
		margin: 0;
		color: #8291a7;
		font-size: 15px;
	}
	.connection-status {
		margin-top: 12px;
		color: #67d9cf;
		font-size: 13px;
	}
	.interactive-button {
		border: 1px solid #315176;
		border-radius: 999px;
		background: #12213b;
		color: #dce8f4;
		padding: 11px 18px;
		font-size: 13px;
		font-weight: 650;
		cursor: pointer;
	}
	.interactive-button.primary {
		background: #58ded1;
		border-color: #58ded1;
		color: #071a25;
	}
	.interactive-button:disabled {
		opacity: 0.55;
		cursor: wait;
	}
	.layout-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 300px;
		gap: 28px;
	}
	.conversation {
		min-width: 0;
	}
	.greeting {
		border: 1px solid #2a3b59;
		background: linear-gradient(100deg, #15253c, #122039);
		border-radius: 14px;
		min-height: 82px;
		padding: 20px 24px;
		display: flex;
		align-items: center;
		gap: 16px;
	}
	.sparkle {
		color: #63e6dd;
		background: #123c42;
		width: 42px;
		height: 42px;
		display: grid;
		place-items: center;
		border-radius: 11px;
		font-size: 24px;
	}
	.greeting strong {
		display: block;
		font-size: 16px;
		margin-bottom: 5px;
	}
	.greeting span {
		color: #8393a8;
		font-size: 13px;
	}
	.login-hint {
		margin: 14px 0;
		padding: 14px 18px;
		border: 1px solid #5b4930;
		background: #302718;
		color: #e6c98f;
		border-radius: 10px;
	}
	.history {
		display: grid;
		gap: 14px;
		margin-top: 18px;
	}
	.message {
		max-width: 88%;
		padding: 17px 20px;
		background: #111e34;
		border: 1px solid #2b4262;
		border-radius: 15px;
	}
	.message.from-user {
		margin-left: auto;
		background: #153841;
		border-color: #2c7777;
	}
	.message-role {
		font-size: 11px;
		color: #79eee6;
		margin-bottom: 8px;
		font-weight: 700;
	}
	.message-content {
		font-size: 15px;
		line-height: 1.65;
	}
	:global(.message-content code) {
		background: #0a1628;
		padding: 2px 5px;
		border-radius: 4px;
	}
	.error-message {
		border-color: #7c3f4b;
		background: #321e2a;
		color: #ffb8c0;
	}
	.feedback {
		display: flex;
		gap: 6px;
		margin-top: 12px;
	}
	.feedback button {
		background: transparent;
		border: 1px solid #315176;
		border-radius: 8px;
		padding: 5px 9px;
		cursor: pointer;
	}
	.sources-inline {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-top: 15px;
	}
	.source-chip {
		border: 1px solid #315176;
		background: #142b42;
		color: #9be9e1;
		border-radius: 999px;
		padding: 7px 11px;
		cursor: pointer;
		font-size: 12px;
	}
	.composer {
		margin-top: 18px;
		background: #111e33;
		border: 1px solid #293e5b;
		border-radius: 13px;
		padding: 16px 18px 13px;
	}
	.composer textarea {
		display: block;
		width: 100%;
		min-height: 72px;
		resize: vertical;
		border: 0;
		outline: 0;
		color: #dbe4f1;
		background: transparent;
		font-size: 15px;
	}
	.composer-bottom {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: 8px;
	}
	.attach {
		color: #7d8da4;
		font-size: 12px;
	}
	.welcome-card,
	.answer-card {
		border: 1px solid #2b4262;
		background: linear-gradient(145deg, #111e34, #101b2e);
		border-radius: 16px;
		padding: 38px 26px;
		text-align: center;
	}
	.welcome-symbol {
		margin: 0 auto 14px;
		background: #124d54;
		width: 48px;
		height: 48px;
		border-radius: 14px;
		display: grid;
		place-items: center;
		color: #62e4dc;
		font-size: 24px;
	}
	.welcome-card h2 {
		font-size: 24px;
		margin: 0 0 9px;
	}
	.welcome-card p {
		color: #94a1b3;
		font-size: 14px;
	}
	.loading-card {
		text-align: left;
		min-height: 150px;
	}
	.card-kicker {
		font-size: 14px;
	}
	.spinner {
		width: 13px;
		height: 13px;
		border: 2px solid #68e1d8;
		border-top-color: transparent;
		border-radius: 50%;
		display: inline-block;
		animation: spin 0.8s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	.right-rail {
		display: grid;
		align-content: start;
		gap: 14px;
	}
	.rail-card {
		background: #111e34;
		border: 1px solid #263a59;
		border-radius: 15px;
		padding: 20px 18px;
	}
	.rail-card h3 {
		text-align: center;
		margin: 0 0 14px;
		font-size: 15px;
	}
	.rail-card button {
		width: 100%;
		margin-top: 8px;
	}
	.rail-card button span {
		float: right;
	}
	.workspace-grid {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 300px;
		gap: 28px;
	}
	.workspace-banner {
		display: flex;
		align-items: center;
		gap: 18px;
		padding: 22px 24px;
		margin-bottom: 18px;
		background: linear-gradient(135deg, #152844, #102038);
		border: 1px solid #2a4263;
		border-radius: 16px;
	}
	.workspace-icon {
		display: grid;
		place-items: center;
		width: 48px;
		height: 48px;
		border-radius: 14px;
		background: #124b50;
		color: #72e9df;
		font-size: 24px;
	}
	.workspace-banner strong {
		display: block;
		font-size: 18px;
		margin-bottom: 6px;
	}
	.workspace-banner p {
		margin: 0;
		color: #91a2ba;
		font-size: 14px;
	}
	.document-list {
		display: grid;
		gap: 12px;
	}
	.document-row {
		display: flex;
		align-items: center;
		gap: 16px;
		width: 100%;
		text-align: left;
		color: #e3ebf6;
		background: #111e34;
		border: 1px solid #2a4263;
		border-radius: 14px;
		padding: 18px 20px;
	}
	.document-row .document-icon {
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		border-radius: 11px;
		background: #173d4d;
		color: #6fe5db;
		font-size: 20px;
	}
	.document-row span:nth-child(2) {
		flex: 1;
	}
	.document-row strong {
		display: block;
		font-size: 15px;
		margin-bottom: 5px;
	}
	.document-row small {
		display: block;
		color: #91a2b9;
		font-size: 13px;
	}
	.document-row em {
		color: #6bd8cf;
		font-style: normal;
		font-size: 12px;
	}
	.upload-card {
		margin-top: 20px;
		padding: 22px;
		background: #111e34;
		border: 1px solid #2a4263;
		border-radius: 15px;
	}
	.upload-card h2 {
		margin: 0 0 14px;
		font-size: 18px;
	}
	.upload-fields {
		display: flex;
		gap: 10px;
		flex-wrap: wrap;
	}
	.upload-fields input {
		border: 1px solid #2a3f5d;
		border-radius: 8px;
		background: #0c172a;
		color: #e1e9f5;
		padding: 11px;
	}
	.empty-rail {
		border: 1px dashed #2a3b59;
		border-radius: 10px;
		padding: 22px;
		color: #788ca6;
		text-align: center;
	}
	.error-text {
		color: #ff9fae;
	}
	.source-backdrop,
	.auth-backdrop {
		position: fixed;
		z-index: 30;
		inset: 0;
		background: rgba(3, 8, 17, 0.78);
		display: grid;
		place-items: center;
		padding: 20px;
	}
	.source-panel,
	.auth-card {
		position: relative;
		width: min(100%, 760px);
		max-height: 85vh;
		overflow: auto;
		background: #111e34;
		border: 1px solid #2d4668;
		border-radius: 16px;
		padding: 30px;
		box-shadow: 0 20px 60px #0008;
	}
	.source-panel h2 {
		margin: 0 0 8px;
		font-size: 24px;
	}
	.source-meta {
		color: #8291a7;
	}
	.source-text {
		margin-top: 20px;
		padding: 20px;
		background: #0b1729;
		border-radius: 12px;
		white-space: pre-wrap;
		line-height: 1.7;
	}
	.auth-card {
		width: min(100%, 420px);
	}
	.auth-close {
		position: absolute;
		top: 12px;
		right: 14px;
		border: 0;
		background: transparent;
		color: #8fa0b8;
		font-size: 25px;
		cursor: pointer;
	}
	.auth-mark {
		width: 42px;
		height: 42px;
		border: 1px solid #2dd6cb;
		color: #64ece2;
		border-radius: 12px;
		display: grid;
		place-items: center;
		font-size: 25px;
		margin-bottom: 18px;
	}
	.auth-card h2 {
		margin: 0 0 8px;
		font-size: 24px;
	}
	.auth-card p {
		color: #8798ae;
	}
	.auth-card label {
		display: grid;
		gap: 7px;
		color: #a4b2c5;
		font-size: 13px;
		margin-top: 14px;
	}
	.auth-card input {
		border: 1px solid #2a3f5d;
		border-radius: 8px;
		background: #0c172a;
		color: #e1e9f5;
		padding: 12px;
	}
	.auth-submit {
		width: 100%;
		margin-top: 22px;
	}
	.mobile-menu {
		display: none;
	}
	@media (max-width: 900px) {
		.sidebar {
			width: 220px;
			min-width: 220px;
		}
		.page-wrap {
			padding: 28px 20px;
		}
		.layout-grid,
		.workspace-grid {
			grid-template-columns: 1fr;
		}
		.right-rail {
			margin-top: 14px;
		}
	}
	@media (max-width: 700px) {
		.sidebar {
			position: fixed;
			z-index: 10;
			left: -240px;
			top: 0;
			bottom: 0;
			transition: left 0.2s;
		}
		.sidebar.mobile-open {
			left: 0;
		}
		.mobile-menu {
			display: block;
			border: 0;
			color: #a8b7cc;
			background: transparent;
			font-size: 20px;
		}
		.topbar {
			height: 64px;
			padding: 0 14px;
		}
		.page-wrap {
			padding: 22px 14px;
		}
		.page-heading {
			align-items: flex-start;
		}
		.message {
			max-width: 100%;
		}
		.composer-bottom {
			gap: 10px;
			align-items: flex-end;
			flex-direction: column;
		}
		.attach {
			align-self: flex-start;
		}
	}
	.source-text.muted {
		color: #8291a7;
	}
	.source-text.failed {
		color: #ff9fae;
	}
	.message.no-answer {
		border-color: #5b4930;
		background: #251f15;
	}
	.message.clarification {
		border-color: #3b6f9c;
	}
	.state-note {
		margin: 12px 0 0;
		color: #e6c98f;
		font-size: 13px;
	}
	.retry {
		margin-top: 10px;
	}
	.progress {
		height: 4px;
		margin-top: 16px;
		border-radius: 4px;
		background: #1a2945;
		overflow: hidden;
	}
	.progress span {
		display: block;
		height: 100%;
		background: #58ded1;
		transition: width 0.5s linear;
	}
	.feedback button.active {
		border-color: #58ded1;
		background: #16464b;
	}
	.feedback button:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.fb-note {
		align-self: center;
		color: #ff9fae;
		font-size: 12px;
	}
	.user-text {
		white-space: pre-wrap;
	}
	:global(.message-content p) {
		margin: 0 0 0.7em;
	}
	:global(.message-content > :last-child) {
		margin-bottom: 0;
	}
	:global(.message-content ul),
	:global(.message-content ol) {
		margin: 0 0 0.7em;
		padding-left: 1.4em;
	}
	:global(.message-content h3),
	:global(.message-content h4),
	:global(.message-content h5),
	:global(.message-content h6) {
		margin: 0.9em 0 0.4em;
		font-size: 15px;
	}
	:global(.message-content pre) {
		overflow-x: auto;
		margin: 0 0 0.7em;
		padding: 12px 14px;
		border-radius: 8px;
		background: #0a1628;
	}
	:global(.message-content pre code) {
		padding: 0;
		background: none;
	}
	:global(.message-content a) {
		color: #79eee6;
	}
	:global(.message-content .cite) {
		padding: 1px 7px;
		border: 1px solid #315176;
		border-radius: 6px;
		background: #142b42;
		color: #9be9e1;
		font-size: 12px;
		cursor: pointer;
	}
	:global(.message-content .cite:hover) {
		border-color: #58ded1;
	}
	.upload-fields select {
		border: 1px solid #2a3f5d;
		border-radius: 8px;
		background: #0c172a;
		color: #e1e9f5;
		padding: 11px;
	}
	.upload-status {
		margin: 12px 0 0;
		color: #79eee6;
	}
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 2px 9px;
		border: 1px solid #315176;
		border-radius: 999px;
		background: #142b42;
		color: #9be9e1;
		font-size: 12px;
		font-style: normal;
		white-space: nowrap;
	}
	.badge.st-draft {
		border-color: #5b4930;
		background: #302718;
		color: #e6c98f;
	}
	.badge.st-indexing {
		border-color: #35507a;
		background: #14253f;
		color: #9cc8ff;
	}
	.badge.st-failed {
		border-color: #7c3f4b;
		background: #321e2a;
		color: #ffb8c0;
	}
	.badge.st-archived {
		border-color: #2a3b59;
		background: #101c31;
		color: #8291a7;
	}
	.versions {
		margin-top: 10px;
	}
	.versions summary {
		color: #79eee6;
		font-size: 13px;
		cursor: pointer;
	}
	.versions ul {
		display: grid;
		gap: 8px;
		margin: 10px 0 0;
		padding: 0;
		list-style: none;
	}
	.versions li {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		font-size: 13px;
	}
	.versions li strong,
	.versions li small {
		display: inline;
		margin: 0;
	}
	.cur {
		color: #79eee6;
		font-size: 12px;
	}
</style>
