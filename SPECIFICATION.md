# SavePreviewImage — SPECIFICATION

## 1. Назначение

Объединение стандартных нод **"Save Image"** и **"Preview Image"** в одну + кнопка открытия в Windows-просмотрщике.

## 2. Файлы

| Файл | Назначение |
|------|-----------|
| `image_node.py` | Python-класс ноды `SavePreviewImage` + API-роут `/custom_node_images/open_file` |
| `web/js/image_node.js` | LiteGraph-расширение: кнопка, скрытие prefix в Preview-режиме |
| `__init__.py` | Экспорт маппингов, `WEB_DIRECTORY` |

## 3. Python: класс SavePreviewImage

### INPUT_TYPES

| Поле | Тип | По умолчанию | Описание |
|------|-----|-------------|----------|
| `images` | `IMAGE` | — | Входное изображение |
| `preview_mode` | `BOOLEAN` | `True` | `True` = Preview (temp), `False` = Save (output с префиксом) |
| `filename_prefix` | `STRING` | `"ComfyUI"` | Префикс файла (только при Save) |

### hidden-поля

- `prompt`, `extra_pnginfo` — для сохранения метаданных в PNG.

### OUTPUT

- `RETURN_TYPES = ("IMAGE",)` — проходной выход (пропускает изображение дальше).
- `OUTPUT_NODE = True` — генерирует `ui.images` для JS.

### Логика save_images

| Режим | Куда сохраняет | prefix | compress_level |
|-------|---------------|--------|---------------|
| Preview | `folder_paths.get_temp_directory()` | `_temp_<random5>` | 1 |
| Save | `folder_paths.get_output_directory()` | из `filename_prefix` | 4 |

Метаданные (prompt + extra_pnginfo) сохраняются в PNG, если не отключено `--disable-metadata`.

## 4. Python: API-роут `/custom_node_images/open_file`

- **Метод:** POST
- **Тело:** `{"path": "полный_путь_к_png"}`
- **Действие:** `os.startfile(filepath)` — открывает в стандартной Windows-программе для PNG.
- **Безопасность:** проверяет, что путь начинается с `output_directory` или `temp_directory`.
- **Коды ответа:** 200 (ok), 400 (нет path), 403 (access denied), 404 (not found), 500 (ошибка).

## 5. JS: расширение LiteGraph

### 5.1. Импорт app

```javascript
const { app } = window.comfyAPI.app;
```

Компилированная сборка ComfyUI v0.27+ не предоставляет `/scripts/app.js`. `app` доступен только через `window.comfyAPI.app`. Подробнее — раздел 7.

### 5.2. Скрытие prefix в Preview-режиме

- При `preview_mode = true` → `filename_prefix` отключается (`setWidgetDisabled`) и скрывается (`display:none`).
- При `preview_mode = false` → `filename_prefix` включается и показывается.
- Переключение через `requestAnimationFrame` для синхронизации с рендером.
- Хелпер `setWidgetDisabled(w, val)` — корректно обрабатывает read-only `ComboWidget.disabled` (ComfyUI v0.27+).

### 5.3. Кнопка открытия в Windows-просмотрщике

**Механизм (v5 — финальный):**

Кнопка создаётся через нативный LiteGraph API — `this.addWidget("button", name, value, callback, options)`. Это **точно тот же механизм**, который ComfyUI использует для кнопки загрузки в стандартной ноде `LoadImage` (смотри core ComfyUI: `AUDIOUPLOAD` → `e.addWidget("button", ...)`).

```javascript
const btn = this.addWidget("button", "open_in_viewer", null, () => {
    const fp = this._images?.[0]?.full_path || this.properties?._last_path;
    if (fp) {
        fetch("/custom_node_images/open_file", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: fp })
        });
    }
}, { serialize: false });

btn.label = hasFile ? "Open in Viewer" : "No image";
```

- Без `canvasOnly: true` в Nodes 2.0 — кнопка рендерится как обычный виджет.
- **Текст кнопки:** меняется через `btn.label` (не `textContent`). `onExecuted` обновляет `this._openBtn.label = "Open in Viewer"` после генерации изображения.
- **Персистентность:** `full_path` сохраняется в `node.properties._last_path` (сериализуется в workflow JSON). После загрузки воркфлоу `onNodeCreated` проверяет `properties._last_path` и устанавливает `btn.label = "Open in Viewer"`.
- **Клик:** `fetch → POST /custom_node_images/open_file` → серверный `os.startfile(filepath)`.
- **Жизненный цикл:**
  - `onNodeCreated` — `this.addWidget("button", ...)`, проверка `_last_path` в properties.
  - `onExecuted` — сохранение `_images` и `this.properties._last_path`, обновление `this._openBtn.label`.
  - `onRemoved` — `delete this._images`, `delete this._openBtn`.

## 6. Известные проблемы и история решений

### 6.1. Ошибка в алфавите для генерации случайного суффикса ✅ ИСПРАВЛЕНО

В `image_node.py:89` строка `"abcdefghijklmnopqrstupvxyz"` содержала опечатку:
- отсутствовала буква `w`
- буква `p` повторялась дважды

Исправлено на `"abcdefghijklmnopqrstuvwxyz"`.

### 6.2. Эволюция кнопки

| Версия | Подход | Проблема |
|--------|--------|----------|
| **v1** ❌ | `addDOMWidget` preview | Пустое пространство, растяжение |
| **v2** ❌ | `onDrawForeground` + `onMouseDown` | Image-виджет перехватывает клики |
| **v3** ❌ | Floating DOM button (`position:fixed`, RAF) | Не вписывается в UI ноды |
| **v4** ❌ | `addCustomWidget` с самописным `draw` | Не совпадает визуально с native-виджетами, сложная реализация `mouse()` |
| **v5** ✅ | `this.addWidget("button", ...)` без `canvasOnly` в Nodes 2.0 | Кнопка как обычный виджет; текст обновляется через `label`, не `textContent` |

### 6.2. Кнопка пропадает после переключения воркфлоу ✅ ИСПРАВЛЕНО

`onExecuted` не вызывается после загрузки воркфлоу. Решение: `full_path` сохраняется в `node.properties._last_path` (сериализуется в JSON воркфлоу). При `onNodeCreated` читаем `properties._last_path` и восстанавливаем `btn.label`.

### 6.3. Путь к API захардкожен

`fetch("/custom_node_images/open_file", ...)` не учитывает `app.config?.apiRoot` — может сломаться при нестандартном префиксе API.

### 6.4. Нет локализации

Нет папки `locales/`, нет поддержки RU/EN. Надпись на кнопке — английская.

### 6.5. Текст кнопки не обновлялся после генерации ✅ ИСПРАВЛЕНО

`onExecuted` использовал `textContent`, но LiteGraph/ComfyUI для виджетов кнопки читает `label`. Решение: заменить на `this._openBtn.label = "Open in Viewer"`. Без этого кнопка оставалась на `"No image"` после выполнения ноды.

## 7. Совместимость с ComfyUI v0.27+

### 7.1. Изменения архитектуры

ComfyUI v0.27+ использует Rolldown production bundle:
- `/scripts/app.js` больше **не доступен** как static resource
- `app` доступен глобально: `window.comfyAPI.app`
- `WEB_DIRECTORY` маппинг работает
- `addWidget`, `addCustomWidget`, `addDOMWidget` — работают

### 7.2. Импорт app

```javascript
// ✅ Работает
const { app } = window.comfyAPI.app;
```

### 7.3. Типичные ошибки

```
Uncaught ReferenceError: app is not defined
```

Причина: файл использует `import { app } from "../../scripts/app.js"` вместо `window.comfyAPI.app`.

## 8. Рабочая копия

`D:\ComfyUI_windows_portable\ComfyUI\custom_nodes\Custom_node_Images\`
