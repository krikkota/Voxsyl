# Сборка Voxsyl для macOS

Нужны Apple Silicon, macOS 14+, Xcode Command Line Tools, Rust stable, Python 3, Node.js и pnpm.

Из корня проекта:

```sh
python3 benchmarks/prepare.py --only gigaam,ort,llama
python3 app/dev_signing.py --initialize
cd app
pnpm install --frozen-lockfile
cd ..
python3 app/build.py
```

Первый шаг скачивает и проверяет закреплённые ресурсы. Сборщик затем использует их в offline-режиме. Для собственного Node передайте `--node /absolute/path/to/node`.

Перед сборкой завершите Voxsyl через меню приложения. Результат: `app/src-tauri/target/debug/bundle/macos/Voxsyl.app`. Каждый запуск сборщика увеличивает patch-номер и синхронизирует четыре манифеста; после неудачной попытки возможен пропуск номера.

Используется отдельная локальная связка подписи в `.local/dev-signing/`. Не публикуйте и не удаляйте её при очистке кешей. Каждый разработчик создаёт собственный ключ. Скрипт не меняет системное доверие и не выдаёт разрешений macOS. Текущая сборка не имеет Apple Developer ID / notarization.

Qwen не включается в bundle. Подключите существующий файл из Настроек, сверив размер и SHA-256 с `benchmarks/artifacts.json`. В bundle включаются GigaAM, ONNX Runtime, llama.cpp, локальные шрифты, звуки и лицензии. Модели, кеши, ключи и пользовательские данные не входят в Git.

Интерфейс — `src/`, движок и macOS-интеграция — `src-tauri/src/`. Заимствованные компоненты Handy перечислены в `UPSTREAM.json`; изменения включают собственные состояния сессии, интерфейс, анимацию, GigaAM, корректор, вставку и хранение данных.

TypeScript/Vite проверяются при сборке. Для Rust-тестов нужен подготовленный ONNX Runtime и переменные `ORT_LIB_PATH`, `ORT_PREFER_DYNAMIC_LINK=1`, `ORT_SKIP_DOWNLOAD=1`; dylib должна быть доступна через `DYLD_LIBRARY_PATH`. Проверка перехода предпросмотра: `node --test app/tests/preview-opacity.test.mjs`.

Явный developer-сценарий: запуск bundle с `--test-wav /absolute/file.wav` распознаёт выбранный WAV без микрофона и без автоматической вставки. Он не сохраняет историю и предназначен для тестовых аудио. Отдельный ignored Rust-тест `local_editor_fixture_report` использует существующий GGUF и записывает результаты заданных текстовых fixtures. Обычная диктовка не журналирует транскрипты.

Лимит записи — 240 секунд. Технический лимит редактора — 3000 символов; контекст 4096 токенов, бюджет ответа 1536, таймаут 60с. Результат Qwen всегда проверяется в предпросмотре; точность не гарантируется.
