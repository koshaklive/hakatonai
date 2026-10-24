import { K as head, O as attr_class, Q as ensure_array_like } from "../../chunks/index.js";
import { e as escape_html } from "../../chunks/context.js";
function _page($$renderer, $$props) {
  $$renderer.component(($$renderer2) => {
    let activeNav = "AI-помощник";
    let draft = "";
    let showMenu = false;
    const navItems = [
      { label: "Главная", icon: "⌂" },
      { label: "Документы", icon: "▣" },
      { label: "AI-помощник", icon: "✧" },
      { label: "Шаблоны", icon: "▤" },
      { label: "Черновики", icon: "◈" },
      { label: "История", icon: "◷" },
      { label: "Аналитика", icon: "⌁" },
      { label: "Команда", icon: "♧" },
      { label: "Настройки", icon: "⚙" }
    ];
    let visibleSources = [];
    head("1uha8ag", $$renderer2, ($$renderer3) => {
      $$renderer3.title(($$renderer4) => {
        $$renderer4.push(`<title>Свод — AI-помощник</title>`);
      });
      $$renderer3.push(`<meta name="description" content="Внутренние знания и проверяемые ответы"/>`);
    });
    $$renderer2.push(`<div class="app-shell svelte-1uha8ag"><aside${attr_class("sidebar svelte-1uha8ag", void 0, { "mobile-open": showMenu })}><div class="brand svelte-1uha8ag"><span class="brand-mark svelte-1uha8ag">⌁</span><span class="brand-name svelte-1uha8ag">СВОД</span></div> <nav class="main-nav svelte-1uha8ag"><!--[-->`);
    const each_array = ensure_array_like(navItems);
    for (let $$index = 0, $$length = each_array.length; $$index < $$length; $$index++) {
      let item = each_array[$$index];
      $$renderer2.push(`<button${attr_class("svelte-1uha8ag", void 0, { "active": activeNav === item.label })}><span class="nav-icon svelte-1uha8ag">${escape_html(item.icon)}</span><span>${escape_html(item.label)}</span></button>`);
    }
    $$renderer2.push(`<!--]--></nav> <div class="divider svelte-1uha8ag"></div> <div class="privacy-card svelte-1uha8ag"><span class="shield svelte-1uha8ag">♢</span><strong class="svelte-1uha8ag">Внутренний контур</strong><small class="svelte-1uha8ag">Только доступные вам документы</small></div></aside> <main class="content svelte-1uha8ag"><header class="topbar svelte-1uha8ag"><button class="mobile-menu svelte-1uha8ag">☰</button> <div class="search svelte-1uha8ag"><span>⌕</span><input placeholder="Поиск по документам, шаблонам и истории" class="svelte-1uha8ag"/><kbd class="svelte-1uha8ag">⌘ K</kbd></div> <div class="top-actions svelte-1uha8ag"><button class="icon-btn svelte-1uha8ag">♧</button><span class="dot svelte-1uha8ag"></span><button class="profile-trigger svelte-1uha8ag"><div class="avatar svelte-1uha8ag">⋯</div><div class="user-info svelte-1uha8ag"><strong class="svelte-1uha8ag">Профиль</strong><small class="svelte-1uha8ag">Войти или зарегистрироваться</small></div></button></div></header> <div class="page-wrap svelte-1uha8ag">`);
    {
      $$renderer2.push(`<!--[0--><div class="page-heading svelte-1uha8ag"><div><div class="eyebrow svelte-1uha8ag">01 / DESKTOP · ОТВЕТ С ИСТОЧНИКАМИ</div><h1 class="svelte-1uha8ag">AI-помощник</h1><p class="svelte-1uha8ag">Внутренние знания. Проверяемые ответы.</p></div><button class="interactive-button ghost-button svelte-1uha8ag">＋ Новый чат</button></div> <div class="layout-grid svelte-1uha8ag"><section class="conversation svelte-1uha8ag"><div class="greeting svelte-1uha8ag"><div class="sparkle svelte-1uha8ag">✧</div><div><strong class="svelte-1uha8ag">Добро пожаловать</strong><span class="svelte-1uha8ag">Задайте вопрос по внутренним документам и регламентам.</span></div></div> `);
      {
        $$renderer2.push(`<!--[-1--><div class="question-bubble muted svelte-1uha8ag">Здесь появится ваш вопрос и проверяемый ответ с источниками.</div>`);
      }
      $$renderer2.push(`<!--]--> `);
      {
        $$renderer2.push(`<!--[-1--><div class="welcome-card svelte-1uha8ag"><div class="welcome-symbol svelte-1uha8ag">✧</div><h2 class="svelte-1uha8ag">С чего начнём?</h2><p class="svelte-1uha8ag">Задайте вопрос о внутренних процессах. Я найду нужные документы, покажу источники и помогу подготовить черновик.</p><div><button class="interactive-button secondary svelte-1uha8ag">⌕ Найти документ</button><button class="interactive-button secondary svelte-1uha8ag">▤ Выбрать шаблон</button></div></div>`);
      }
      $$renderer2.push(`<!--]--> <div class="composer svelte-1uha8ag"><textarea placeholder="Задайте уточняющий вопрос..." class="svelte-1uha8ag">`);
      const $$body = escape_html(draft);
      if ($$body) {
        $$renderer2.push(`${$$body}`);
      }
      $$renderer2.push(`</textarea><div class="composer-bottom svelte-1uha8ag"><button class="attach svelte-1uha8ag">⌕ Прикрепить файл</button><button class="interactive-button primary send svelte-1uha8ag">↥ Отправить</button></div></div> <p class="disclaimer svelte-1uha8ag">AI использует только документы в пределах вашего доступа.</p><p class="demo-note svelte-1uha8ag">Ответ сверяйте с действующей версией документа.</p></section> <aside class="right-rail svelte-1uha8ag"><div class="rail-card svelte-1uha8ag"><h3 class="svelte-1uha8ag">▥ Источники ответа</h3>`);
      if (visibleSources.length) {
        $$renderer2.push(`<!--[0--><p class="rail-caption svelte-1uha8ag">${escape_html(visibleSources.length)} документа · действующие версии</p><!--[-->`);
        const each_array_1 = ensure_array_like(visibleSources);
        for (let $$index_1 = 0, $$length = each_array_1.length; $$index_1 < $$length; $$index_1++) {
          let source = each_array_1[$$index_1];
          $$renderer2.push(`<div class="source-item svelte-1uha8ag"><div><strong class="svelte-1uha8ag">${escape_html(source.title)}</strong><small class="svelte-1uha8ag">${escape_html(source.meta)}</small></div><div class="source-foot svelte-1uha8ag"><span class="svelte-1uha8ag">Действует</span><em class="svelte-1uha8ag">${escape_html(source.score)}</em></div></div>`);
        }
        $$renderer2.push(`<!--]--><p class="rail-caption svelte-1uha8ag">Релевантность обновляется вместе с запросом.</p>`);
      } else {
        $$renderer2.push(`<!--[-1--><div class="empty-rail svelte-1uha8ag">Источники появятся после первого вопроса.</div>`);
      }
      $$renderer2.push(`<!--]--></div> <div class="rail-card compact svelte-1uha8ag"><h3 class="svelte-1uha8ag">⌁ Быстрые действия</h3><button class="interactive-button svelte-1uha8ag">Открыть документы <span class="svelte-1uha8ag">↗</span></button><button class="interactive-button svelte-1uha8ag">Выбрать шаблон <span class="svelte-1uha8ag">↗</span></button></div></aside></div>`);
    }
    $$renderer2.push(`<!--]--></div></main> `);
    {
      $$renderer2.push("<!--[-1-->");
    }
    $$renderer2.push(`<!--]--></div>`);
  });
}
export {
  _page as default
};
