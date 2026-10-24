migrate((db) => {
  const dao = new Dao(db);

  // Секреты и email — только из окружения (см. .env.example). Пароли без дефолтов.
  const env = (key, def) => {
    const v = $os.getenv(key) || def || "";
    if (!v) {
      throw new Error("Seed: переменная окружения " + key + " обязательна");
    }
    return v;
  };

  // 1. Пользователи (+ сервисный backend)
  const usersColl = dao.findCollectionByNameOrId("users");
  const usersData = [
    { key: "employee",      username: "employee",      name: "Иван Сотрудник", role: "employee",      access_level: 1, email: env("SEED_EMPLOYEE_EMAIL", "employee@test.local"),           password: env("SEED_EMPLOYEE_PASSWORD") },
    { key: "methodologist", username: "methodologist", name: "Анна Методолог", role: "methodologist", access_level: 2, email: env("SEED_METHODOLOGIST_EMAIL", "methodologist@test.local"), password: env("SEED_METHODOLOGIST_PASSWORD") },
    { key: "admin",         username: "admin",         name: "Петр Админ",     role: "admin",         access_level: 3, email: env("SEED_ADMIN_EMAIL", "admin@test.local"),                 password: env("SEED_ADMIN_PASSWORD") },
    { key: "backend",       username: "backend",       name: "Backend Service", role: "admin",        access_level: 3, email: env("SEED_BACKEND_EMAIL", "backend@test.local"),             password: env("SEED_BACKEND_PASSWORD"), department: "service" }
  ];

  const ids = {};
  for (const u of usersData) {
    const rec = new Record(usersColl);
    rec.setEmail(u.email);
    rec.setUsername(u.username);
    rec.setPassword(u.password);
    rec.setVerified(true);
    rec.set("name", u.name);
    rec.set("role", u.role);
    rec.set("access_level", u.access_level);
    rec.set("emailVisibility", true);
    if (u.department) {
      rec.set("department", u.department);
    }
    dao.saveRecord(rec);
    ids[u.key] = rec.id;
  }

  // 2. Документ
  const docsColl = dao.findCollectionByNameOrId("documents");
  const docRec = new Record(docsColl);
  docRec.set("title", "Инструкция по ДОУ");
  docRec.set("doc_type", "instruction");
  docRec.set("status", "active");
  dao.saveRecord(docRec);

  // 3. Версия
  const verColl = dao.findCollectionByNameOrId("document_versions");
  const verRec = new Record(verColl);
  verRec.set("document", docRec.id);
  verRec.set("version_label", "ОД-184");
  verRec.set("status", "active");
  verRec.set("access_level", 1);
  verRec.set("uploaded_by", ids["methodologist"]);
  dao.saveRecord(verRec);

  docRec.set("current_version", verRec.id);
  dao.saveRecord(docRec);

  // 4. Шаблоны модулей — ровно 7, коды как в /data/modules
  const tmplColl = dao.findCollectionByNameOrId("module_templates");
  const templates = [
    { code: "order_commissioning",     title: "О вводе в эксплуатацию",                      doc_kind: "приказ" },
    { code: "order_responsible_dou",   title: "О назначении ответственных за ДОУ",           doc_kind: "приказ" },
    { code: "order_local_act",         title: "Об утверждении локального нормативного акта", doc_kind: "приказ" },
    { code: "order_handover",          title: "О приеме и передаче дел и имущества",         doc_kind: "приказ" },
    { code: "order_working_group",     title: "О создании рабочей группы",                   doc_kind: "распоряжение" },
    { code: "order_project_committee", title: "О создании проектного комитета",              doc_kind: "распоряжение" },
    { code: "order_internal_audit",    title: "О проведении внутреннего аудита",             doc_kind: "распоряжение" }
  ];

  for (const t of templates) {
    const rec = new Record(tmplColl);
    rec.set("code", t.code);
    rec.set("title", t.title);
    rec.set("doc_kind", t.doc_kind);
    rec.set("is_active", true);
    rec.set("version", verRec.id);
    rec.set("fields_schema", {});
    dao.saveRecord(rec);
  }
}, (db) => {
  // В прототипе откат seed'ов опущен (пересоздавайте volume pb_data)
});
