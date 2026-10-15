# Перламутр

Сохранённый вариант голосового индикатора: скорость формы **2,5×**, энергичность **100%**, изменение скорости контура от громкости включено, свечение **65%**. Цвета и рисование перенесены из выбранного в чате варианта без изменения.

## Посмотреть

Откройте `demo.html` двойным щелчком в браузере. Пример работает без интернета, установки пакетов и сервера. Он сразу запускается с выбранными настройками. «Пример речи» имитирует изменение громкости, сохраняя заданную энергичность.

Начальные 9% громкости — состояние предпросмотра. При подключении микрофона громкость будет меняться от настоящего голоса.

## Что внутри

- `demo.html` — самостоятельный пример со всеми исходниками внутри.
- `pearl-voice.js` — переносимый компонент на Canvas 2D без внешних зависимостей.
- `pearl-voice.d.ts` — типы для TypeScript.
- `preset.json` — выбранные параметры и палитры для светлой и тёмной темы.
- `preview.png` — неподвижный кадр выбранного варианта.

## Подключить в приложении

Для веб-приложения или Tauri/WebView поместите модуль рядом с кодом интерфейса:

```html
<canvas id="voice" width="320" height="210"
  style="width:320px;max-width:100%;height:auto;aspect-ratio:32/21"
  role="img" aria-label="Голосовой индикатор"></canvas>
```

```js
import { createPearlVoice } from './pearl-voice.js';

const indicator = createPearlVoice(document.getElementById('voice'));
// Выбранные 2.5× и 100% уже установлены по умолчанию.

indicator.setVolume(0.6); // Полученный уровень голоса: от 0 до 1.
indicator.setVolume(0);   // Тишина.
indicator.pause();       // Остановить движение.
indicator.resume();      // Продолжить.
// При удалении компонента:
indicator.destroy();
```

Импортируемый модуль подключайте через сборщик или сервер приложения. Для открытия напрямую с диска предназначен `demo.html`.

## React / Handy

Пример обёртки с полученным от приложения уровнем громкости:

```tsx
import { useEffect, useRef } from 'react';
import { createPearlVoice } from './pearl-voice.js';
import type { PearlController } from './pearl-voice.js';

export function PearlVoice({ volume }: { volume: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const indicator = useRef<PearlController | null>(null);

  useEffect(() => {
    if (!canvas.current) return;
    const instance = createPearlVoice(canvas.current);
    indicator.current = instance;
    return () => { instance.destroy(); indicator.current = null; };
  }, []);

  useEffect(() => { indicator.current?.setVolume(volume); }, [volume]);

  return <canvas ref={canvas} width={320} height={210}
    style={{ width: 320, maxWidth: '100%', height: 'auto', aspectRatio: '32 / 21' }}
    role="img" aria-label="Голосовой индикатор" />;
}
```

В Handy его можно разместить в окне индикатора записи и передавать уровень от существующего аудиосигнала. Если приложение отдаёт массив частотных уровней, сначала преобразуйте его в один нормированный уровень 0…1. Чувствительность подбирается под формат аудиосигнала; компонент сглаживает быстрые изменения сам.

Горячие клавиши, показ и скрытие окна, запись микрофона и распознавание речи подключаются в самом приложении. В этом комплекте сохранена визуальная часть.

## Параметры

| Параметр | Выбранное значение | Диапазон |
|---|---:|---|
| `shapeSpeed` | `2.5` | `0.5…3` |
| `energy` | `1` | `0…1` |
| `reactiveShape` | `true` | `true / false` |
| `glow` | `0.65` | `0…1` |
| `volume` | `0.09` в примере | `0…1` от микрофона |
| `theme` | `'auto'` | `'auto' / 'light' / 'dark'` |

Настройки можно менять через `setOptions({ shapeSpeed: 2.5, energy: 1 })`. Компонент поддерживает прозрачный фон, масштабирование и системную тему. При скрытии вкладки или индикатора движение останавливается; при системном уменьшении движения рисуется неподвижный кадр, реагирующий на входной уровень.

Для рендера отдельных кадров доступна `drawPearlFrame(context, { width, height, time, shapePhase, volume, energy, glow, theme })` без обращения к DOM.
