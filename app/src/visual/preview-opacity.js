// Keep the last rendered opacity: closing must never reveal a hidden card.
export function createPreviewOpacity() {
  let phase = 'idle', opacity = 0, closingOpacity = 0, closingAt = 0;
  const smooth = value => {
    const p = Math.max(0, Math.min(1, value));
    return p * p * (3 - 2 * p);
  };
  return (current, progress, now) => {
    if (current !== phase) {
      if (current === 'closing') { closingOpacity = opacity; closingAt = now; }
      phase = current;
    }
    opacity = current === 'closing'
      ? closingOpacity * (1 - smooth((now - closingAt) / 120))
      : current === 'preview' || current === 'error'
        ? smooth((progress - .65) / .35) : 0;
    return opacity;
  };
}
