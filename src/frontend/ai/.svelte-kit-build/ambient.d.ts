
// this file is generated — do not edit it


/// <reference types="@sveltejs/kit" />

/**
 * Environment variables [loaded by Vite](https://vitejs.dev/guide/env-and-mode.html#env-files) from `.env` files and `process.env`. Like [`$env/dynamic/private`](https://svelte.dev/docs/kit/$env-dynamic-private), this module cannot be imported into client-side code. This module only includes variables that _do not_ begin with [`config.kit.env.publicPrefix`](https://svelte.dev/docs/kit/configuration#env) _and do_ start with [`config.kit.env.privatePrefix`](https://svelte.dev/docs/kit/configuration#env) (if configured).
 * 
 * _Unlike_ [`$env/dynamic/private`](https://svelte.dev/docs/kit/$env-dynamic-private), the values exported from this module are statically injected into your bundle at build time, enabling optimisations like dead code elimination.
 * 
 * ```ts
 * import { API_KEY } from '$env/static/private';
 * ```
 * 
 * Note that all environment variables referenced in your code should be declared (for example in an `.env` file), even if they don't have a value until the app is deployed:
 * 
 * ```
 * MY_FEATURE_FLAG=""
 * ```
 * 
 * You can override `.env` values from the command line like so:
 * 
 * ```sh
 * MY_FEATURE_FLAG="enabled" npm run dev
 * ```
 */
declare module '$env/static/private' {
	export const ALLUSERSPROFILE: string;
	export const AMDRMSDKPATH: string;
	export const APPDATA: string;
	export const BROWSER_USE_ACCESS_VERIFYING_IDENTITY: string;
	export const CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS: string;
	export const CODEX_APP_RUNTIME_CLI_PATH: string;
	export const CODEX_APP_TOOLS_PIPE_PATH: string;
	export const CODEX_CI: string;
	export const CODEX_INTERNAL_ORIGINATOR_OVERRIDE: string;
	export const CODEX_MCP_NODE_PATH: string;
	export const CODEX_PERMISSION_PROFILE: string;
	export const CODEX_SAGE_BACKFILL_TRACKER_TAB_REUSE: string;
	export const CODEX_SESSION_ID: string;
	export const CODEX_SHELL: string;
	export const CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY: string;
	export const CODEX_TECTONIC_PATH: string;
	export const CODEX_THREAD_ID: string;
	export const CODEX_TOOL_CALL_ID: string;
	export const CODEX_VERSION: string;
	export const CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY: string;
	export const COLOR: string;
	export const COLORTERM: string;
	export const CommonProgramFiles: string;
	export const CommonProgramW6432: string;
	export const COMPUTERNAME: string;
	export const ComSpec: string;
	export const DISABLE_AUTO_UPDATE: string;
	export const DriverData: string;
	export const EDITOR: string;
	export const GH_PAGER: string;
	export const GIT_PAGER: string;
	export const HOME: string;
	export const HOMEDRIVE: string;
	export const HOMEPATH: string;
	export const INIT_CWD: string;
	export const LANG: string;
	export const LC_ALL: string;
	export const LC_CTYPE: string;
	export const LOCALAPPDATA: string;
	export const LOGONSERVER: string;
	export const LOG_FORMAT: string;
	export const NODE: string;
	export const NODE_ENV: string;
	export const NO_COLOR: string;
	export const npm_command: string;
	export const npm_config_allow_scripts: string;
	export const npm_config_cache: string;
	export const npm_config_engine_strict: string;
	export const npm_config_globalconfig: string;
	export const npm_config_global_prefix: string;
	export const npm_config_init_module: string;
	export const npm_config_local_prefix: string;
	export const npm_config_node_gyp: string;
	export const npm_config_noproxy: string;
	export const npm_config_npm_version: string;
	export const npm_config_prefix: string;
	export const npm_config_userconfig: string;
	export const npm_config_user_agent: string;
	export const npm_execpath: string;
	export const npm_lifecycle_event: string;
	export const npm_lifecycle_script: string;
	export const npm_node_execpath: string;
	export const npm_package_json: string;
	export const npm_package_name: string;
	export const npm_package_version: string;
	export const NUMBER_OF_PROCESSORS: string;
	export const OneDrive: string;
	export const OS: string;
	export const PAGER: string;
	export const Path: string;
	export const PATHEXT: string;
	export const PROCESSOR_ARCHITECTURE: string;
	export const PROCESSOR_IDENTIFIER: string;
	export const PROCESSOR_LEVEL: string;
	export const PROCESSOR_REVISION: string;
	export const ProgramData: string;
	export const ProgramFiles: string;
	export const ProgramW6432: string;
	export const PROMPT: string;
	export const PSModulePath: string;
	export const PUBLIC: string;
	export const RUST_LOG: string;
	export const SHELL: string;
	export const SystemDrive: string;
	export const SystemRoot: string;
	export const TEMP: string;
	export const TERM: string;
	export const TMP: string;
	export const USERDOMAIN: string;
	export const USERDOMAIN_ROAMINGPROFILE: string;
	export const USERNAME: string;
	export const USERPROFILE: string;
	export const windir: string;
	export const ZSH_TMUX_AUTOSTART: string;
	export const ZSH_TMUX_AUTOSTARTED: string;
}

/**
 * Similar to [`$env/static/private`](https://svelte.dev/docs/kit/$env-static-private), except that it only includes environment variables that begin with [`config.kit.env.publicPrefix`](https://svelte.dev/docs/kit/configuration#env) (which defaults to `PUBLIC_`), and can therefore safely be exposed to client-side code.
 * 
 * Values are replaced statically at build time.
 * 
 * ```ts
 * import { PUBLIC_BASE_URL } from '$env/static/public';
 * ```
 */
declare module '$env/static/public' {
	
}

/**
 * This module provides access to runtime environment variables, as defined by the platform you're running on. For example if you're using [`adapter-node`](https://github.com/sveltejs/kit/tree/main/packages/adapter-node) (or running [`vite preview`](https://svelte.dev/docs/kit/cli)), this is equivalent to `process.env`. This module only includes variables that _do not_ begin with [`config.kit.env.publicPrefix`](https://svelte.dev/docs/kit/configuration#env) _and do_ start with [`config.kit.env.privatePrefix`](https://svelte.dev/docs/kit/configuration#env) (if configured).
 * 
 * This module cannot be imported into client-side code.
 * 
 * ```ts
 * import { env } from '$env/dynamic/private';
 * console.log(env.DEPLOYMENT_SPECIFIC_VARIABLE);
 * ```
 * 
 * > [!NOTE] In `dev`, `$env/dynamic` always includes environment variables from `.env`. In `prod`, this behavior will depend on your adapter.
 */
declare module '$env/dynamic/private' {
	export const env: {
		ALLUSERSPROFILE: string;
		AMDRMSDKPATH: string;
		APPDATA: string;
		BROWSER_USE_ACCESS_VERIFYING_IDENTITY: string;
		CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS: string;
		CODEX_APP_RUNTIME_CLI_PATH: string;
		CODEX_APP_TOOLS_PIPE_PATH: string;
		CODEX_CI: string;
		CODEX_INTERNAL_ORIGINATOR_OVERRIDE: string;
		CODEX_MCP_NODE_PATH: string;
		CODEX_PERMISSION_PROFILE: string;
		CODEX_SAGE_BACKFILL_TRACKER_TAB_REUSE: string;
		CODEX_SESSION_ID: string;
		CODEX_SHELL: string;
		CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY: string;
		CODEX_TECTONIC_PATH: string;
		CODEX_THREAD_ID: string;
		CODEX_TOOL_CALL_ID: string;
		CODEX_VERSION: string;
		CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY: string;
		COLOR: string;
		COLORTERM: string;
		CommonProgramFiles: string;
		CommonProgramW6432: string;
		COMPUTERNAME: string;
		ComSpec: string;
		DISABLE_AUTO_UPDATE: string;
		DriverData: string;
		EDITOR: string;
		GH_PAGER: string;
		GIT_PAGER: string;
		HOME: string;
		HOMEDRIVE: string;
		HOMEPATH: string;
		INIT_CWD: string;
		LANG: string;
		LC_ALL: string;
		LC_CTYPE: string;
		LOCALAPPDATA: string;
		LOGONSERVER: string;
		LOG_FORMAT: string;
		NODE: string;
		NODE_ENV: string;
		NO_COLOR: string;
		npm_command: string;
		npm_config_allow_scripts: string;
		npm_config_cache: string;
		npm_config_engine_strict: string;
		npm_config_globalconfig: string;
		npm_config_global_prefix: string;
		npm_config_init_module: string;
		npm_config_local_prefix: string;
		npm_config_node_gyp: string;
		npm_config_noproxy: string;
		npm_config_npm_version: string;
		npm_config_prefix: string;
		npm_config_userconfig: string;
		npm_config_user_agent: string;
		npm_execpath: string;
		npm_lifecycle_event: string;
		npm_lifecycle_script: string;
		npm_node_execpath: string;
		npm_package_json: string;
		npm_package_name: string;
		npm_package_version: string;
		NUMBER_OF_PROCESSORS: string;
		OneDrive: string;
		OS: string;
		PAGER: string;
		Path: string;
		PATHEXT: string;
		PROCESSOR_ARCHITECTURE: string;
		PROCESSOR_IDENTIFIER: string;
		PROCESSOR_LEVEL: string;
		PROCESSOR_REVISION: string;
		ProgramData: string;
		ProgramFiles: string;
		ProgramW6432: string;
		PROMPT: string;
		PSModulePath: string;
		PUBLIC: string;
		RUST_LOG: string;
		SHELL: string;
		SystemDrive: string;
		SystemRoot: string;
		TEMP: string;
		TERM: string;
		TMP: string;
		USERDOMAIN: string;
		USERDOMAIN_ROAMINGPROFILE: string;
		USERNAME: string;
		USERPROFILE: string;
		windir: string;
		ZSH_TMUX_AUTOSTART: string;
		ZSH_TMUX_AUTOSTARTED: string;
		[key: `PUBLIC_${string}`]: undefined;
		[key: `${string}`]: string | undefined;
	}
}

/**
 * Similar to [`$env/dynamic/private`](https://svelte.dev/docs/kit/$env-dynamic-private), but only includes variables that begin with [`config.kit.env.publicPrefix`](https://svelte.dev/docs/kit/configuration#env) (which defaults to `PUBLIC_`), and can therefore safely be exposed to client-side code.
 * 
 * Note that public dynamic environment variables must all be sent from the server to the client, causing larger network requests — when possible, use `$env/static/public` instead.
 * 
 * ```ts
 * import { env } from '$env/dynamic/public';
 * console.log(env.PUBLIC_DEPLOYMENT_SPECIFIC_VARIABLE);
 * ```
 */
declare module '$env/dynamic/public' {
	export const env: {
		[key: `PUBLIC_${string}`]: string | undefined;
	}
}
