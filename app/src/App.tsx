import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeftRight, Check, Copy, ExternalLink, FolderOpen, History, Info, Link2Off, Settings2, Trash2, Undo2 } from 'lucide-react';
import { Entry, invoke, Settings, useSnapshot } from './api';
import { getVersion } from '@tauri-apps/api/app';

function HistoryEntry({ entry, onError }: { entry: Entry; onError: (code: string) => void }) {
  const { t } = useTranslation();
  const [raw, setRaw] = useState(false);
  const [copied, setCopied] = useState(false);
  useEffect(() => { if (copied) { const timer = window.setTimeout(() => setCopied(false), 1600); return () => clearTimeout(timer); } }, [copied]);
  return <article className="history-entry">
    <div className="entry-meta"><time dateTime={new Date(entry.timestamp * 1000).toISOString()}>{new Intl.DateTimeFormat('ru', { dateStyle: 'medium', timeStyle: 'short' }).format(entry.timestamp * 1000)}</time>
      {entry.edited !== entry.raw && <button className="utility-button" title={t(raw ? 'showCorrected' : 'showOriginal')} aria-label={t(raw ? 'showCorrected' : 'showOriginal')} aria-pressed={raw} onClick={() => setRaw(value => !value)}><ArrowLeftRight aria-hidden /></button>}</div>
    <p>{raw ? entry.raw : entry.edited}</p>
    <div className="entry-actions"><button className="utility-button" title={t(copied ? 'copied' : 'copy')} aria-label={t(copied ? 'copied' : 'copy')} onClick={() => void invoke('copy_text', { text: raw ? entry.raw : entry.edited }).then(() => setCopied(true)).catch(() => onError('clipboard'))}>{copied ? <Check aria-hidden /> : <Copy aria-hidden />}</button><span className="sr-only" role="status">{copied ? t('copied') : ''}</span>
      <button className="utility-button" aria-label={t('delete')} title={t('delete')} onClick={() => void invoke('delete_entry', { id: entry.id }).catch(() => onError('storage'))}><Trash2 aria-hidden /></button></div>
  </article>;
}
export default function App() {
  const { t } = useTranslation();
  const { snapshot, error } = useSnapshot();
  const [page, setPage] = useState('settings');
  const [failure, setFailure] = useState<string | null>(null);
  const [devices, setDevices] = useState<string[]>([]);
  const [version, setVersion] = useState('');
  const content = useRef<HTMLElement>(null);
  useLayoutEffect(() => { if (content.current) content.current.scrollTop = 0; }, [page]);
  useEffect(() => { void invoke<string[]>('input_devices').then(setDevices).catch(() => setFailure('microphone')); }, []);
  useEffect(() => { void getVersion().then(setVersion).catch(() => {}); }, []);
  if (!snapshot) return <main className="initial" role="status">{t(error ? `error.${error}` : 'brand')}</main>;
  const settings = snapshot.settings;
  const save = (change: Partial<Settings>) => { setFailure(null); void invoke('save_settings', { value: { ...settings, ...change } }).catch(code => setFailure(String(code))); };
  const busy = !['idle', 'preview', 'error'].includes(snapshot.phase);
  return <div className="app-shell">
    <aside><div className="brand">{t('brand')}</div><nav aria-label={t('brand')}>
      {[['history', History], ['settings', Settings2], ['about', Info]].map(([id, Icon]) => { const name = id as string; const Glyph = Icon as typeof History; return <button key={name} className={page === name ? 'nav-current' : undefined} aria-current={page === name ? 'page' : undefined} onClick={() => setPage(name)}><Glyph size={17} aria-hidden />{t(name)}</button>; })}
    </nav><span className="local-note">{t('local')}</span></aside>
    <main ref={content} className={`content page-${page}`}><header><h1>{t(page)}</h1>{page === 'history' && snapshot.history.length > 0 && <button className="utility-button" title={t('clear')} aria-label={t('clear')} onClick={() => void invoke('clear_history').catch(() => setFailure('storage'))}><Trash2 aria-hidden /></button>}</header>
      {(failure || error || snapshot.error) && <p className="notice error" role="alert">{t(`error.${failure || error || snapshot.error}`)}</p>}
      {page === 'history' && <><p className="muted intro">{t('historyHelp')}</p>{snapshot.history.length ? snapshot.history.map(entry => <HistoryEntry key={entry.id} entry={entry} onError={setFailure} />) : <div className="empty"><History size={24} aria-hidden /><h2>{t('emptyHistory')}</h2><p>{t('emptyHelp')}</p></div>}</>}
      {page === 'settings' && <>
        {!['checking', 'ready'].includes(snapshot.shortcut_status) && <section className="notice"><h2>{t(snapshot.shortcut_status === 'permission_required' ? 'permissions' : 'shortcutUnavailable')}</h2><p>{t(snapshot.shortcut_status === 'permission_required' ? 'permissionHelp' : 'shortcutUnavailableHelp')}</p>{snapshot.shortcut_status === 'permission_required' && <><button className="utility-button" title={t('openPermissions')} aria-label={t('openPermissions')} onClick={() => void invoke('open_permission_settings').catch(() => setFailure('permission'))}><ExternalLink aria-hidden /></button><details><summary>{t('permissionAlreadyEnabled')}</summary><p>{t('permissionRecovery')}</p></details></>}</section>}
        <fieldset disabled={busy}><legend>{t('recording')}</legend>
          <div className="setting-row"><label htmlFor="shortcut">{t('shortcut')}</label><select id="shortcut" value={settings.shortcut} onChange={event => save({ shortcut: event.target.value })}><option value="optionright">{t('rightOption')}</option><option value="option+space">{t('optionSpace')}</option><option value="control+option+space">{t('controlOptionSpace')}</option></select></div>
          <div className="setting-row"><div><span id="mode-label">{t('mode')}</span><p className="muted small">{t(settings.hold ? 'holdHelp' : 'toggleHelp')}</p></div><div className="segments" role="group" aria-labelledby="mode-label">{[false, true].map(hold => <button key={String(hold)} aria-pressed={settings.hold === hold} onClick={() => save({ hold })}>{t(hold ? 'hold' : 'toggle')}</button>)}</div></div>
          <div className="setting-row"><label htmlFor="microphone">{t('microphone')}</label><select id="microphone" value={settings.microphone || ''} onChange={event => save({ microphone: event.target.value || null })}><option value="">{t('systemMicrophone')}</option>{devices.map((name, index) => <option key={`${name}-${index}`} value={name}>{name}</option>)}</select></div>
        </fieldset>
        <fieldset disabled={busy}><legend>{t('result')}</legend><div className="setting-row"><span id="output-label">{t('afterRecognition')}</span><div className="segments" role="group" aria-labelledby="output-label">{[false, true].map(auto_insert => <button key={String(auto_insert)} aria-pressed={settings.auto_insert === auto_insert} onClick={() => save({ auto_insert })}>{t(auto_insert ? 'auto' : 'preview')}</button>)}</div></div>
          <label className="check-row"><span>{t('cleanup')}<span className="muted small description">{t('cleanupHelp')}</span></span><input type="checkbox" checked={settings.cleanup} onChange={event => save({ cleanup: event.target.checked })} /></label>
          <div className="setting-row model-row"><div><span>{t('cleanupModel')}</span><p className="muted small" role="status">{t(snapshot.cleanup_model_status === 'checking' ? 'modelChecking' : settings.cleanup_model_path ? 'modelLinked' : 'modelMissing')}</p></div><div className="setting-actions">
            <button className="utility-button" title={t('chooseModel')} aria-label={t('chooseModel')} disabled={snapshot.phase !== 'idle' || snapshot.cleanup_model_status === 'checking'} onClick={() => void invoke('choose_cleanup_model').catch(code => setFailure(String(code)))}><FolderOpen aria-hidden /></button>
            {settings.cleanup_model_path && <button className="utility-button" title={t('unlinkModel')} aria-label={t('unlinkModel')} disabled={snapshot.cleanup_model_status === 'checking'} onClick={() => save({ cleanup_model_path: null })}><Link2Off aria-hidden /></button>}
          </div>{settings.cleanup_model_path && <p className="model-note muted small">{t('modelReuse')}</p>}</div>
          {snapshot.phase === 'preview' && snapshot.raw_text !== snapshot.text && <div className="setting-row"><span>{t('originalPreviewText')}</span><div className="setting-actions"><button className="utility-button" title={t('restoreRaw')} aria-label={t('restoreRaw')} onClick={() => void invoke('restore_raw_text').catch(() => setFailure('state'))}><Undo2 aria-hidden /></button></div></div>}
        </fieldset>
        <fieldset disabled={busy}><legend>{t('dataAndSound')}</legend><label className="check-row"><span>{t('keepHistory')}<span className="muted small description">{t('historyOffHelp')}</span></span><input type="checkbox" checked={settings.history_enabled} onChange={event => save({ history_enabled: event.target.checked })} /></label><label className="check-row"><span>{t('sounds')}</span><input type="checkbox" checked={settings.sounds} onChange={event => save({ sounds: event.target.checked })} /></label></fieldset>
      </>}
      {page === 'about' && <div className="about">
        <div className="about-intro"><h2>{t('brand')}</h2><span className="about-version">{version && `${t('appVersion', { version })} · `}macOS 14+ · Apple Silicon</span><p>{t('aboutText')}</p></div>
        <p className="about-origin">{t('basedOnHandy')}</p>
        <details className="about-credits"><summary>{t('componentsAndThanks')}</summary><div><p>{t('creditHandy')}</p><p>{t('creditGiga')}</p><p>{t('creditQwen')}</p><p>{t('creditFonts')}</p></div></details>
      </div>}
    </main>
  </div>;
}
