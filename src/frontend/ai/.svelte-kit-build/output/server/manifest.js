export const manifest = (() => {
function __memo(fn) {
	let value;
	return () => value ??= (value = fn());
}

return {
	appDir: "_app",
	appPath: "_app",
	assets: new Set(["robots.txt"]),
	mimeTypes: {".txt":"text/plain"},
	_: {
		client: {start:"_app/immutable/entry/start.CitvYdIW.js",app:"_app/immutable/entry/app.DhBqCxP3.js",imports:["_app/immutable/entry/start.CitvYdIW.js","_app/immutable/chunks/C88SWEr8.js","_app/immutable/chunks/X8EX51-p.js","_app/immutable/chunks/Cu0ZCgWt.js","_app/immutable/chunks/Dcop2j6Y.js","_app/immutable/entry/app.DhBqCxP3.js","_app/immutable/chunks/Cu0ZCgWt.js","_app/immutable/chunks/Dcop2j6Y.js","_app/immutable/chunks/Bzak7iHL.js","_app/immutable/chunks/X8EX51-p.js","_app/immutable/chunks/DP6Ep70N.js","_app/immutable/chunks/VSt3sRT2.js"],stylesheets:[],fonts:[],uses_env_dynamic_public:false},
		nodes: [
			__memo(() => import('./nodes/0.js')),
			__memo(() => import('./nodes/1.js')),
			__memo(() => import('./nodes/2.js'))
		],
		remotes: {
			
		},
		routes: [
			{
				id: "/",
				pattern: /^\/$/,
				params: [],
				page: { layouts: [0,], errors: [1,], leaf: 2 },
				endpoint: null
			}
		],
		prerendered_routes: new Set([]),
		matchers: async () => {
			
			return {  };
		},
		server_assets: {}
	}
}
})();
