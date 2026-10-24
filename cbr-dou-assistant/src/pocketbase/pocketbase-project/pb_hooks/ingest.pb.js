// Файл должен называться *.pb.js и лежать в pb_hooks/ (PocketBase 0.22.x).
// Важно: в 0.22 handler изолирован — внешние переменные/функции из файла
// внутри него недоступны, поэтому всё объявляется внутри каждого handler'а.

// ---------------------------------------------------------------
// 1. Триггер индексации при создании версии документа
// ---------------------------------------------------------------
onRecordAfterCreateRequest((e) => {
    const status = e.record.get("status");
    if (status !== "draft" && status !== "indexing") {
        return;
    }

    const versionId = e.record.id;
    const backendUrl = $os.getenv("BACKEND_URL") || "http://fastapi:8000";
    let errText = "";

    try {
        const res = $http.send({
            url: backendUrl + "/ingest",
            method: "POST",
            body: JSON.stringify({ version_id: versionId }),
            headers: { "Content-Type": "application/json" },
            timeout: 10 // секунд
        });
        // $http.send НЕ бросает исключение на 4xx/5xx — проверяем код сами
        if (res.statusCode < 200 || res.statusCode >= 300) {
            errText = "ingest: HTTP " + res.statusCode + " " + String(res.raw).slice(0, 500);
        }
    } catch (err) {
        // сеть недоступна, таймаут и т.п.
        errText = "ingest: request failed: " + String(err);
    }

    if (errText) {
        $app.logger().error("Ingest trigger failed", "version", versionId, "error", errText);
        try {
            const rec = $app.dao().findRecordById("document_versions", versionId);
            rec.set("status", "failed");
            rec.set("comment", errText.slice(0, 1000));
            $app.dao().saveRecord(rec);
        } catch (saveErr) {
            $app.logger().error("Failed to mark version as failed", "version", versionId, "error", String(saveErr));
        }
        return;
    }

    $app.logger().info("Ingest triggered", "version", versionId);

    // draft -> indexing (дальше статус меняет backend через PATCH)
    if (status === "draft") {
        try {
            const rec = $app.dao().findRecordById("document_versions", versionId);
            rec.set("status", "indexing");
            $app.dao().saveRecord(rec);
        } catch (saveErr) {
            $app.logger().error("Failed to set status=indexing", "version", versionId, "error", String(saveErr));
        }
    }
}, "document_versions");


// ---------------------------------------------------------------
// 2. Архивация старой версии при активации новой
//    (срабатывает и на PATCH от FastAPI: это API-запрос)
// ---------------------------------------------------------------
onRecordAfterUpdateRequest((e) => {
    const status = e.record.get("status");
    const originalStatus = e.record.originalCopy().get("status");

    if (status !== "active" || originalStatus === "active") {
        return;
    }

    const docId = e.record.get("document");
    let docRecord;
    try {
        docRecord = $app.dao().findRecordById("documents", docId);
    } catch (err) {
        $app.logger().error("Archive hook: document not found", "document", docId, "error", String(err));
        return;
    }

    const oldVersionId = docRecord.get("current_version");
    if (oldVersionId && oldVersionId !== e.record.id) {
        try {
            const oldVersion = $app.dao().findRecordById("document_versions", oldVersionId);
            oldVersion.set("status", "archived");
            $app.dao().saveRecord(oldVersion);
            $app.logger().info("Old version archived", "old", oldVersionId, "new", e.record.id);
        } catch (err) {
            $app.logger().error("Failed to archive old version", "old", oldVersionId, "error", String(err));
        }
    }

    try {
        docRecord.set("current_version", e.record.id);
        $app.dao().saveRecord(docRecord);
    } catch (err) {
        $app.logger().error("Failed to set current_version", "document", docId, "error", String(err));
    }
}, "document_versions");
