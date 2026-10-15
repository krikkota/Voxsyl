import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeftRight, ArrowUp, X } from 'lucide-react';
import { invoke, listen, useSnapshot } from './api';
import { drawPearlFrame } from './visual/pearl-voice';
import { drawPearlTransition } from './visual/transition';
import { createPreviewOpacity } from './visual/preview-opacity';

export default function Overlay() {
  const { t } = useTranslation();
  const { snapshot } = useSnapshot();
  const canvas = useRef<HTMLCanvasElement>(null);
  const preview = useRef<HTMLDivElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const state = useRef(snapshot);
  const volume = useRef(0);
  const wake = useRef<(() => void) | null>(null);
  const [text, setText] = useState('');
  const versions = useRef<{ raw: string; corrected: string } | null>(null);
  const [original, setOriginal] = useState(false);
  const [hasVersions, setHasVersions] = useState(false);
  const [switching, setSwitching] = useState(false);
  const textAnimation = useRef<Animation | null>(null);
  const switchEpoch = useRef(0);
  const fadeIn = useRef(false);
  const resetTextScroll = useRef(false);
  state.current = snapshot;
  const phase = snapshot?.phase || 'idle';
  const editing = phase === 'preview';
  const height = useRef(112);
  // Original text scrolls inside the same card instead of growing it on toggle.
  if (!original || !hasVersions) height.current = Math.min(172, Math.max(100, 56 + Math.ceil(Math.max(1, text.length) / 38) * 21));
  useEffect(() => { if (editing) { const timer = setTimeout(() => textarea.current?.focus(), 760); return () => clearTimeout(timer); } }, [editing]);
  useLayoutEffect(() => {
    switchEpoch.current += 1;
    textAnimation.current?.cancel(); fadeIn.current = false; setSwitching(false);
    if (!editing) { versions.current = null; setHasVersions(false); setOriginal(false); return; }
    const raw = snapshot?.raw_text || '';
    const next = snapshot?.text || '';
    // Keep both drafts when the separate Settings action restores the original.
    if (!versions.current || versions.current.raw !== raw) versions.current = { raw, corrected: next };
    else if (next !== raw) versions.current.corrected = next;
    setHasVersions(!!raw && versions.current.corrected !== raw);
    setOriginal(next === raw); setText(next);
  }, [editing, snapshot?.text, snapshot?.raw_text]);
  useLayoutEffect(() => {
    if (resetTextScroll.current && textarea.current) {
      resetTextScroll.current = false;
      textarea.current.setSelectionRange(0, 0);
      textarea.current.scrollTop = 0; textarea.current.scrollLeft = 0;
    }
    if (!fadeIn.current) return;
    fadeIn.current = false; textAnimation.current?.cancel();
    textAnimation.current = textarea.current?.animate([{ opacity: .25 }, { opacity: 1 }], { duration: 85, easing: 'ease-out' }) || null;
  }, [text, original]);
  useEffect(() => () => { switchEpoch.current += 1; textAnimation.current?.cancel(); }, []);
  useLayoutEffect(() => {
    if (['idle', 'arming', 'recording', 'processing'].includes(phase)) setText('');
  }, [phase]);
  useEffect(() => {
    let mounted = true;
    const subscription = listen<number>('mic-level', event => { if (mounted) volume.current = Math.max(0, Math.min(1, event.payload)); });
    return () => { mounted = false; void subscription.then(unlisten => unlisten()); };
  }, []);
  useEffect(() => {
    const drawing = canvas.current;
    const context = drawing?.getContext('2d');
    if (!drawing || !context) return;
    const pearl = document.createElement('canvas'); pearl.width = pearl.height = 420;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0, previous = performance.now(), shape = .336, time = 1.6, amplitude = 0;
    let progress = 0, visibility = 0, arrival = 0, cardHeight = 112, glow = 0;
    let lastPhase = 'idle', frozenShape = shape, frozenTime = time, closeStarted = 0, hidden = false, closeStartProgress = 0;
    let entranceStarted = performance.now();
    const previewOpacity = createPreviewOpacity();
    const ease = (a: number, b: number, amount: number) => a + (b - a) * Math.max(0, Math.min(1, amount));
    const smooth = (value: number) => { const p = Math.max(0, Math.min(1, value)); return p * p * (3 - 2 * p); };
    function render(now: number) {
      const dt = Math.min(.05, (now - previous) / 1000); previous = now;
      const value = state.current;
      const current = value?.phase || 'idle';
      if (lastPhase !== current) {
        if (lastPhase === 'idle') entranceStarted = now;
        if (current === 'idle' || current === 'arming') {
          progress = 0; cardHeight = 112; amplitude = 0; volume.current = 0;
        }
        if (current === 'preview' || current === 'error') { frozenShape = shape; frozenTime = time; }
        if (current === 'closing') {
          closeStarted = now; closeStartProgress = progress;
          if (!['preview', 'error', 'inserting'].includes(lastPhase)) { frozenShape = shape; frozenTime = time; }
        }
        hidden = false; lastPhase = current;
      }
      amplitude = ease(amplitude, current === 'recording' ? volume.current : 0, 1 - Math.exp(-dt / .16));
      if (!motion.matches && current === 'recording') { time += dt; shape += dt * 2.5 * (.32 + amplitude * 1.05 + .07); }
      const expanded = current === 'preview' || current === 'error' || current === 'inserting';
      if (motion.matches) {
        progress = expanded ? 1 : 0; visibility = current === 'idle' || current === 'closing' ? 0 : 1; arrival = 1;
      } else if (current === 'closing') {
        const elapsed = now - closeStarted;
        progress = closeStartProgress * (1 - smooth((elapsed - 80) / 620));
        visibility = 1 - smooth((elapsed - 640) / 420);
        arrival = visibility;
      } else {
        visibility = current === 'idle' ? 0 : smooth((now - entranceStarted) / 420);
        arrival = visibility;
        progress = ease(progress, expanded ? 1 : 0, 1 - Math.exp(-dt / .18));
      }
      if (current === 'closing' && visibility <= .001 && !hidden) { hidden = true; void invoke('overlay_hidden'); }
      glow = ease(glow, current === 'processing' ? 1 : 0, 1 - Math.exp(-dt / .16));
      cardHeight = ease(cardHeight, height.current, 1 - Math.exp(-dt / .12));
      const rect = drawing!.getBoundingClientRect(); const dpr = devicePixelRatio;
      const width = Math.round(rect.width * dpr), h = Math.round(rect.height * dpr);
      if (drawing!.width !== width || drawing!.height !== h) { drawing!.width = width; drawing!.height = h; }
      context!.setTransform(dpr, 0, 0, dpr, 0, 0);
      const g = drawPearlTransition(context!, { width: rect.width, height: rect.height, progress, visibility, arrival,
        volume: amplitude, time: expanded || current === 'closing' ? frozenTime : time,
        shapePhase: expanded || current === 'closing' ? frozenShape : shape, cardHeight,
        pearlCanvas: pearl, processing: glow, processingTime: motion.matches ? 1 : now / 1000 }, drawPearlFrame);
      const layer = preview.current;
      if (layer) {
        layer.style.width = `${g.cardWidth}px`; layer.style.height = `${cardHeight}px`;
        layer.style.left = `${(rect.width - g.cardWidth) / 2}px`;
        const textAlpha = previewOpacity(current, progress, now);
        layer.style.opacity = String(textAlpha * visibility);
        layer.toggleAttribute('inert', current !== 'preview' && current !== 'error');
      }
      frame = current === 'idle' && visibility === 0 ? 0 : requestAnimationFrame(render);
    }
    wake.current = () => { if (!frame) { previous = performance.now(); frame = requestAnimationFrame(render); } };
    frame = requestAnimationFrame(render);
    return () => { wake.current = null; cancelAnimationFrame(frame); };
  }, []);
  useEffect(() => { wake.current?.(); }, [phase]);
  useEffect(() => {
    if (phase !== 'preview' && phase !== 'error') return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); void invoke('close_preview'); }
      if (phase === 'preview' && !switching && event.metaKey && event.key === 'Enter' && text.trim()) {
        event.preventDefault(); event.stopPropagation(); void invoke('insert_text', { text });
      }
    };
    window.addEventListener('keydown', onKeyDown, true);
    const focusError = phase === 'error' ? window.setTimeout(() => preview.current?.querySelector<HTMLButtonElement>('.close')?.focus(), 760) : undefined;
    return () => { window.removeEventListener('keydown', onKeyDown, true); if (focusError !== undefined) clearTimeout(focusError); };
  }, [phase, text, switching]);
  const insert = () => { if (editing && !switching && text.trim()) void invoke('insert_text', { text }); };
  const switchVersion = async () => {
    if (!editing || switching || !versions.current) return;
    const epoch = ++switchEpoch.current;
    versions.current[original ? 'raw' : 'corrected'] = text;
    const next = versions.current[original ? 'corrected' : 'raw'];
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    setSwitching(true);
    if (!reduced && textarea.current) {
      textAnimation.current?.cancel();
      textAnimation.current = textarea.current.animate([{ opacity: 1 }, { opacity: .25 }], { duration: 45, fill: 'forwards', easing: 'ease-in' });
      await textAnimation.current.finished.catch(() => {});
    }
    if (epoch !== switchEpoch.current) return;
    fadeIn.current = !reduced && next !== text;
    resetTextScroll.current = true;
    if (!fadeIn.current) textAnimation.current?.cancel();
    setText(next); setOriginal(!original); setSwitching(false);
  };
  return <div className="overlay-root">
    <canvas ref={canvas} aria-hidden="true" />
    <span className="sr-only" role="status" aria-live="polite">{phase !== 'idle' && t(`phase.${phase}`)}</span>
    <div ref={preview} className="preview" aria-hidden={!editing && phase !== 'error'}>
      <button className="close icon-button" title={t('close')} aria-label={t('close')} onClick={() => void invoke('close_preview')}><X size={15} aria-hidden /></button>
      {phase === 'error' ? <p className="overlay-error" role="alert">{t(`error.${snapshot?.error || 'asr'}`)}</p> : <textarea ref={textarea} value={text} aria-label={t(original ? 'originalPreviewText' : 'recognizedText')} readOnly={switching} spellCheck={false} onChange={event => setText(event.target.value)} />}
      {editing && hasVersions && <button className="version-switch icon-button" title={t(original ? 'showCorrected' : 'showOriginal')} aria-label={t(original ? 'showCorrected' : 'showOriginal')} aria-pressed={original} disabled={switching} onClick={() => void switchVersion()}><ArrowLeftRight size={15} aria-hidden /></button>}
      <button className="insert icon-button" title={t('insert')} aria-label={t('insert')} disabled={!editing || switching || !text.trim()} onClick={insert}><ArrowUp size={16} aria-hidden /></button>
      {editing && snapshot?.error && <span className="sr-only" role="alert">{t(`error.${snapshot.error}`)}</span>}
      {editing && snapshot?.error && <p className="preview-failure" role="alert">{t(`error.${snapshot.error}`)}</p>}
    </div>
  </div>;
}
