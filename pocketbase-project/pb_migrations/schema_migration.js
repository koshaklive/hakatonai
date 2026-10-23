migrate((db) => {
  const dao = new Dao(db);

  // 1. users
  const users = dao.findCollectionByNameOrId("users");
  users.schema.addField(new SchemaField({ name: "department", type: "text" }));
  users.schema.addField(new SchemaField({ name: "role", type: "select", required: true, options: { maxSelect: 1, values: ["employee", "methodologist", "admin"] } }));
  users.schema.addField(new SchemaField({ name: "access_level", type: "number", required: true, options: { min: 1, max: 3 } }));
  users.createRule = "@request.auth.role = 'admin'";
  users.listRule = "@request.auth.role = 'admin' || @request.auth.id = id";
  users.viewRule = "@request.auth.role = 'admin' || @request.auth.id = id";
  users.updateRule = "@request.auth.role = 'admin'";
  users.deleteRule = "@request.auth.role = 'admin'";
  dao.saveCollection(users);

  // 2. documents (без current_version пока)
  const docs = new Collection({
    name: "documents", type: "base",
    listRule: "@request.auth.id != '' && status = 'active' && (@request.auth.role = 'admin' || @request.auth.role = 'methodologist' || current_version.access_level <= @request.auth.access_level)",
    viewRule: "@request.auth.id != '' && status = 'active' && (@request.auth.role = 'admin' || @request.auth.role = 'methodologist' || current_version.access_level <= @request.auth.access_level)",
    createRule: "@request.auth.role = 'admin' || @request.auth.role = 'methodologist'",
    updateRule: "@request.auth.role = 'admin' || @request.auth.role = 'methodologist'",
    deleteRule: "@request.auth.role = 'admin'",
    schema: [
      { name: "title", type: "text", required: true },
      { name: "doc_type", type: "select", required: true, options: { maxSelect: 1, values: ["instruction", "matrix", "module", "methodology"] } },
      { name: "owner_dept", type: "text" },
      { name: "status", type: "select", required: true, options: { maxSelect: 1, values: ["active", "archived"] } }
    ]
  });
  dao.saveCollection(docs);

  // 3. document_versions
  const docVersions = new Collection({
    name: "document_versions", type: "base",
    listRule: "@request.auth.id != '' && (@request.auth.role = 'admin' || @request.auth.role = 'methodologist' || (status = 'active' && access_level <= @request.auth.access_level))",
    viewRule: "@request.auth.id != '' && (@request.auth.role = 'admin' || @request.auth.role = 'methodologist' || (status = 'active' && access_level <= @request.auth.access_level))",
    createRule: "@request.auth.role = 'admin' || @request.auth.role = 'methodologist'",
    updateRule: "@request.auth.role = 'admin' || @request.auth.role = 'methodologist'",
    deleteRule: "@request.auth.role = 'admin'",
    schema: [
      { name: "document", type: "relation", required: true, options: { collectionId: docs.id, maxSelect: 1 } },
      { name: "version_label", type: "text", required: true },
      { name: "edition", type: "text" },
      { name: "file", type: "file", options: { maxSize: 20971520 } },
      { name: "status", type: "select", required: true, options: { maxSelect: 1, values: ["draft", "indexing", "active", "archived", "failed"] } },
      { name: "access_level", type: "number", required: true },
      { name: "effective_date", type: "date" },
      { name: "indexed_at", type: "date" },
      { name: "chunks_count", type: "number" },
      { name: "uploaded_by", type: "relation", required: true, options: { collectionId: users.id, maxSelect: 1 } },
      { name: "comment", type: "text" }
    ]
  });
  dao.saveCollection(docVersions);

  docs.schema.addField(new SchemaField({ name: "current_version", type: "relation", options: { collectionId: docVersions.id, maxSelect: 1 } }));
  dao.saveCollection(docs);

  // 4. module_templates
  const templates = new Collection({
    name: "module_templates", type: "base",
    listRule: "@request.auth.id != '' && (is_active = true || @request.auth.role = 'admin' || @request.auth.role = 'methodologist')",
    viewRule: "@request.auth.id != '' && (is_active = true || @request.auth.role = 'admin' || @request.auth.role = 'methodologist')",
    createRule: "@request.auth.role = 'admin' || @request.auth.role = 'methodologist'",
    updateRule: "@request.auth.role = 'admin' || @request.auth.role = 'methodologist'",
    deleteRule: "@request.auth.role = 'admin'",
    schema: [
      { name: "code", type: "text", required: true, unique: true },
      { name: "title", type: "text", required: true },
      { name: "doc_kind", type: "select", required: true, options: { maxSelect: 1, values: ["приказ", "распоряжение"] } },
      { name: "description", type: "text" },
      { name: "keywords", type: "json" },
      { name: "fields_schema", type: "json" },
      { name: "file", type: "file" },
      { name: "version", type: "relation", options: { collectionId: docVersions.id, maxSelect: 1 } },
      { name: "is_active", type: "bool" }
    ]
  });
  dao.saveCollection(templates);

  // 5. chat_sessions
  const sessions = new Collection({
    name: "chat_sessions", type: "base",
    listRule: "@request.auth.role = 'admin' || user = @request.auth.id",
    viewRule: "@request.auth.role = 'admin' || user = @request.auth.id",
    createRule: "@request.auth.id != ''",
    updateRule: "@request.auth.role = 'admin' || user = @request.auth.id",
    deleteRule: "@request.auth.role = 'admin'",
    schema: [
      { name: "user", type: "relation", required: true, options: { collectionId: users.id, maxSelect: 1 } },
      { name: "title", type: "text" },
      { name: "status", type: "select", required: true, options: { maxSelect: 1, values: ["active", "closed"] } },
      { name: "context", type: "json" }
    ]
  });
  dao.saveCollection(sessions);

  // 6. messages
  const messages = new Collection({
    name: "messages", type: "base",
    listRule: "@request.auth.role = 'admin' || session.user = @request.auth.id",
    viewRule: "@request.auth.role = 'admin' || session.user = @request.auth.id",
    createRule: "@request.auth.id != ''",
    updateRule: "@request.auth.role = 'admin'",
    deleteRule: "@request.auth.role = 'admin'",
    schema: [
      { name: "session", type: "relation", required: true, options: { collectionId: sessions.id, maxSelect: 1 } },
      { name: "role", type: "select", required: true, options: { maxSelect: 1, values: ["user", "assistant", "system"] } },
      { name: "content", type: "editor" },
      { name: "sources", type: "json" },
      { name: "relevance_max", type: "number" },
      { name: "no_answer", type: "bool" },
      { name: "clarification", type: "bool" },
      { name: "attachments", type: "json" }
    ]
  });
  dao.saveCollection(messages);

  // 7. generated_drafts
  const drafts = new Collection({
    name: "generated_drafts", type: "base",
    listRule: "@request.auth.role = 'admin' || user = @request.auth.id",
    viewRule: "@request.auth.role = 'admin' || user = @request.auth.id",
    createRule: "@request.auth.id != ''",
    updateRule: "@request.auth.role = 'admin' || user = @request.auth.id",
    deleteRule: "@request.auth.role = 'admin'",
    schema: [
      { name: "session", type: "relation", required: true, options: { collectionId: sessions.id, maxSelect: 1 } },
      { name: "user", type: "relation", required: true, options: { collectionId: users.id, maxSelect: 1 } },
      { name: "module", type: "relation", required: true, options: { collectionId: templates.id, maxSelect: 1 } },
      { name: "fields_values", type: "json" },
      { name: "file", type: "file" },
      { name: "status", type: "select", required: true, options: { maxSelect: 1, values: ["filling", "ready", "exported"] } },
      { name: "route", type: "json" },
      { name: "note_text", type: "text" }
    ]
  });
  dao.saveCollection(drafts);

  // 8. feedback
  const feedback = new Collection({
    name: "feedback", type: "base",
    listRule: "@request.auth.role = 'admin' || user = @request.auth.id",
    viewRule: "@request.auth.role = 'admin' || user = @request.auth.id",
    createRule: "@request.auth.id != ''",
    updateRule: "@request.auth.role = 'admin' || user = @request.auth.id",
    deleteRule: "@request.auth.role = 'admin'",
    schema: [
      { name: "message", type: "relation", required: true, options: { collectionId: messages.id, maxSelect: 1 } },
      { name: "user", type: "relation", required: true, options: { collectionId: users.id, maxSelect: 1 } },
      { name: "rating", type: "select", required: true, options: { maxSelect: 1, values: ["up", "down"] } },
      { name: "comment", type: "text" }
    ]
  });
  dao.saveCollection(feedback);

  // 9. audit_log
  const audit = new Collection({
    name: "audit_log", type: "base",
    listRule: "@request.auth.role = 'admin'",
    viewRule: "@request.auth.role = 'admin'",
    createRule: "@request.auth.id != ''",
    updateRule: "@request.auth.role = 'admin'",
    deleteRule: "@request.auth.role = 'admin'",
    schema: [
      { name: "user", type: "relation", required: true, options: { collectionId: users.id, maxSelect: 1 } },
      { name: "action", type: "text", required: true },
      { name: "entity", type: "text" },
      { name: "entity_id", type: "text" },
      { name: "meta", type: "json" },
      { name: "ip", type: "text" }
    ]
  });
  dao.saveCollection(audit);

}, (db) => {
  const dao = new Dao(db);
  dao.deleteCollection(dao.findCollectionByNameOrId("audit_log"));
  dao.deleteCollection(dao.findCollectionByNameOrId("feedback"));
  dao.deleteCollection(dao.findCollectionByNameOrId("generated_drafts"));
  dao.deleteCollection(dao.findCollectionByNameOrId("messages"));
  dao.deleteCollection(dao.findCollectionByNameOrId("chat_sessions"));
  dao.deleteCollection(dao.findCollectionByNameOrId("module_templates"));
  const docs = dao.findCollectionByNameOrId("documents");
  docs.schema.removeField("current_version");
  dao.saveCollection(docs);
  dao.deleteCollection(dao.findCollectionByNameOrId("document_versions"));
  dao.deleteCollection(dao.findCollectionByNameOrId("documents"));
});