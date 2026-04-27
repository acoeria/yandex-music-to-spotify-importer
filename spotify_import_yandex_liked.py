#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Импорт TXT-списка треков в Spotify.

Входной файл:
    Artist - Track
    Artist - Track

Скрипт:
    - ищет треки через Spotify;
    - создаёт плейлист или пишет в уже существующий;
    - добавляет найденные треки;
    - сохраняет отчёты;
    - умеет продолжать после rate limit.

Перед запуском нужны переменные окружения:
    SPOTIPY_CLIENT_ID
    SPOTIPY_CLIENT_SECRET
    SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth


SPOTIFY_SCOPE = "playlist-modify-public playlist-modify-private user-read-private"


class LongRateLimit(RuntimeError):
    """Spotify просит ждать слишком долго. Сохраняем состояние и выходим."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Spotify rate limit: retry after {retry_after} seconds")


@dataclass
class TrackLine:
    raw: str
    artist: str
    title: str


@dataclass
class MatchResult:
    raw: str
    input_artist: str
    input_title: str
    spotify_artist: str = ""
    spotify_title: str = ""
    spotify_album: str = ""
    spotify_uri: str = ""
    spotify_url: str = ""
    score: float = 0.0
    query: str = ""
    status: str = "not_found"


def clean_text(value: str) -> str:
    return (value or "").replace("\u00a0", " ").strip()


def normalize_for_match(value: str) -> str:
    value = clean_text(value).lower().replace("ё", "е")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))

    # Частый шум в названиях. Убираем только для сравнения, исходную строку не трогаем.
    value = re.sub(r"\[(.*?)\]", " ", value)
    value = re.sub(
        r"\((?:.*?remaster.*?|.*?remastered.*?|.*?live.*?|.*?version.*?|.*?edit.*?)\)",
        " ",
        value,
        flags=re.I,
    )

    value = re.sub(r"[\"'`´’“”«»]", "", value)
    value = re.sub(r"[^0-9a-zа-яіїєґ一-龥ぁ-ゔァ-ヴー々〆〤가-힣]+", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def similarity(left: str, right: str) -> float:
    left_norm = normalize_for_match(left)
    right_norm = normalize_for_match(right)

    if not left_norm or not right_norm:
        return 0.0

    if left_norm == right_norm:
        return 1.0

    if left_norm in right_norm or right_norm in left_norm:
        return max(0.82, SequenceMatcher(None, left_norm, right_norm).ratio())

    return SequenceMatcher(None, left_norm, right_norm).ratio()


def split_artists(artist: str) -> list[str]:
    artist = clean_text(artist)
    if not artist:
        return []

    parts = re.split(r"\s*(?:,|&| feat\. | ft\. | featuring | x )\s*", artist, flags=re.I)
    return [part.strip() for part in parts if part.strip()]


def parse_track_line(line: str) -> TrackLine | None:
    raw = clean_text(line)
    if not raw:
        return None

    for separator in (" - ", " — ", " – "):
        if separator in raw:
            artist, title = raw.split(separator, 1)
            return TrackLine(raw=raw, artist=clean_text(artist), title=clean_text(title))

    return TrackLine(raw=raw, artist="", title=raw)


def read_tracks(path: Path, limit: int | None) -> list[TrackLine]:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()

    tracks: list[TrackLine] = []
    seen: set[str] = set()

    for line in lines:
        item = parse_track_line(line)
        if item is None:
            continue

        key = normalize_for_match(item.raw)
        if key in seen:
            continue

        tracks.append(item)
        seen.add(key)

    if limit is not None:
        tracks = tracks[:limit]

    return tracks


def build_search_query(track: TrackLine) -> str:
    # Один запрос на трек. Так меньше шанс быстро упереться в rate limit.
    title = track.title.replace('"', "")
    artists = split_artists(track.artist)
    first_artist = artists[0].replace('"', "") if artists else ""

    if title and first_artist:
        return f"{first_artist} {title}"

    return title or track.raw


def retry_after_from_error(error: Exception) -> int:
    headers = getattr(error, "headers", None) or {}

    for key in ("Retry-After", "retry-after"):
        if key in headers:
            try:
                return int(float(headers[key]))
            except Exception:
                pass

    text = str(error)

    patterns = [
        r"Retry(?: will occur)? after:?\s*(\d+)",
        r"retry-after[:=]\s*(\d+)",
        r"after\s+(\d+)\s*s",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return int(match.group(1))

    return 60


def spotify_call(fn, *args, max_retry_after: int, **kwargs):
    while True:
        try:
            return fn(*args, **kwargs)
        except SpotifyException as error:
            is_rate_limit = getattr(error, "http_status", None) == 429 or "rate/request limit" in str(error).lower()

            if not is_rate_limit:
                raise

            retry_after = retry_after_from_error(error)

            if retry_after > max_retry_after:
                raise LongRateLimit(retry_after) from error

            print(f"[429] Spotify просит паузу {retry_after} с.")
            time.sleep(retry_after + 1)


def score_candidate(track: TrackLine, item: dict[str, Any]) -> float:
    title_score = similarity(track.title, item.get("name", ""))

    spotify_artists = [artist.get("name", "") for artist in item.get("artists", [])]
    input_artists = split_artists(track.artist)

    if input_artists and spotify_artists:
        artist_score = max(
            similarity(input_artist, spotify_artist)
            for input_artist in input_artists
            for spotify_artist in spotify_artists
        )
    elif not input_artists:
        artist_score = 0.5
    else:
        artist_score = 0.0

    return round(0.70 * title_score + 0.30 * artist_score, 4)


def make_result(track: TrackLine, item: dict[str, Any] | None, score: float, query: str) -> MatchResult:
    if item is None:
        return MatchResult(
            raw=track.raw,
            input_artist=track.artist,
            input_title=track.title,
            query=query,
            status="not_found",
        )

    artists = ", ".join(artist.get("name", "") for artist in item.get("artists", []))
    album = (item.get("album") or {}).get("name", "")
    url = (item.get("external_urls") or {}).get("spotify", "")

    return MatchResult(
        raw=track.raw,
        input_artist=track.artist,
        input_title=track.title,
        spotify_artist=artists,
        spotify_title=item.get("name", ""),
        spotify_album=album,
        spotify_uri=item.get("uri", ""),
        spotify_url=url,
        score=score,
        query=query,
        status="matched",
    )


def search_track(
    sp: spotipy.Spotify,
    track: TrackLine,
    market: str,
    search_limit: int,
    max_retry_after: int,
) -> MatchResult:
    query = build_search_query(track)

    response = spotify_call(
        sp.search,
        q=query,
        type="track",
        limit=search_limit,
        market=market,
        max_retry_after=max_retry_after,
    )

    items = response.get("tracks", {}).get("items", []) if response else []

    best_item = None
    best_score = 0.0

    for item in items:
        score = score_candidate(track, item)
        if score > best_score:
            best_item = item
            best_score = score

    return make_result(track, best_item, best_score, query)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def write_csv(path: Path, rows: list[MatchResult]) -> None:
    fieldnames = list(asdict(MatchResult(raw="", input_artist="", input_title="")).keys())

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow(asdict(row))


def split_batches(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def save_reports(
    out_dir: Path,
    results: list[MatchResult],
    add_threshold: float,
    review_threshold: float,
) -> None:
    matched = [row for row in results if row.spotify_uri and row.score >= add_threshold]
    needs_review = [row for row in results if row.spotify_uri and add_threshold <= row.score < review_threshold]
    not_found = [row for row in results if not row.spotify_uri or row.score < add_threshold]

    write_csv(out_dir / "matches.csv", matched)
    write_csv(out_dir / "needs_review.csv", needs_review)
    write_csv(out_dir / "not_found.csv", not_found)

    uris = [row.spotify_uri for row in matched if row.spotify_uri]
    (out_dir / "matched_uris.txt").write_text("\n".join(uris) + ("\n" if uris else ""), encoding="utf-8")


def create_or_get_playlist(
    sp: spotipy.Spotify,
    args: argparse.Namespace,
    state: dict[str, Any],
) -> tuple[str | None, str]:
    if args.dry_run:
        return None, ""

    if args.playlist_id:
        playlist_id = args.playlist_id.strip()
        return playlist_id, f"https://open.spotify.com/playlist/{playlist_id}"

    if state.get("playlist_id"):
        playlist_id = str(state["playlist_id"])
        return playlist_id, f"https://open.spotify.com/playlist/{playlist_id}"

    playlist = spotify_call(
        sp._post,
        "me/playlists",
        payload={
            "name": args.playlist,
            "public": not args.private,
            "collaborative": False,
            "description": "Imported from a local TXT track list.",
        },
        max_retry_after=args.max_retry_after,
    )

    playlist_id = playlist["id"]
    playlist_url = playlist.get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{playlist_id}")

    state["playlist_id"] = playlist_id
    return playlist_id, playlist_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Импорт TXT-списка треков в Spotify-плейлист.")
    parser.add_argument("--input", default="yandex_liked_tracks.txt", help="TXT-файл со строками Artist - Track.")
    parser.add_argument("--playlist", default="Yandex Liked Import", help="Имя нового плейлиста.")
    parser.add_argument("--playlist-id", default=None, help="ID существующего плейлиста. Если задан, новый плейлист не создаётся.")
    parser.add_argument("--private", action="store_true", help="Создать приватный плейлист.")
    parser.add_argument("--limit", type=int, default=None, help="Ограничить число строк для теста.")
    parser.add_argument("--dry-run", action="store_true", help="Только поиск, без записи в Spotify.")
    parser.add_argument("--delay", type=float, default=6.0, help="Пауза между поисковыми запросами, секунды.")
    parser.add_argument("--search-limit", type=int, default=3, help="Сколько кандидатов брать из Spotify Search.")
    parser.add_argument("--add-threshold", type=float, default=0.62, help="Минимальный score для добавления.")
    parser.add_argument("--review-threshold", type=float, default=0.78, help="Ниже этого score строка попадёт в needs_review.csv.")
    parser.add_argument("--market", default="from_token", help='Рынок Spotify. Обычно лучше оставить "from_token".')
    parser.add_argument("--out-dir", default="spotify_import_result", help="Папка для состояния и отчётов.")
    parser.add_argument("--max-retry-after", type=int, default=600, help="Если Spotify просит ждать дольше, скрипт сохранится и выйдет.")
    parser.add_argument("--reset-state", action="store_true", help="Начать заново и удалить старое состояние.")
    parser.add_argument("--client-id", default=os.getenv("SPOTIPY_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.getenv("SPOTIPY_CLIENT_SECRET"))
    parser.add_argument("--redirect-uri", default=os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback"))

    args = parser.parse_args()

    if not args.client_id or not args.client_secret:
        print("Не заданы SPOTIPY_CLIENT_ID и/или SPOTIPY_CLIENT_SECRET.")
        print("См. README.md, раздел с настройкой Spotify Developer App.")
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    state_path = out_dir / "state.json"
    cache_path = out_dir / "spotify_search_cache.json"

    if args.reset_state:
        for path in (state_path, cache_path):
            if path.exists():
                path.unlink()

    input_path = Path(args.input)
    tracks = read_tracks(input_path, limit=args.limit)

    print(f"Файл: {input_path.resolve()}")
    print(f"Строк к обработке: {len(tracks)}")
    print(f"Папка результата: {out_dir.resolve()}")
    print()

    auth = SpotifyOAuth(
        client_id=args.client_id,
        client_secret=args.client_secret,
        redirect_uri=args.redirect_uri,
        scope=SPOTIFY_SCOPE,
        open_browser=True,
        cache_path=str(out_dir / ".spotify_token_cache"),
    )

    sp = spotipy.Spotify(
        auth_manager=auth,
        requests_timeout=30,
        retries=0,
        status_retries=0,
    )

    try:
        me = spotify_call(sp.current_user, max_retry_after=args.max_retry_after)
    except LongRateLimit as error:
        print(f"Spotify уже ограничил приложение. Повторите позже: {error.retry_after} с.")
        return 75

    print(f"Spotify user: {me.get('display_name') or me.get('id')}")
    print()

    state = load_json(state_path, default={})
    cache = load_json(cache_path, default={})

    if not isinstance(state, dict):
        state = {}

    if not isinstance(cache, dict):
        cache = {}

    try:
        playlist_id, playlist_url = create_or_get_playlist(sp, args, state)
    except LongRateLimit as error:
        save_json(state_path, state)
        print(f"Rate limit при создании плейлиста. Повторите позже: {error.retry_after} с.")
        return 75

    if playlist_url:
        print(f"Плейлист: {playlist_url}")
        print()

    processed_raw = set(state.get("processed_raw", []))
    added_uris = set(state.get("added_uris", []))
    pending_uris = list(state.get("pending_uris", []))

    results: list[MatchResult] = []
    for item in state.get("results", []):
        try:
            results.append(MatchResult(**item))
        except Exception:
            pass

    def save_state() -> None:
        state["playlist_id"] = playlist_id
        state["processed_raw"] = sorted(processed_raw)
        state["added_uris"] = sorted(added_uris)
        state["pending_uris"] = pending_uris
        state["results"] = [asdict(row) for row in results]
        save_json(state_path, state)
        save_json(cache_path, cache)

    def flush_pending() -> None:
        nonlocal pending_uris

        if args.dry_run or not playlist_id or not pending_uris:
            return

        for batch in split_batches(pending_uris, 100):
            spotify_call(
                sp._post,
                f"playlists/{playlist_id}/items",
                payload={"uris": batch},
                max_retry_after=args.max_retry_after,
            )

            for uri in batch:
                added_uris.add(uri)

            print(f"Добавлено в плейлист: {len(added_uris)}")
            time.sleep(0.5)

        pending_uris = []
        save_state()

    try:
        # Если в прошлый раз успели найти треки, но не успели добавить — добавим их первыми.
        flush_pending()

        for index, track in enumerate(tracks, start=1):
            if track.raw in processed_raw:
                continue

            cached = cache.get(track.raw)

            if isinstance(cached, dict):
                result = MatchResult(**cached)
            else:
                result = search_track(
                    sp=sp,
                    track=track,
                    market=args.market,
                    search_limit=args.search_limit,
                    max_retry_after=args.max_retry_after,
                )

                cache[track.raw] = asdict(result)
                time.sleep(args.delay)

            results.append(result)
            processed_raw.add(track.raw)

            if result.spotify_uri and result.score >= args.add_threshold and result.spotify_uri not in added_uris:
                pending_uris.append(result.spotify_uri)

            save_state()

            if len(pending_uris) >= 50:
                flush_pending()

            if index == 1 or index % 25 == 0 or index == len(tracks):
                found = sum(1 for row in results if row.spotify_uri and row.score >= args.add_threshold)
                print(f"[{index}/{len(tracks)}] обработано: {len(processed_raw)}, найдено: {found}, добавлено: {len(added_uris)}")

        flush_pending()
        save_reports(out_dir, results, args.add_threshold, args.review_threshold)

    except LongRateLimit as error:
        save_state()
        save_reports(out_dir, results, args.add_threshold, args.review_threshold)
        print()
        print(f"Spotify выдал rate limit: {error.retry_after} с.")
        print("Состояние сохранено. Повторите эту же команду позже.")
        return 75

    except KeyboardInterrupt:
        save_state()
        save_reports(out_dir, results, args.add_threshold, args.review_threshold)
        print()
        print("Остановлено пользователем. Состояние сохранено.")
        return 130

    print()
    print("Готово.")
    print(f"Обработано: {len(processed_raw)} / {len(tracks)}")
    print(f"Добавлено в плейлист: {len(added_uris)}")
    print(f"Отчёты: {out_dir.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
