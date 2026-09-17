const { app } = window.comfyAPI.app;

// Markeer assembly — F12 console
const IMG_JS_VERSION = "1.04-native-button";
console.log(`[Custom_node_Images] JS ${IMG_JS_VERSION} loaded`);

function setWidgetDisabled(w, val) {
    if (w.options) w.options.disabled = val;
    try { w.disabled = val; } catch (e) {}
}

app.registerExtension({
    name: "images.save_preview",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SavePreviewImage") return;

        const origOnCreated = nodeType.prototype.onNodeCreated;
        const origOnExecuted = nodeType.prototype.onExecuted;
        const origOnRemoved = nodeType.prototype.onRemoved;

        nodeType.prototype.onNodeCreated = function () {
            const ret = origOnCreated?.apply(this, arguments);

            // Preview toggle — скрытие prefix в Preview-режиме
            const previewToggle = this.widgets?.find(w => w.name === "preview_mode");
            const prefixWidget = this.widgets?.find(w => w.name === "filename_prefix");

            if (previewToggle && prefixWidget) {
                const updateVis = (isPreview) => {
                    setWidgetDisabled(prefixWidget, isPreview);
                    if (prefixWidget.el) prefixWidget.el.style.display = isPreview ? "none" : "";
                    if (this.graph) this.graph.setDirtyCanvas(true, true);
                };
                updateVis(previewToggle.value);
                const origCb = previewToggle.callback;
                previewToggle.callback = function (val) {
                    if (origCb) origCb.call(this, val);
                    requestAnimationFrame(() => updateVis(val));
                };
            }

            // Кнопка "Open in Viewer" — нативный виджет-кнопка (как в LoadImage).
            // canvasOnly: true НЕ работает в Nodes 2.0 (Vue) — кнопка не рендерится.
            // Пробуем БЕЗ canvasOnly — кнопка рисуется как обычный виджет.
            const openBtn = this.addWidget("button", "open_in_viewer", null, () => {
                const fp = this._images?.[0]?.full_path || this.properties?._last_path;
                if (fp) {
                    fetch("/custom_node_images/open_file", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ path: fp })
                    }).then(r => {
                        if (!r.ok) console.warn("open_file failed", r.status);
                    }).catch(err => console.warn("open_file error", err));
                }
            }, { serialize: false });
            openBtn.label = this.properties?._last_path ? "Open in Viewer" : "No image";
            this._openBtn = openBtn;

            return ret;
        };

        nodeType.prototype.onExecuted = function (message) {
            const ret = origOnExecuted?.apply(this, arguments);
            if (message?.images?.length > 0) {
                this._images = message.images;
                this.properties._last_path = message.images[0].full_path;
            }
            if (this._openBtn) {
                this._openBtn.label = "Open in Viewer";
            }
            return ret;
        };

        nodeType.prototype.onRemoved = function () {
            delete this._images;
            delete this._openBtn;
            return origOnRemoved?.apply(this, arguments);
        };
    },
});