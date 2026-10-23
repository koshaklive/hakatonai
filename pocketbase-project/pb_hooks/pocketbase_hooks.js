// Триггер на индексацию
onRecordAfterCreateRequest((e) => {
    const status = e.record.get("status");
    if (status === "draft" || status === "indexing") {
        const backendUrl = $os.getenv("BACKEND_URL") || "http://fastapi:8000";
        try {
            $http.send({
                url: `${backendUrl}/ingest`,
                method: "POST",
                body: JSON.stringify({ version_id: e.record.id }),
                headers: { "Content-Type": "application/json" }
            });
            $app.logger().info("Ingest triggered for version: " + e.record.id);
        } catch (err) {
            $app.logger().error("Ingest trigger failed", "error", err);
        }
    }
}, "document_versions");

// Архивация старой версии при активации новой
onRecordAfterUpdateRequest((e) => {
    const status = e.record.get("status");
    const originalStatus = e.record.originalCopy().get("status");

    if (status === "active" && originalStatus !== "active") {
        const docId = e.record.get("document");
        const docRecord = $app.dao().findRecordById("documents", docId);
        const oldVersionId = docRecord.get("current_version");

        if (oldVersionId && oldVersionId !== e.record.id) {
            try {
                const oldVersion = $app.dao().findRecordById("document_versions", oldVersionId);
                oldVersion.set("status", "archived");
                $app.dao().saveRecord(oldVersion);
            } catch (err) {}
        }
        docRecord.set("current_version", e.record.id);
        $app.dao().saveRecord(docRecord);
    }
}, "document_versions");