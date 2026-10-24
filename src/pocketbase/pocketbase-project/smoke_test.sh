#!/usr/bin/env bash
# Smoke-тест правил доступа PocketBase 0.40.x. Нужны: curl, jq.
# Запуск: ./smoke_test.sh   (читает ./.env, PB_URL по умолчанию http://localhost:8090)
set -uo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then set -a; . ./.env; set +a; fi

PB_URL="${PB_URL:-http://localhost:8090}"
for bin in curl jq; do command -v "$bin" >/dev/null || { echo "нужен $bin"; exit 2; }; done
for v in SEED_EMPLOYEE_PASSWORD SEED_METHODOLOGIST_PASSWORD SEED_ADMIN_PASSWORD SEED_BACKEND_PASSWORD; do
  [ -n "${!v:-}" ] || { echo "не задана $v"; exit 2; }
done
EMP_EMAIL="${SEED_EMPLOYEE_EMAIL:-employee@test.local}"
MET_EMAIL="${SEED_METHODOLOGIST_EMAIL:-methodologist@test.local}"
ADM_EMAIL="${SEED_ADMIN_EMAIL:-admin@test.local}"
BCK_EMAIL="${SEED_BACKEND_EMAIL:-backend@test.local}"

TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
PASS=0; FAIL=0; CODE=""; BODY=""; CLEAN=()

call() { # METHOD PATH TOKEN [JSON]
  local m="$1" p="$2" t="${3:-}" d="${4:-}"
  local a=(-s -o "$TMP" -w '%{http_code}' -X "$m" "$PB_URL$p" -H 'Content-Type: application/json')
  [ -n "$t" ] && a+=(-H "Authorization: $t")
  [ -n "$d" ] && a+=(-d "$d")
  CODE="$(curl "${a[@]}")"; BODY="$(cat "$TMP")"
}
expect() { # "описание" код1 [код2 ...]
  local name="$1"; shift
  for c in "$@"; do
    if [ "$CODE" = "$c" ]; then echo "  PASS  $name (HTTP $CODE)"; PASS=$((PASS+1)); return; fi
  done
  echo "  FAIL  $name — получен HTTP $CODE, ожидалось: $*"; echo "        $BODY" | cut -c1-300
  FAIL=$((FAIL+1))
}
login() { # email password -> "token id role"
  call POST /api/collections/users/auth-with-password "" "$(jq -n --arg i "$1" --arg p "$2" '{identity:$i,password:$p}')"
  echo "$BODY" | jq -r '[.token // "", .record.id // "", .record.role // ""] | @tsv'
}
enc() { jq -rn --arg v "$1" '$v|@uri'; }
track() { CLEAN+=("$1:$2"); }

echo "== 1. Логин тремя ролями + сервисный backend"
read -r E_TOK E_ID E_ROLE < <(login "$EMP_EMAIL" "$SEED_EMPLOYEE_PASSWORD")
read -r M_TOK M_ID M_ROLE < <(login "$MET_EMAIL" "$SEED_METHODOLOGIST_PASSWORD")
read -r A_TOK A_ID A_ROLE < <(login "$ADM_EMAIL" "$SEED_ADMIN_PASSWORD")
read -r B_TOK B_ID B_ROLE < <(login "$BCK_EMAIL" "$SEED_BACKEND_PASSWORD")
for pair in "employee:$E_TOK:$E_ROLE:employee" "methodologist:$M_TOK:$M_ROLE:methodologist" "admin:$A_TOK:$A_ROLE:admin" "backend:$B_TOK:$B_ROLE:admin"; do
  IFS=: read -r n tok role want <<<"$pair"
  if [ -n "$tok" ] && [ "$role" = "$want" ]; then echo "  PASS  логин $n (role=$role)"; PASS=$((PASS+1))
  else echo "  FAIL  логин $n (role='$role', ожидалось $want)"; FAIL=$((FAIL+1)); fi
done
if [ -z "$E_TOK" ] || [ -z "$M_TOK" ] || [ -z "$B_TOK" ]; then echo "Без токенов дальше нет смысла."; exit 1; fi

echo "== 2. chat_sessions"
call POST /api/collections/chat_sessions/records "$M_TOK" "$(jq -n --arg u "$M_ID" '{user:$u,title:"smoke methodologist",status:"active"}')"
expect "methodologist создаёт свою сессию" 200; M_SESS="$(echo "$BODY" | jq -r .id)"; track chat_sessions "$M_SESS"

call POST /api/collections/chat_sessions/records "$E_TOK" "$(jq -n --arg u "$E_ID" '{user:$u,title:"smoke employee",status:"active"}')"
expect "employee создаёт свою сессию" 200; E_SESS="$(echo "$BODY" | jq -r .id)"; track chat_sessions "$E_SESS"

call POST /api/collections/chat_sessions/records "$E_TOK" "$(jq -n --arg u "$M_ID" '{user:$u,title:"forged",status:"active"}')"
expect "employee НЕ создаёт сессию от имени другого" 400 403
[ "$CODE" = "200" ] && track chat_sessions "$(echo "$BODY" | jq -r .id)"

call GET "/api/collections/chat_sessions/records/$M_SESS" "$E_TOK"
expect "employee НЕ читает чужую сессию (view)" 404 403

call GET "/api/collections/chat_sessions/records?filter=$(enc "id=\"$M_SESS\"")" "$E_TOK"
if [ "$CODE" = "200" ] && [ "$(echo "$BODY" | jq -r .totalItems)" = "0" ]; then echo "  PASS  employee не видит чужую сессию в list"; PASS=$((PASS+1))
else echo "  FAIL  чужая сессия видна в list (HTTP $CODE)"; FAIL=$((FAIL+1)); fi

call GET "/api/collections/chat_sessions/records/$E_SESS" "$E_TOK"
expect "employee читает свою сессию" 200

echo "== 3. messages"
call POST /api/collections/messages/records "$M_TOK" "$(jq -n --arg s "$M_SESS" '{session:$s,role:"user",content:"smoke m"}')"
expect "methodologist пишет в свою сессию" 200; M_MSG="$(echo "$BODY" | jq -r .id)"; track messages "$M_MSG"

call POST /api/collections/messages/records "$E_TOK" "$(jq -n --arg s "$E_SESS" '{session:$s,role:"user",content:"smoke e"}')"
expect "employee пишет в свою сессию" 200; E_MSG="$(echo "$BODY" | jq -r .id)"; track messages "$E_MSG"

call POST /api/collections/messages/records "$E_TOK" "$(jq -n --arg s "$M_SESS" '{session:$s,role:"user",content:"hack"}')"
expect "employee НЕ создаёт message в чужой сессии" 400 403
[ "$CODE" = "200" ] && track messages "$(echo "$BODY" | jq -r .id)"

call GET "/api/collections/messages/records/$M_MSG" "$E_TOK"
expect "employee НЕ читает чужой message" 404 403

call POST /api/collections/messages/records "$B_TOK" "$(jq -n --arg s "$E_SESS" '{session:$s,role:"assistant",content:"ответ"}')"
expect "backend (admin) пишет assistant-message в сессию employee" 200; track messages "$(echo "$BODY" | jq -r .id)"

echo "== 4. generated_drafts / feedback / audit_log"
call GET "/api/collections/module_templates/records?perPage=1&filter=$(enc 'is_active=true')" "$E_TOK"
MOD_ID="$(echo "$BODY" | jq -r '.items[0].id // empty')"
if [ -n "$MOD_ID" ]; then
  call POST /api/collections/generated_drafts/records "$E_TOK" "$(jq -n --arg s "$E_SESS" --arg u "$E_ID" --arg m "$MOD_ID" '{session:$s,user:$u,module:$m,status:"filling"}')"
  expect "employee создаёт draft в своей сессии" 200; track generated_drafts "$(echo "$BODY" | jq -r .id)"
  call POST /api/collections/generated_drafts/records "$E_TOK" "$(jq -n --arg s "$M_SESS" --arg u "$E_ID" --arg m "$MOD_ID" '{session:$s,user:$u,module:$m,status:"filling"}')"
  expect "employee НЕ создаёт draft в чужой сессии" 400 403
  call POST /api/collections/generated_drafts/records "$E_TOK" "$(jq -n --arg s "$E_SESS" --arg u "$M_ID" --arg m "$MOD_ID" '{session:$s,user:$u,module:$m,status:"filling"}')"
  expect "employee НЕ создаёт draft с чужим user" 400 403
else
  echo "  FAIL  нет активных module_templates"; FAIL=$((FAIL+1))
fi

call POST /api/collections/feedback/records "$E_TOK" "$(jq -n --arg m "$E_MSG" --arg u "$E_ID" '{message:$m,user:$u,rating:"up"}')"
expect "employee оставляет feedback на свой message" 200; track feedback "$(echo "$BODY" | jq -r .id)"
call POST /api/collections/feedback/records "$E_TOK" "$(jq -n --arg m "$M_MSG" --arg u "$E_ID" '{message:$m,user:$u,rating:"down"}')"
expect "employee НЕ оставляет feedback на чужой message" 400 403

call POST /api/collections/audit_log/records "$E_TOK" "$(jq -n --arg u "$E_ID" '{user:$u,action:"smoke"}')"
expect "employee пишет audit_log от своего имени" 200; track audit_log "$(echo "$BODY" | jq -r .id)"
call POST /api/collections/audit_log/records "$E_TOK" "$(jq -n --arg u "$M_ID" '{user:$u,action:"forged"}')"
expect "employee НЕ пишет audit_log от чужого имени" 400 403
call GET /api/collections/audit_log/records "$E_TOK"
expect "employee НЕ читает audit_log" 403 200
if [ "$CODE" = "200" ] && [ "$(echo "$BODY" | jq -r .totalItems)" != "0" ]; then echo "  FAIL  employee видит записи audit_log"; FAIL=$((FAIL+1)); fi

echo "== 5. users: смена role / access_level"
call PATCH "/api/collections/users/records/$E_ID" "$E_TOK" '{"role":"admin"}'
expect "employee НЕ меняет себе role" 400 403 404
call PATCH "/api/collections/users/records/$E_ID" "$E_TOK" '{"access_level":3}'
expect "employee НЕ меняет себе access_level" 400 403 404
call GET "/api/collections/users/records/$E_ID" "$E_TOK"
if [ "$(echo "$BODY" | jq -r .role)" = "employee" ] && [ "$(echo "$BODY" | jq -r .access_level)" = "1" ]; then echo "  PASS  role/access_level не изменились"; PASS=$((PASS+1))
else echo "  FAIL  role/access_level изменились: $BODY"; FAIL=$((FAIL+1)); fi
call PATCH "/api/collections/users/records/$E_ID" "$E_TOK" '{"department":"smoke-dept"}'
expect "employee меняет безобидное поле профиля (department)" 200
call PATCH "/api/collections/users/records/$E_ID" "$E_TOK" '{"department":""}' >/dev/null
call PATCH "/api/collections/users/records/$M_ID" "$E_TOK" '{"department":"x"}'
expect "employee НЕ правит чужой профиль" 400 403 404

echo "== 6. documents / document_versions / сервисный PATCH"
call GET /api/collections/documents/records "$E_TOK"
if [ "$CODE" = "200" ] && [ "$(echo "$BODY" | jq -r .totalItems)" -ge 1 ]; then echo "  PASS  employee видит active-документ (level 1)"; PASS=$((PASS+1))
else echo "  FAIL  employee не видит seed-документ (HTTP $CODE)"; FAIL=$((FAIL+1)); fi

call GET "/api/collections/document_versions/records?perPage=1&sort=created" "$B_TOK"
V_ID="$(echo "$BODY" | jq -r '.items[0].id // empty')"
if [ -n "$V_ID" ]; then
  call PATCH "/api/collections/document_versions/records/$V_ID" "$B_TOK" '{"comment":"smoke-by-backend"}'
  expect "backend делает PATCH document_versions" 200
  call PATCH "/api/collections/document_versions/records/$V_ID" "$E_TOK" '{"comment":"hack"}'
  expect "employee НЕ делает PATCH document_versions" 400 403 404
  call PATCH "/api/collections/document_versions/records/$V_ID" "$B_TOK" '{"comment":""}' >/dev/null
fi

echo "== Очистка"
for ((i=${#CLEAN[@]}-1; i>=0; i--)); do
  IFS=: read -r coll id <<<"${CLEAN[$i]}"
  call DELETE "/api/collections/$coll/records/$id" "$B_TOK"
  [ "$CODE" = "204" ] || echo "  warn: не удалил $coll/$id (HTTP $CODE)"
done

echo
echo "Итого: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]

