migrate((db) => {
  const dao = new Dao(db);
  
  // Создание пользователей
  const usersColl = dao.findCollectionByNameOrId("users");
  const usersData = [
    { email: "employee@test", username: "employee", password: "Password123!", passwordConfirm: "Password123!", name: "Иван Сотрудник", role: "employee", access_level: 1, emailVisibility: true },
    { email: "methodologist@test", username: "methodologist", password: "Password123!", passwordConfirm: "Password123!", name: "Анна Методолог", role: "methodologist", access_level: 2, emailVisibility: true },
    { email: "admin@test", username: "admin", password: "Password123!", passwordConfirm: "Password123!", name: "Петр Админ", role: "admin", access_level: 3, emailVisibility: true }
  ];
  
  const ids = {};
  for (const u of usersData) {
    const rec = new Record(usersColl);
    rec.setEmail(u.email);
    rec.setUsername(u.username);
    rec.setPassword(u.password);
    rec.set("name", u.name);
    rec.set("role", u.role);
    rec.set("access_level", u.access_level);
    rec.set("emailVisibility", u.emailVisibility);
    dao.saveRecord(rec);
    ids[u.role] = rec.id;
  }

  // Создание документа
  const docsColl = dao.findCollectionByNameOrId("documents");
  const docRec = new Record(docsColl);
  docRec.set("title", "Инструкция по ДОУ");
  docRec.set("doc_type", "instruction");
  docRec.set("status", "active");
  dao.saveRecord(docRec);

  // Создание версии
  const verColl = dao.findCollectionByNameOrId("document_versions");
  const verRec = new Record(verColl);
  verRec.set("document", docRec.id);
  verRec.set("version_label", "ОД-184");
  verRec.set("status", "active");
  verRec.set("access_level", 1);
  verRec.set("uploaded_by", ids["methodologist"]);
  dao.saveRecord(verRec);

  // Обновление связи в документе
  docRec.set("current_version", verRec.id);
  dao.saveRecord(docRec);

  // Создание шаблонов модулей
  const tmplColl = dao.findCollectionByNameOrId("module_templates");
  const templates = [
    { code: "mod_weekend_work", title: "О работе в выходные дни", doc_kind: "приказ" },
    { code: "mod_transfer_assets", title: "О приеме и передаче дел и имущества", doc_kind: "приказ" },
    { code: "mod_it_system", title: "О вводе в эксплуатацию ИС", doc_kind: "приказ" },
    { code: "mod_material_help", title: "О предоставлении материальной помощи", doc_kind: "распоряжение" },
    { code: "mod_project_committee", title: "О создании проектного комитета", doc_kind: "распоряжение" },
    { code: "mod_working_group", title: "О создании рабочей группы", doc_kind: "распоряжение" },
    { code: "mod_internal_audit", title: "О проведении внутреннего аудита", doc_kind: "распоряжение" }
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
    // В прототипе откат seed'ов можно опустить
});