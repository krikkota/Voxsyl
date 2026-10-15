export type PearlTheme = 'auto' | 'light' | 'dark';
export interface PearlOptions {
  /** Громкость от 0 до 1. В примере: 0.09. */
  volume?: number;
  /** Энергичность от 0 до 1. Выбранное значение: 1. */
  energy?: number;
  /** Скорость изменения контура от 0.5 до 3. Выбранное значение: 2.5. */
  shapeSpeed?: number;
  /** Зависимость скорости контура от громкости. */
  reactiveShape?: boolean;
  /** Интенсивность свечения от 0 до 1. */
  glow?: number;
  theme?: PearlTheme;
  paused?: boolean;
}
export interface PearlPreset extends Required<PearlOptions> {
  label: 'Перламутр';
  material: 'pearl';
}
export const PEARL_PRESET: Readonly<PearlPreset>;
export interface PearlController {
  setVolume(value: number): void;
  setEnergy(value: number): void;
  setOptions(options: PearlOptions): void;
  getOptions(): PearlPreset;
  pause(): void;
  resume(): void;
  destroy(): void;
}
export interface PearlFrame {
  width?: number;
  height?: number;
  /** Фаза внутреннего движения; по умолчанию 1.6. */
  time?: number;
  /** Фаза внешнего контура; по умолчанию 0.336. */
  shapePhase?: number;
  volume?: number;
  energy?: number;
  glow?: number;
  theme?: 'light' | 'dark';
}
export function drawPearlFrame(ctx: CanvasRenderingContext2D, frame?: PearlFrame): void;
export function createPearlVoice(canvas: HTMLCanvasElement, options?: PearlOptions): PearlController;
