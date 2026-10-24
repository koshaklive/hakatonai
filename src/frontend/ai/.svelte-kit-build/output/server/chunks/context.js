var is_array = Array.isArray;
var index_of = Array.prototype.indexOf;
var includes = Array.prototype.includes;
var array_from = Array.from;
var define_property = Object.defineProperty;
var get_descriptor = Object.getOwnPropertyDescriptor;
var object_prototype = Object.prototype;
var array_prototype = Array.prototype;
var get_prototype_of = Object.getPrototypeOf;
var is_extensible = Object.isExtensible;
var has_own_property = Object.prototype.hasOwnProperty;
const noop = () => {
};
function run_all(arr) {
  for (var i = 0; i < arr.length; i++) {
    arr[i]();
  }
}
function deferred() {
  var resolve;
  var reject;
  var promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
function lifecycle_outside_component(name) {
  {
    throw new Error(`https://svelte.dev/e/lifecycle_outside_component`);
  }
}
function set_context_after_init() {
  {
    throw new Error(`https://svelte.dev/e/set_context_after_init`);
  }
}
function get_parent_context(context) {
  let parent = context.p;
  while (parent !== null && parent.c === null) {
    parent = parent.p;
  }
  return parent?.c ?? null;
}
function get_or_init_context_map(context, name) {
  if (context === null) {
    lifecycle_outside_component();
  }
  return context.c ??= new Map(get_parent_context(context) || void 0);
}
const ATTR_REGEX = /[&"<]/g;
const CONTENT_REGEX = /[&<]/g;
function escape_html(value, is_attr) {
  const str = String(value ?? "");
  const pattern = is_attr ? ATTR_REGEX : CONTENT_REGEX;
  pattern.lastIndex = 0;
  let escaped = "";
  let last = 0;
  while (pattern.test(str)) {
    const i = pattern.lastIndex - 1;
    const ch = str[i];
    escaped += str.substring(last, i) + (ch === "&" ? "&amp;" : ch === '"' ? "&quot;" : "&lt;");
    last = i + 1;
  }
  return escaped + str.substring(last);
}
var ssr_context = null;
function set_ssr_context(v) {
  ssr_context = v;
}
function getContext(key) {
  const context_map = get_or_init_context_map(ssr_context);
  const result = (
    /** @type {T} */
    context_map.get(key)
  );
  return result;
}
function setContext(key, context) {
  const context_map = get_or_init_context_map(ssr_context);
  if (
    /** @type {SSRContext} */
    ssr_context.i
  ) {
    set_context_after_init();
  }
  context_map.set(key, context);
  return context;
}
function push(fn) {
  ssr_context = { p: ssr_context, c: null, r: null, i: false };
}
function pop() {
  ssr_context = /** @type {SSRContext} */
  ssr_context.p;
}
export {
  array_prototype as a,
  get_descriptor as b,
  get_prototype_of as c,
  define_property as d,
  escape_html as e,
  is_extensible as f,
  getContext as g,
  deferred as h,
  is_array as i,
  includes as j,
  index_of as k,
  array_from as l,
  has_own_property as m,
  noop as n,
  object_prototype as o,
  set_ssr_context as p,
  ssr_context as q,
  run_all as r,
  setContext as s,
  push as t,
  pop as u
};
