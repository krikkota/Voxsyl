import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { useEffect, useState } from 'react';
export interface Settings { shortcut: string; hold: boolean; auto_insert: boolean; cleanup: boolean; history_enabled: boolean; sounds: boolean; microphone: string | null; cleanup_model_path: string | null; }
export interface Entry { id: number; timestamp: number; raw: string; edited: string; }
export interface Snapshot { phase: string; text: string; raw_text: string; cleanup_model_status: 'missing' | 'checking' | 'linked'; error: string | null; settings: Settings; history: Entry[]; shortcut_ready: boolean; shortcut_status: 'checking' | 'permission_required' | 'listener_unavailable' | 'registration_failed' | 'ready'; asr_ready: boolean; }
export function useSnapshot() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    const subscription = listen<Snapshot>('snapshot', ({ payload }) => { if (active) setSnapshot(payload); });
    void subscription.then(() => invoke<Snapshot>('snapshot')).then(value => { if (active) setSnapshot(value); }).catch(() => { if (active) setError('state'); });
    return () => { active = false; void subscription.then(unlisten => unlisten()); };
  }, []);
  return { snapshot, error };
}
export { invoke, listen };
