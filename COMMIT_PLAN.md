# План коммитов

Если хочется аккуратную историю, можно разложить изменения так.

## Коммит 1

```powershell
git add README.md docs/export_from_yandex_music.md examples/example_tracks.txt
git commit -m "Add usage guide and example track list"
```

## Коммит 2

```powershell
git add tools/yandex_music_export_console.js
git commit -m "Add Yandex Music browser export helper"
```

## Коммит 3

```powershell
git add spotify_import_yandex_liked.py requirements.txt
git commit -m "Add Spotify playlist importer"
```

## Коммит 4

```powershell
git add .gitignore .gitattributes .env.example LICENSE
git commit -m "Add project metadata"
```

Если не нужна красивая история, можно одним коммитом:

```powershell
git add .
git commit -m "Prepare public release"
```
