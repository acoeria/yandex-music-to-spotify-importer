# Yandex Music TXT → Spotify Importer

Небольшой локальный инструмент для переноса треков из Яндекс Музыки в Spotify.

Он нужен в ситуации, когда обычные переносчики не работают, Яндекс Музыка не отдаёт нормальный экспорт, а у вас на руках есть список треков в текстовом виде:

```text
Artist - Track
Artist - Track
Artist - Track
```

Скрипт не использует API Яндекс Музыки.  
Он берёт обычный TXT-файл, ищет треки через Spotify Web API и складывает найденное в плейлист Spotify.

## Что умеет

- читать TXT-файл со строками `Artist - Track`;
- искать треки в Spotify;
- создавать приватный или публичный плейлист;
- добавлять найденные треки в плейлист;
- продолжать работу после rate limit;
- сохранять отчёты:
  - `matches.csv` — что найдено;
  - `needs_review.csv` — что лучше проверить глазами;
  - `not_found.csv` — что не нашлось;
  - `matched_uris.txt` — найденные Spotify URI.

## Что не умеет

- не переносит лайки напрямую из Яндекс Музыки;
- не обходит ограничения Spotify;
- не гарантирует идеальные совпадения;
- не добавляет треки в `Liked Songs`, только в плейлист.

Это сделано специально: плейлист проще проверить и почистить, чем потом разбирать мусор в любимых треках.

---

# Быстрый порядок

1. Вытащить список треков из Яндекс Музыки.
2. Создать Spotify Developer App.
3. Запустить Python-скрипт.
4. Проверить отчёты.

Ниже — полный порядок.

---

# 1. Как получить список треков из Яндекс Музыки

## Вариант через браузерную консоль

Откройте Яндекс Музыку в браузере и перейдите сюда:

```text
Коллекция → Мне нравится → Треки
```

Важно открыть именно список треков, а не альбомы, артистов или общую страницу коллекции.

Дальше:

1. Откройте инструменты разработчика:
   - Firefox: `Ctrl + Shift + K`
   - Chrome / Edge: `F12` → вкладка `Console`
2. Если браузер попросит разрешить вставку, введите:
   ```text
   allow pasting
   ```
3. Откройте файл:
   ```text
   tools/yandex_music_export_console.js
   ```
4. Скопируйте его содержимое в консоль и нажмите `Enter`.
5. Пролистайте список лайкнутых треков до самого конца.
6. В консоли выполните:
   ```js
   ymSave()
   ```
7. Браузер скачает файл:
   ```text
   yandex_liked_tracks.txt
   ```

Почему надо листать вручную: Яндекс Музыка подгружает список кусками. Если не дойти до конца, в файл попадёт только часть треков.

Подробная инструкция лежит отдельно:

```text
docs/export_from_yandex_music.md
```

---

# 2. Создать Spotify Developer App

1. Откройте Spotify Developer Dashboard.
2. Создайте новое приложение.
3. В настройках приложения добавьте Redirect URI:

```text
http://127.0.0.1:8888/callback
```

4. Скопируйте:
   - `Client ID`
   - `Client Secret`

Эти значения нужны только локально. Не выкладывайте их в GitHub.

---

# 3. Установка

Нужен Python 3.10 или новее.

В PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Если PowerShell блокирует запуск виртуального окружения:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

---

# 4. Настроить ключи Spotify

В той же PowerShell-сессии:

```powershell
$env:SPOTIPY_CLIENT_ID="your_client_id"
$env:SPOTIPY_CLIENT_SECRET="your_client_secret"
$env:SPOTIPY_REDIRECT_URI="http://127.0.0.1:8888/callback"
```

Можно проверить, что переменные заданы:

```powershell
$env:SPOTIPY_CLIENT_ID
$env:SPOTIPY_CLIENT_SECRET.Length
$env:SPOTIPY_REDIRECT_URI
```

Секрет целиком лучше не выводить.

---

# 5. Тестовый запуск

Сначала проверьте работу на примере из репозитория:

```powershell
python .\spotify_import_yandex_liked.py --input .\examples\example_tracks.txt --playlist "Yandex Import Test" --private --out-dir spotify_import_test_result
```

При первом запуске откроется браузер. Spotify попросит разрешить доступ к аккаунту.  
Разрешение нужно только для создания и изменения плейлистов.

---

# 6. Полный импорт

Положите свой `yandex_liked_tracks.txt` в папку проекта.

Запуск:

```powershell
python .\spotify_import_yandex_liked.py --input .\yandex_liked_tracks.txt --playlist "Yandex Liked from Yandex Music" --private --delay 6 --search-limit 3
```

Для больших списков лучше не уменьшать `--delay`. Spotify может выдать rate limit, если слать запросы слишком часто.

---

# 7. Если Spotify выдал rate limit

Если увидите сообщение про `rate limit` или `Retry-After`, не надо мучить API повторными запусками.

Скрипт сохраняет состояние в:

```text
spotify_import_result/state.json
spotify_import_result/spotify_search_cache.json
```

Позже запустите ту же команду ещё раз. Скрипт продолжит с того места, где остановился.

---

# 8. Если плейлист уже создан вручную

Можно создать пустой плейлист в Spotify самому, скопировать его ID из ссылки:

```text
https://open.spotify.com/playlist/THIS_IS_PLAYLIST_ID
```

И запустить импорт в него:

```powershell
python .\spotify_import_yandex_liked.py --input .\yandex_liked_tracks.txt --playlist-id "THIS_IS_PLAYLIST_ID" --delay 6 --search-limit 3
```

---

# 9. Отчёты

После работы появится папка:

```text
spotify_import_result/
```

Внутри:

```text
matches.csv
needs_review.csv
not_found.csv
matched_uris.txt
state.json
spotify_search_cache.json
```

`needs_review.csv` лучше просмотреть вручную. Там могут быть каверы, ремастеры или версии с похожим названием.

---

# 10. Что не стоит коммитить

Не публикуйте:

```text
yandex_liked_tracks.txt
.env
.venv/
spotify_import_result/
.spotify_token_cache
spotify_search_cache.json
state.json
matches.csv
needs_review.csv
not_found.csv
matched_uris.txt
```

В `.gitignore` это уже добавлено.

---

# Пример формата входного файла

```text
Bennie Goodman - Swing, Swing, Swing
Tool - Lateralus
Rammstein - Sonne
Linkin Park - Numb
```

---

# Лицензия

MIT.
