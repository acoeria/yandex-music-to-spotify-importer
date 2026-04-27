/*
  Экспорт видимых треков из Яндекс Музыки в TXT.

  Как пользоваться:
  1. Откройте: Коллекция -> Мне нравится -> Треки.
  2. Откройте консоль браузера.
  3. Вставьте этот файл целиком и нажмите Enter.
  4. Пролистайте список до конца.
  5. Выполните в консоли: ymSave()

  Скрипт не отправляет данные в сеть. Он только читает открытую страницу
  и скачивает TXT-файл на ваш компьютер.
*/

(function () {
  var tracks = window.ymLikedTracks || {};
  window.ymLikedTracks = tracks;

  function clean(text) {
    return (text || "")
      .replace(/\s+/g, " ")
      .replace(/\u00a0/g, " ")
      .trim();
  }

  function unique(items) {
    var result = [];
    var seen = {};

    for (var i = 0; i < items.length; i++) {
      var value = clean(items[i]);
      if (value && !seen[value]) {
        result.push(value);
        seen[value] = true;
      }
    }

    return result;
  }

  function findArtistsNear(trackLink) {
    var node = trackLink.parentElement;

    for (var depth = 0; depth < 14 && node; depth++) {
      var artistLinks = node.querySelectorAll('a[href*="/artist/"]');
      var names = [];

      for (var i = 0; i < artistLinks.length; i++) {
        names.push(artistLinks[i].textContent);
      }

      names = unique(names);

      if (names.length > 0) {
        return names.join(", ");
      }

      node = node.parentElement;
    }

    return "";
  }

  function scanVisibleTracks() {
    var links = document.querySelectorAll(
      'a[href*="/track/"], a[href*="/album/"][href*="/track/"]'
    );

    for (var i = 0; i < links.length; i++) {
      var trackLink = links[i];
      var title = clean(trackLink.textContent);

      if (!title || title.length < 2) {
        continue;
      }

      var artist = findArtistsNear(trackLink);

      if (!artist) {
        artist = "Unknown artist";
      }

      var line = artist + " - " + title;
      tracks[line] = line;
    }

    console.clear();
    console.log("Собрано треков: " + Object.keys(tracks).length);
    console.log("Листайте список вниз до конца.");
    console.log("Когда закончите, выполните: ymSave()");
  }

  window.ymStop = function () {
    if (window.ymLikedTimer) {
      clearInterval(window.ymLikedTimer);
      window.ymLikedTimer = null;
    }

    scanVisibleTracks();
    console.log("Сборщик остановлен.");
  };

  window.ymSave = function () {
    window.ymStop();

    var lines = Object.keys(tracks).sort();
    var text = lines.join("\n") + "\n";

    var blob = new Blob([text], {
      type: "text/plain;charset=utf-8"
    });

    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "yandex_liked_tracks.txt";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    console.log("Готово. Сохранено строк: " + lines.length);
  };

  if (window.ymLikedTimer) {
    clearInterval(window.ymLikedTimer);
  }

  scanVisibleTracks();
  window.ymLikedTimer = setInterval(scanVisibleTracks, 800);

  console.log("Сборщик запущен. Листайте список до конца, потом выполните ymSave()");
})();
