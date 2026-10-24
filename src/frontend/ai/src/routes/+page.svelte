<script lang="ts">
	let activeNav = 'AI-помощник';
	let query = '';
	let draft = '';
	let isLoading = false;
	let hasAnswer = false;
	let copied = false;
	let showMenu = false;
	let showAuth = false;
	let authMode: 'register' | 'login' = 'register';
	let answeredQueries = 0;
	let selectedDocument = '';

	const navItems = [
		{ label: 'Главная', icon: '⌂' },
		{ label: 'Документы', icon: '▣' },
		{ label: 'AI-помощник', icon: '✧' },
		{ label: 'Шаблоны', icon: '▤' },
		{ label: 'Черновики', icon: '◈' },
		{ label: 'История', icon: '◷' },
		{ label: 'Аналитика', icon: '⌁' },
		{ label: 'Команда', icon: '♧' },
		{ label: 'Настройки', icon: '⚙' }
	];

	const sourceSets = {
		procurement: [
		{ title: 'Регламент закупок', meta: 'Регламент · v3.2 · Отдел закупок', score: '98% релев.' },
		{ title: 'Порядок согласования договоров', meta: 'Порядок · v2.4 · Отдел закупок', score: '94% релев.' },
		{ title: 'Шаблон служебной записки', meta: 'Шаблон · v1.6 · Отдел закупок', score: '91% релев.' }
		],
		documentation: [
			{ title: 'Инструкция по документообороту', meta: 'Инструкция · v2.1 · ЦДО', score: '97% релев.' },
			{ title: 'Регламент регистрации документов', meta: 'Регламент · v1.8 · ЦДО', score: '93% релев.' },
			{ title: 'FAQ для сотрудников', meta: 'База знаний · v1.3 · ЦДО', score: '89% релев.' }
		],
		trip: [
			{ title: 'Положение о командировках', meta: 'Положение · v4.0 · HR', score: '96% релев.' },
			{ title: 'Порядок согласования поездок', meta: 'Порядок · v2.2 · Финансы', score: '92% релев.' },
			{ title: 'Заявка на командировку', meta: 'Шаблон · v2.0 · HR', score: '88% релев.' }
		]
	};
	let visibleSources: { title: string; meta: string; score: string }[] = [];

	function submitQuery() {
		if (!draft.trim()) return;
		query = draft;
		answeredQueries += 1;
		visibleSources = query.toLowerCase().includes('командир') ? sourceSets.trip : query.toLowerCase().includes('документ') ? sourceSets.documentation : sourceSets.procurement;
		draft = '';
		hasAnswer = true;
		isLoading = true;
		setTimeout(() => (isLoading = false), 900);
	}

	function startNewChat() {
		query = '';
		visibleSources = [];
		hasAnswer = false;
		draft = '';
	}

	function copyAnswer() {
		copied = true;
		setTimeout(() => (copied = false), 1500);
	}

	function openSource(title: string) {
		selectedDocument = title;
		activeNav = 'Документы';
	}
</script>

<svelte:head>
	<title>Свод — AI-помощник</title>
	<meta name="description" content="Внутренние знания и проверяемые ответы" />
</svelte:head>

<div class="app-shell">
	<aside class:mobile-open={showMenu} class="sidebar">
		<div class="brand"><span class="brand-mark">⌁</span><span class="brand-name">СВОД</span></div>
		<nav class="main-nav">
			{#each navItems as item}
				<button class:active={activeNav === item.label} onclick={() => { activeNav = item.label; showMenu = false; }}>
					<span class="nav-icon">{item.icon}</span><span>{item.label}</span>
				</button>
			{/each}
		</nav>
		<div class="divider"></div>
		<div class="privacy-card"><span class="shield">♢</span><strong>Внутренний контур</strong><small>Только доступные вам документы</small></div>
	</aside>

	<main class="content">
		<header class="topbar">
			<button class="mobile-menu" onclick={() => (showMenu = !showMenu)}>☰</button>
			<div class="search"><span>⌕</span><input placeholder="Поиск по документам, шаблонам и истории" /><kbd>⌘ K</kbd></div>
			<div class="top-actions"><button class="icon-btn">♧</button><span class="dot"></span><button class="profile-trigger" onclick={() => (showAuth = true)}><div class="avatar">⋯</div><div class="user-info"><strong>Профиль</strong><small>Войти или зарегистрироваться</small></div></button></div>
		</header>

		<div class="page-wrap">
			{#if activeNav === 'AI-помощник'}
			<div class="page-heading"><div><div class="eyebrow">01 / DESKTOP · ОТВЕТ С ИСТОЧНИКАМИ</div><h1>AI-помощник</h1><p>Внутренние знания. Проверяемые ответы.</p></div><button class="interactive-button ghost-button" onclick={startNewChat}>＋ Новый чат</button></div>

			<div class="layout-grid">
				<section class="conversation">
					<div class="greeting"><div class="sparkle">✧</div><div><strong>Добро пожаловать</strong><span>Задайте вопрос по внутренним документам и регламентам.</span></div></div>
					{#if query}
						<div class="question-meta">Ваш запрос</div><div class="question-bubble">{query}</div>
					{:else}
						<div class="question-bubble muted">Здесь появится ваш вопрос и проверяемый ответ с источниками.</div>
					{/if}

					{#if isLoading}
						<div class="answer-card loading-card"><div class="card-kicker"><span class="spinner"></span> Изучаю внутренние документы</div><p>Проверяю актуальность версий и собираю подтверждения для каждого шага.</p><div class="loading-lines"><i></i><i></i><i></i></div></div>
				{:else if hasAnswer}
					<div class="answer-card"><div class="card-kicker"><span class="teal-icon">✧</span> Свод AI <span class="verified">На основе 3 источников</span></div><h2>От потребности — к согласованию</h2><p>Для закупки оборудования подготовьте служебную записку. Вот порядок действий по действующим документам:</p>
						<div class="steps">
							<div class="step"><span>1</span><div><strong>Обоснуйте потребность</strong><p>Укажите оборудование, количество и цель закупки. Объясните, какую задачу решит приобретение.</p><small>Регламент закупок · п. 4.1 ↗</small></div></div>
							<div class="step"><span>2</span><div><strong>Заполните служебную записку</strong><p>Используйте шаблон ЗАК-01: добавьте обоснование, ориентировочную сумму и подразделение.</p><small>Шаблон служебной записки · v1.6 ↗</small></div></div>
							<div class="step"><span>3</span><div><strong>Приложите подтверждающие материалы</strong><p>Добавьте коммерческое предложение и технические требования. Проверьте комплектность вложений.</p><small>Регламент закупок · п. 4.3 ↗</small></div></div>
							<div class="step"><span>4</span><div><strong>Передайте на согласование</strong><p>Маршрут: руководитель подразделения → финансовый отдел → отдел закупок. После согласования передайте на исполнение.</p><small>Порядок согласования договоров · п. 2.2 ↗</small></div></div>
						</div>
						<div class="answer-actions"><button class="interactive-button secondary">▤ Открыть шаблон</button><button class="interactive-button primary" onclick={() => (draft = 'Создать черновик служебной записки')}>✧ Создать черновик</button><button class="interactive-button secondary route">⌁ Показать маршрут</button></div>
						<div class="feedback"><span>Ответ был полезен?</span><div><button class:copied class="tiny" onclick={copyAnswer}>♧ {copied ? 'Скопировано' : 'Да, спасибо'}</button><button class="tiny">♧</button><button class="tiny">▣</button></div></div>
					</div>
				{:else}
					<div class="welcome-card"><div class="welcome-symbol">✧</div><h2>С чего начнём?</h2><p>Задайте вопрос о внутренних процессах. Я найду нужные документы, покажу источники и помогу подготовить черновик.</p><div><button class="interactive-button secondary">⌕ Найти документ</button><button class="interactive-button secondary">▤ Выбрать шаблон</button></div></div>
				{/if}

					<div class="composer"><textarea bind:value={draft} onkeydown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), submitQuery())} placeholder="Задайте уточняющий вопрос..."></textarea><div class="composer-bottom"><button class="attach">⌕ Прикрепить файл</button><button class="interactive-button primary send" onclick={submitQuery}>↥ Отправить</button></div></div>
					<p class="disclaimer">AI использует только документы в пределах вашего доступа.</p><p class="demo-note">Ответ сверяйте с действующей версией документа.</p>
				</section>

				<aside class="right-rail">
					<div class="rail-card"><h3>▥ Источники ответа</h3>{#if visibleSources.length}<p class="rail-caption">{visibleSources.length} документа · действующие версии</p>{#each visibleSources as source}<button class="source-item" onclick={() => openSource(source.title)}><div><strong>{source.title}</strong><small>{source.meta}</small></div><div class="source-foot"><span>Действует</span><em>{source.score}</em></div><span class="source-open">Открыть документ ↗</span></button>{/each}<p class="rail-caption">Нажмите на источник, чтобы открыть документ.</p>{:else}<div class="empty-rail">Источники появятся после первого вопроса.</div>{/if}</div>
					<div class="rail-card compact"><h3>⌁ Быстрые действия</h3><button class="interactive-button" onclick={() => (activeNav = 'Документы')}>Открыть документы <span>↗</span></button><button class="interactive-button" onclick={() => (activeNav = 'Шаблоны')}>Выбрать шаблон <span>↗</span></button></div>
				</aside>
			</div>
			{:else}
				<div class="page-heading"><div><div class="eyebrow">02 / WORKSPACE · {activeNav.toUpperCase()}</div><h1>{activeNav}</h1><p>Рабочее пространство внутренних документов и процессов.</p></div><button class="interactive-button ghost-button" onclick={() => (activeNav = 'AI-помощник')}>✧ К AI-помощнику</button></div>
				<div class="workspace-grid">
					<section class="workspace-main">
						<div class="workspace-banner"><span class="workspace-icon">{navItems.find((item) => item.label === activeNav)?.icon}</span><div><strong>{activeNav === 'Документы' ? 'Единый каталог документов' : activeNav === 'Шаблоны' ? 'Шаблоны для ежедневной работы' : activeNav === 'Черновики' ? 'Черновики и подготовленные материалы' : activeNav === 'История' ? 'История запросов и ответов' : activeNav === 'Аналитика' ? 'Аналитика использования знаний' : activeNav === 'Команда' ? 'Команда и уровни доступа' : 'Настройки рабочего пространства'}</strong><p>Здесь можно продолжить работу с внутренними материалами.</p></div></div>
						{#if activeNav === 'Документы'}
							{#if selectedDocument}<div class="document-detail"><button class="back-link" onclick={() => (selectedDocument = '')}>← Все документы</button><div class="document-detail-head"><span class="document-icon">▣</span><div><h2>{selectedDocument}</h2><p>Источник ответа · действующая версия</p></div><span class="status-chip">Действует</span></div><div class="document-detail-body"><h3>О документе</h3><p>Документ открыт из ответа AI. Здесь сотрудник может ознакомиться с полным содержанием, реквизитами и связанными разделами.</p><div class="detail-placeholder">Содержимое документа появится после подключения хранилища документов.</div></div></div>{:else}<div class="document-list"><div class="empty-rail">Документы появятся после подключения рабочего пространства.</div></div>{/if}
						{:else if activeNav === 'Шаблоны'}
							<div class="template-grid"><div class="template-card"><span>▤</span><strong>Служебная записка</strong><small>ЗАК-01 · Активен</small><button class="interactive-button secondary" onclick={() => { activeNav = 'AI-помощник'; draft = 'Создать черновик служебной записки'; }}>Использовать</button></div><div class="template-card"><span>▤</span><strong>Заявка на командировку</strong><small>КОМ-02 · Активен</small><button class="interactive-button secondary" onclick={() => { activeNav = 'AI-помощник'; draft = 'Подготовить заявку на командировку'; }}>Использовать</button></div></div>
						{:else if activeNav === 'Черновики'}
							<div class="draft-preview"><span class="teal-icon">◈</span><div><h2>Служебная записка на закупку оборудования</h2><p>Подготовлено на основе ответа AI · ещё не отправлено на согласование</p></div><button class="interactive-button primary" onclick={() => (activeNav = 'AI-помощник')}>Открыть</button></div>
						{:else}
							<div class="metrics-empty"><p>Показатели читаются автоматически из текущей сессии.</p><div class="metric-fields"><label>Ответов за период<input value={answeredQueries || '—'} readonly /></label><label>Релевантность<input value={answeredQueries ? 'Считается' : '—'} readonly /></label><label>Среднее время поиска<input value={answeredQueries ? 'Считается' : '—'} readonly /></label></div></div>
						{/if}
					</section>
					<aside class="rail-card context-card"><h3>⌁ Быстрые действия</h3><button class="interactive-button" onclick={() => (activeNav = 'AI-помощник')}>Задать вопрос AI <span>↗</span></button><button class="interactive-button" onclick={() => (activeNav = 'Документы')}>Открыть документы <span>↗</span></button><button class="interactive-button" onclick={() => (activeNav = 'Шаблоны')}>Выбрать шаблон <span>↗</span></button></aside>
				</div>
			{/if}
		</div>
	</main>
	{#if showAuth}
		<div class="auth-backdrop" role="presentation" onclick={(event) => event.target === event.currentTarget && (showAuth = false)}>
			<div class="auth-card" role="dialog" aria-modal="true" aria-label="Регистрация">
				<button class="auth-close" aria-label="Закрыть" onclick={() => (showAuth = false)}>×</button>
				<div class="auth-mark">⌁</div><div class="eyebrow">СВОД · ВНУТРЕННИЙ КОНТУР</div>
				<h2>{authMode === 'register' ? 'Создать аккаунт' : 'Войти в Свод'}</h2><p>Получите доступ к рабочему пространству и внутренним документам.</p>
				{#if authMode === 'register'}<label>Имя<input placeholder="Ваше имя" /></label>{/if}<label>Рабочая почта<input type="email" placeholder="name@company.ru" /></label><label>Пароль<input type="password" placeholder="Не менее 8 символов" /></label>
				<button class="interactive-button primary auth-submit" onclick={() => (showAuth = false)}>{authMode === 'register' ? 'Зарегистрироваться' : 'Войти'}</button>
				<button class="auth-switch" onclick={() => (authMode = authMode === 'register' ? 'login' : 'register')}>{authMode === 'register' ? 'Уже есть аккаунт? Войти' : 'Нет аккаунта? Зарегистрироваться'}</button>
			</div>
		</div>
	{/if}
</div>

<style>
	:global(*) { box-sizing: border-box; }
	:global(body) { margin: 0; background: #070d1a; color: #e7edf7; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 13px; }
	:global(button), :global(input), :global(textarea) { font: inherit; }
	.app-shell { min-height: 100vh; display: flex; background: radial-gradient(ellipse at 55% -10%, #14213d 0%, #080e1a 48%, #060b15 100%); }
	.sidebar { width: 238px; min-width: 238px; border-right: 1px solid #1a2945; background: rgba(9,16,31,.88); padding: 27px 16px 20px; display: flex; flex-direction: column; }
	.brand { display: flex; gap: 10px; align-items: center; margin: 4px 5px 31px; }.brand-mark { width: 28px; height: 28px; border: 1px solid #2dd6cb; color: #64ece2; border-radius: 9px; display: grid; place-items: center; font-size: 23px; line-height: 1; }.brand-name { font-size: 15px; letter-spacing: .08em; font-weight: 600; }
	.main-nav { display: grid; gap: 4px; }.main-nav button { border: 0; background: transparent; color: #9eacc3; display: flex; align-items: center; gap: 12px; text-align: left; padding: 9px 10px; border-radius: 7px; cursor: pointer; font-size: 12px; }.main-nav button:hover, .main-nav button.active { background: #16464b; color: #79eee6; }.nav-icon { width: 15px; text-align: center; color: inherit; font-size: 15px; }.divider { height: 1px; background: #1b2943; margin: 24px 4px 16px; }.privacy-card { margin-top: auto; background: #111d33; border: 1px solid #263855; border-radius: 8px; padding: 14px 11px; display: grid; gap: 5px; color: #91a1b6; }.privacy-card strong { color: #d9e3ef; font-size: 11px; }.privacy-card small { font-size: 9px; line-height: 1.45; }.shield { color: #47e0d5; font-size: 14px; }
	.content { flex: 1; min-width: 0; }.topbar { height: 69px; border-bottom: 1px solid #1c2940; display: flex; align-items: center; gap: 20px; padding: 0 28px; }.search { height: 34px; border: 1px solid #253757; background: #101c31; border-radius: 7px; display: flex; align-items: center; gap: 9px; padding: 0 10px; flex: 1; max-width: 560px; color: #7d8ea8; }.search input { border: 0; outline: 0; color: #dfe8f5; background: transparent; flex: 1; font-size: 11px; }.search input::placeholder { color: #74849a; }.search kbd { font-size: 9px; color: #6f819a; }.top-actions { margin-left: auto; display: flex; align-items: center; gap: 9px; }.icon-btn { background: transparent; color: #adbad0; border: 0; font-size: 16px; }.dot { width: 4px; height: 4px; background: #48dcd0; border-radius: 50%; }.avatar { width: 25px; height: 25px; display: grid; place-items: center; border-radius: 50%; background: #17294b; border: 1px solid #2b426b; color: #93c5e7; font-size: 9px; }.user-info { display: grid; gap: 2px; }.user-info strong { font-size: 10px; }.user-info small { color: #73839b; font-size: 8px; }.mobile-menu { display:none; }
	.page-wrap { max-width: 1190px; margin: 0 auto; padding: 29px 30px 50px; }.page-heading { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 22px; }.eyebrow { font-size: 8px; color: #788aa5; letter-spacing: .06em; margin-bottom: 14px; }.page-heading h1 { margin: 0 0 5px; font-size: 19px; letter-spacing: -.02em; }.page-heading p { margin: 0; color: #8291a7; font-size: 10px; }.ghost-button, .secondary, .primary { border-radius: 6px; padding: 9px 13px; cursor: pointer; border: 1px solid #263957; color: #d4deed; background: #12213b; font-size: 10px; }.ghost-button:hover, .secondary:hover { border-color: #3d6388; }.primary { background: #58ded1; border-color: #58ded1; color: #071a25; font-weight: 650; }.layout-grid { display: grid; grid-template-columns: minmax(0, 1fr) 244px; gap: 20px; }.conversation { min-width: 0; }.greeting { border: 1px solid #2a3b59; background: linear-gradient(100deg, #15253c, #122039); border-radius: 8px; min-height: 59px; padding: 13px 16px; display: flex; align-items: center; gap: 12px; }.sparkle, .teal-icon { color: #63e6dd; background: #123c42; width: 30px; height: 30px; display: grid; place-items: center; border-radius: 8px; font-size: 18px; }.greeting strong { display: block; font-size: 11px; margin-bottom: 3px; }.greeting span { color: #8393a8; font-size: 9px; }.question-meta { text-align: right; font-size: 8px; color: #71829a; padding: 9px 9px 5px; }.question-bubble { background: #17243c; border: 1px solid #2b3e5d; border-radius: 8px; padding: 12px; font-size: 10px; margin-bottom: 10px; color: #e1e9f5; }.question-bubble.muted { margin-top: 9px; }.answer-card, .welcome-card { border: 1px solid #2b4262; background: linear-gradient(145deg, #111e34, #101b2e); border-radius: 13px; padding: 17px 17px 13px; }.card-kicker { color: #d6e0ef; font-size: 10px; display: flex; align-items: center; gap: 8px; }.teal-icon { width: 22px; height: 22px; font-size: 13px; border-radius: 6px; }.verified { margin-left: auto; color: #73e2d8; background: #124843; border-radius: 4px; padding: 4px 6px; font-size: 8px; }.answer-card h2, .welcome-card h2 { margin: 14px 0 8px; font-size: 16px; }.answer-card > p, .welcome-card p { color: #94a1b3; font-size: 10px; line-height: 1.55; margin: 0 0 15px; }.steps { display: grid; gap: 13px; }.step { display: grid; grid-template-columns: 21px 1fr; gap: 9px; }.step > span { background: #14504f; color: #73e5dc; height: 17px; width: 17px; border-radius: 5px; display:grid; place-items:center; font-size: 9px; margin-top: 1px; }.step strong { font-size: 10px; }.step p { color: #9aa8ba; font-size: 9px; line-height: 1.45; margin: 4px 0 2px; }.step small { color: #6ea7b1; font-size: 8px; }.answer-actions { display: flex; gap: 7px; margin-top: 15px; padding-top: 13px; border-top: 1px solid #20314c; }.answer-actions .secondary, .answer-actions .primary { padding: 8px 10px; }.feedback { display: flex; justify-content: space-between; align-items: center; color: #78899f; border-top: 1px solid #1c2c46; margin-top: 12px; padding-top: 10px; font-size: 9px; }.feedback > div { display: flex; gap: 4px; }.tiny { border: 0; color: #9cabc0; background: transparent; font-size: 9px; cursor: pointer; }.tiny.copied { color: #68e1d5; }.composer { margin-top: 12px; background: #111e33; border: 1px solid #293e5b; border-radius: 9px; padding: 10px 12px 8px; }.composer textarea { display: block; width: 100%; min-height: 27px; resize: vertical; border: 0; outline: 0; color: #dbe4f1; background: transparent; font-size: 10px; }.composer textarea::placeholder { color: #788ba4; }.composer-bottom { display: flex; justify-content: space-between; align-items: center; margin-top: 5px; }.attach { border: 0; background: transparent; color: #7d8da4; font-size: 9px; cursor: pointer; }.send { padding: 7px 14px; }.disclaimer, .demo-note { color: #6e7d92; font-size: 8px; margin: 9px 2px 0; }.demo-note { margin-top: 17px; }
	.right-rail { display: grid; align-content: start; gap: 10px; }.rail-card { background: #111e34; border: 1px solid #263a59; border-radius: 12px; padding: 13px 12px; }.rail-card h3 { margin: 0 0 9px; font-size: 11px; }.rail-caption { color: #788aa2; font-size: 8px; margin: 0 0 10px; line-height: 1.4; }.source-item { border: 1px solid #263957; background: #14233a; border-radius: 7px; padding: 10px 9px; margin-bottom: 7px; }.source-item strong { display: block; color: #dde7f3; font-size: 9px; margin-bottom: 4px; }.source-item small { color: #788ca6; font-size: 8px; }.source-foot { margin-top: 8px; display: flex; justify-content: space-between; align-items: center; }.source-foot span { color: #69e3d9; background: #104d4c; padding: 3px 5px; border-radius: 4px; font-size: 8px; }.source-foot em { font-style: normal; color: #70dcd1; font-size: 8px; }.compact h3 { color: #dbe6f1; }.compact button { width: 100%; background: transparent; border: 0; border-bottom: 1px solid #23344f; color: #9eacc1; padding: 8px 0; text-align: left; font-size: 9px; cursor:pointer; }.compact button:last-child { border-bottom: 0; }.compact button span { float: right; color: #b3c2d4; }.welcome-card { min-height: 240px; padding: 38px 24px; }.welcome-symbol { margin: 0 auto 12px; background: #124d54; width: 39px; height: 39px; border-radius: 12px; display: grid; place-items: center; color: #62e4dc; font-size: 20px; }.welcome-card h2 { font-size: 18px; }.welcome-card p { max-width: 620px; margin-bottom: 18px; }.loading-card { min-height: 225px; }.loading-card p { margin-top: 18px; }.spinner { width: 10px; height: 10px; border: 1px solid #68e1d8; border-top-color: transparent; border-radius: 50%; display:inline-block; animation: spin .8s linear infinite; }.loading-lines { display:grid; gap: 12px; margin-top: 28px; }.loading-lines i { height: 8px; width: 80%; background: #1d2d48; border-radius: 8px; display:block; }.loading-lines i:nth-child(2) { width: 100%; }.loading-lines i:nth-child(3) { width: 55%; } @keyframes spin { to { transform: rotate(360deg); } }
	.profile-trigger { border: 0; background: transparent; color: inherit; display: flex; align-items: center; gap: 8px; padding: 0; cursor: pointer; text-align: left; }.profile-trigger:hover .user-info strong { color: #69e3d9; }
	.empty-rail { border: 1px dashed #2a3b59; border-radius: 8px; padding: 15px 10px; color: #788ca6; font-size: 9px; line-height: 1.5; }.metrics-empty { background: #111e34; border: 1px solid #293e5b; border-radius: 12px; padding: 16px; }.metrics-empty > p { margin: 0 0 14px; color: #8797ab; font-size: 10px; }.metric-fields { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }.metric-fields label { display: grid; gap: 6px; color: #93a3b9; font-size: 9px; }.metric-fields input { min-width: 0; border: 1px solid #2a3f5d; border-radius: 7px; background: #0c172a; color: #e1e9f5; padding: 10px; outline: 0; }.metric-fields input:focus { border-color: #53d8ce; }
	.auth-backdrop { position: fixed; z-index: 30; inset: 0; background: rgba(3,8,17,.78); display: grid; place-items: center; padding: 18px; }.auth-card { position: relative; width: min(100%, 390px); background: #111e34; border: 1px solid #2d4668; border-radius: 14px; padding: 28px; box-shadow: 0 20px 60px rgba(0,0,0,.45); }.auth-close { position: absolute; top: 12px; right: 14px; border: 0; background: transparent; color: #8fa0b8; font-size: 22px; cursor: pointer; }.auth-mark { width: 38px; height: 38px; border: 1px solid #2dd6cb; color: #64ece2; border-radius: 11px; display: grid; place-items: center; font-size: 23px; margin-bottom: 17px; }.auth-card .eyebrow { margin-bottom: 7px; }.auth-card h2 { margin: 0 0 7px; font-size: 20px; }.auth-card > p { color: #8798ae; font-size: 10px; line-height: 1.5; margin: 0 0 20px; }.auth-card label { display: grid; gap: 6px; color: #a4b2c5; font-size: 10px; margin-top: 12px; }.auth-card input { border: 1px solid #2a3f5d; border-radius: 7px; background: #0c172a; color: #e1e9f5; padding: 10px 11px; outline: 0; }.auth-card input:focus { border-color: #53d8ce; }.auth-submit { width: 100%; margin-top: 21px; padding: 11px; }.auth-switch { display: block; margin: 14px auto 0; color: #68ddd4; border: 0; background: transparent; font-size: 10px; cursor: pointer; }
	/* Interactive hover button adapted from the requested component for Svelte. */
	.interactive-button { position: relative; overflow: hidden; isolation: isolate; min-width: 142px; border: 1px solid #315176; border-radius: 999px; background: #12213b; color: #dce8f4; padding: 9px 14px; font-size: 10px; font-weight: 650; cursor: pointer; transition: color .25s, border-color .25s, transform .25s; }.interactive-button::before { content: ''; position: absolute; z-index: -1; width: 0; height: 100%; left: 0; top: 0; border-radius: inherit; background: #58ded1; transition: all .3s ease; }.interactive-button:hover { color: #071a25; border-color: #58ded1; transform: translateY(-1px); }.interactive-button:hover::before { width: 100%; height: 100%; left: 0; top: 0; }	@media (max-width: 900px) { .sidebar { width: 205px; min-width: 205px; }.page-wrap { padding: 24px 18px 35px; }.layout-grid { grid-template-columns: minmax(0,1fr) 220px; }.user-info { display:none; }.topbar { padding: 0 18px; } }
	@media (max-width: 700px) { .sidebar { position: fixed; z-index: 10; left: -240px; top: 0; bottom: 0; transition: left .2s ease; box-shadow: 10px 0 30px rgba(0,0,0,.4); }.sidebar.mobile-open { left: 0; }.mobile-menu { display:block; border:0; color:#a8b7cc; background:transparent; font-size:18px; cursor:pointer; }.topbar { height: 58px; padding: 0 12px; gap: 9px; }.search { height: 31px; }.search kbd { display:none; }.top-actions { gap: 5px; }.icon-btn { display:none; }.page-wrap { padding: 20px 12px 30px; }.page-heading { align-items: flex-start; }.page-heading .ghost-button { padding: 7px 9px; }.layout-grid { display: block; }.workspace-grid { display: block; }.context-card { margin-top: 12px; }.template-grid { grid-template-columns: 1fr; }.metric-fields { grid-template-columns: 1fr; }.right-rail { margin-top: 12px; }.right-rail .rail-card:first-child { order: 0; }.answer-actions { flex-wrap: wrap; }.answer-actions .route { flex-basis: 100%; }.greeting { padding: 11px; }.question-bubble { line-height: 1.4; }.answer-card { padding: 14px 12px 11px; }.step p { font-size: 9px; }.welcome-card { padding: 28px 16px; min-height: 220px; } }
</style>



















