// Минимальный безопасный Markdown → HTML без зависимостей.
// Весь ввод сначала экранируется, HTML создаётся только этим модулем.
// Ссылки на пункты вида [п. 4.2] / [пп. 4.2, 4.3] превращаются в кнопки с data-point.

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

const POINT = /^\d+(?:\.\d+)*$/;
const CITATION = /\[(?:пункты?|пп?\.?)\s*([^\][]+?)\]/gi;

function inline(raw: string): string {
	const stash: string[] = [];
	const keep = (html: string) => `\u0000${stash.push(html) - 1}\u0000`;
	let s = esc(raw).replace(/`([^`\n]+)`/g, (_, code) => keep(`<code>${code}</code>`));

	s = s.replace(CITATION, (whole, inner: string) => {
		const points = inner.split(/\s*[,;]\s*/).map((p) => p.trim());
		if (!points.length || !points.every((p) => POINT.test(p))) return whole;
		return points.map((p) => keep(`<button type="button" class="cite" data-point="${p}">п. ${p}</button>`)).join(' ');
	});
	s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, text, url) => keep(`<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`));
	s = s.replace(/\*\*([^*\n]+?)\*\*/g, '<strong>$1</strong>').replace(/(^|[^*\w])\*([^*\s][^*\n]*?)\*(?![*\w])/g, '$1<em>$2</em>');
	return s.replace(/\u0000(\d+)\u0000/g, (_, i) => stash[Number(i)]);
}

export function renderMarkdown(text: string): string {
	const lines = text.replace(/\u0000/g, '').replace(/\r\n?/g, '\n').split('\n');
	const out: string[] = [];
	let para: string[] = [];
	let list: { tag: 'ul' | 'ol'; start: number; items: string[] } | null = null;
	let fence: string[] | null = null;

	const flushPara = () => {
		if (para.length) out.push(`<p>${para.map(inline).join('<br>')}</p>`);
		para = [];
	};
	const flushList = () => {
		if (list) {
			const start = list.tag === 'ol' && list.start !== 1 ? ` start="${list.start}"` : '';
			out.push(`<${list.tag}${start}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`);
		}
		list = null;
	};

	for (const line of lines) {
		if (fence) {
			if (/^\s*```/.test(line)) {
				out.push(`<pre><code>${esc(fence.join('\n'))}</code></pre>`);
				fence = null;
			} else fence.push(line);
			continue;
		}
		if (/^\s*```/.test(line)) {
			flushPara();
			flushList();
			fence = [];
			continue;
		}
		const heading = /^(#{1,4})\s+(.+?)\s*#*$/.exec(line);
		const ul = /^\s*[-*•]\s+(.*)$/.exec(line);
		const ol = /^\s*(\d+)[.)]\s+(.*)$/.exec(line);
		if (heading) {
			flushPara();
			flushList();
			const level = heading[1].length + 2;
			out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
		} else if (ul || ol) {
			flushPara();
			const tag = ul ? 'ul' : 'ol';
			if (list && list.tag !== tag) flushList();
			if (!list) list = { tag, start: ol ? Number(ol[1]) : 1, items: [] };
			list.items.push(ul ? ul[1] : ol![2]);
		} else if (!line.trim()) {
			flushPara();
			flushList();
		} else if (list && /^\s+\S/.test(line)) {
			list.items[list.items.length - 1] += ' ' + line.trim();
		} else {
			flushList();
			para.push(line.trim());
		}
	}
	if (fence) out.push(`<pre><code>${esc(fence.join('\n'))}</code></pre>`);
	flushPara();
	flushList();
	return out.join('');
}

// «4.2», «п. 4.2», «4.2.» → «4.2» — для сопоставления ссылки в тексте с источником из ответа
export function normalizePoint(p: string): string {
	return p.replace(/[^\d.]/g, '').replace(/^\.+|\.+$/g, '');
}
