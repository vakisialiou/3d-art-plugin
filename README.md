# 🧩 3d-art-plugin

Аддон Blender проекта [3d-art](../README.md) — читает текущую сцену и отправляет её в [3d-art-api](../3d-art-api) по socket.io для живого превью в [3d-art-web](../3d-art-web). Собран под Blender 5.2.1, только стандартная библиотека Python (`urllib`) — pip внутри Blender не нужен.

## 📦 Что делает

- 📤 Экспортирует объекты как glTF — один маленький `.glb` на объект, а не вся сцена одним блобом; иерархия собирается в браузере по `id`/`parentId`.
- 🎨 Материалы Principled BSDF вместе с coat-слоем: процедурные входы запекаются в текстуры (glTF их иначе теряет), составные поверхности и Volume приближаются.
- ☀️ Отдельные каналы синка, каждый своей кнопкой: сцена/объекты, небо, HDRI, свет, настройки рендера, камера.
- 🖼️ `blender/` — демо-сцены для проверки синка (не код аддона); `blender/scripts/` — скрипты, достраивающие демо-материалы.

## 🔧 Установка

1. Собрать `art3d_sync.zip` командой из раздела «Пересборка» — zip в git не хранится (`.gitignore`).
2. Blender: Edit → Preferences → Add-ons → Install from Disk… → `art3d_sync.zip` → включить "3D Art Sync".
3. **После каждой переустановки — полностью перезапустить Blender**: запущенная сессия держит старые модули в кэше.
4. 3D Viewport → сайдбар (`N`) → вкладка "3D Art": сначала ввести **Project ID** (из веб-приложения; без него кнопки не отправляют), затем **Send Sky** / **Send HDRI** / **Send Render Settings** (General Settings) и **Send Selected** / **Send All** в секциях Objects, Lighting, Camera.

## ⚙️ Пересборка после изменений (обязательно)

```bash
rm -f art3d_sync.zip && zip -r art3d_sync.zip art3d_sync -x "*.pyc" -x "__pycache__/*"
```

Установленная копия сама не обновляется — без пересборки, переустановки и перезапуска Blender изменения не подхватятся.

## 🌐 Конфигурация

`art3d_sync/constants.py`: `SERVER_URL` (по умолчанию `http://localhost:3500` — порт `3d-art-api`) и `DEV_TOKEN` (общий токен с сервером, `ART3D_DEV_TOKEN` на стороне API; логина у аддона нет).

## 📚 Документация

- [`CLAUDE.md`](CLAUDE.md) — дисциплина пересборки, конвенции, неочевидные моменты экспорта
- [`docs/file-structure.md`](docs/file-structure.md) — роли файлов `art3d_sync/`
- [`../CLAUDE.md`](../CLAUDE.md) — архитектура всего проекта
- [`../docs/sync-protocol.md`](../docs/sync-protocol.md) — формат payload'ов, которые собирает этот аддон
