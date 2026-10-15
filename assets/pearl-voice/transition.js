/** Единая геометрия компактного Перламутра и поля текста. */
export function transitionGeometry(width, height, progress, cardHeight = 164, volume = .09, time = 1.6) {
  const p = Math.max(0, Math.min(1, progress));
  const cardWidth = Math.min(344, Math.max(244, width - 36));
  const baseline = height - 24;
  const r = (54 + Math.pow(volume, .65) * 20) * (1 + Math.sin(time * .65) * .008) * .5;
  return { p, cardWidth, cardHeight, volume, cx: width / 2, baseline, r,
    cy: baseline - (31 + (cardHeight / 2 - 31) * p),
    halfWidth: r + (cardWidth / 2 - r) * p,
    halfHeight: r * .98 + (cardHeight / 2 - r * .98) * p,
    radius: r * .98 + (18 - r * .98) * p };
}

const smooth = (a, b, x) => {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

function roundedRay(angle, halfWidth, halfHeight, radius) {
  radius = Math.min(radius, halfWidth, halfHeight);
  const dx = Math.cos(angle), dy = Math.sin(angle);
  const ax = Math.abs(dx), ay = Math.abs(dy);
  const t = Math.min(halfWidth / Math.max(ax, 1e-9), halfHeight / Math.max(ay, 1e-9));
  if (ax * t <= halfWidth - radius || ay * t <= halfHeight - radius) return [dx * t, dy * t];
  const x = Math.sign(dx) * (halfWidth - radius), y = Math.sign(dy) * (halfHeight - radius);
  const b = dx * x + dy * y;
  const exit = b + Math.sqrt(Math.max(0, b * b - x * x - y * y + radius * radius));
  return [dx * exit, dy * exit];
}

/** Одинаковые точки контура во всех кадрах; без смены примитива на концах. */
export function transitionContour(g, shapePhase) {
  const points = [], organic = 1 - smooth(0, .28, g.p);
  for (let i = 0; i <= 256; i++) {
    const angle = i / 256 * Math.PI * 2, dx = Math.cos(angle), dy = Math.sin(angle);
    const box = roundedRay(angle, g.halfWidth, g.halfHeight, g.radius);
    const start = roundedRay(angle, g.r, g.r * .98, g.r * .98);
    const wobble = (.025 + g.volume * .025) * Math.cos(angle * 3 + shapePhase)
      + .016 * Math.sin(angle * 2 - shapePhase * .95) + .009 * Math.sin(angle + shapePhase * .76);
    points.push([box[0] + (dx * g.r * (1+wobble) - start[0]) * organic,
      box[1] + (dy * g.r * .98 * (1+wobble) - start[1]) * organic]);
  }
  return points;
}

function traceContour(ctx, points) {
  ctx.beginPath(); points.forEach((point, i) => i ? ctx.lineTo(point[0], point[1]) : ctx.moveTo(point[0], point[1])); ctx.closePath();
}

function pearlEdge(ctx, width, height, time, opacity) {
  const gradient = typeof ctx.createConicGradient === 'function'
    ? ctx.createConicGradient(-.6 + time * .05, 0, 0)
    : ctx.createLinearGradient(-width, -height, width, height);
  [[0,[147,242,216]],[.22,[224,252,243]],[.43,[174,189,221]],[.64,[255,240,217]],[.83,[73,190,199]],[1,[147,242,216]]]
    .forEach(([offset,c])=>gradient.addColorStop(offset,`rgba(${c.join(',')},${opacity})`));
  return gradient;
}

function processingGlow(ctx, points, level, time) {
  if(level<=.001)return;
  const pulse=.84+Math.sin(time*2.4)*.12;
  ctx.save();ctx.scale(1.065,1.065);traceContour(ctx,points);
  ctx.strokeStyle=`rgba(177,164,229,${.46*level*pulse})`;
  ctx.lineWidth=1.1;ctx.shadowColor=`rgba(177,164,229,${.7*level*pulse})`;ctx.shadowBlur=13;
  ctx.stroke();ctx.restore();
}

/** Выбранный рисунок записи сохранён; новое свечение означает обработку. */
export function drawPearlTransition(ctx, options, drawPearlFrame) {
  const { width, height, progress = 0, visibility = 1, arrival = 1,
    volume = .09, time = 1.6, shapePhase = .336, cardHeight = 164, pearlCanvas,
    processing = 0, processingTime = time, handoff = 0 } = options;
  const g = transitionGeometry(width, height, progress, cardHeight, volume, time);
  ctx.clearRect(0, 0, width, height);
  if (visibility <= 0) return g;
  if (!pearlCanvas) throw new TypeError('Нужен отдельный canvas для Перламутра.');
  const points = transitionContour(g, shapePhase), p = g.p;
  ctx.save(); ctx.globalAlpha = visibility; ctx.translate(g.cx, g.cy);
  const entranceScale = .82 + .18 * arrival; ctx.scale(entranceScale, entranceScale);

  const faceOpacity = 1 - smooth(0, .2, p);
  if (faceOpacity > .001) {
    const pc = pearlCanvas.getContext('2d'), scale = pearlCanvas.width / 210;
    pc.setTransform(scale,0,0,scale,0,0);
    drawPearlFrame(pc,{width:210,height:210,volume,energy:1,glow:.65,time,shapePhase,theme:'dark'});
  }
  if (p === 0) {
    ctx.save(); ctx.scale(.5,.5); ctx.drawImage(pearlCanvas,-105,-105,210,210); ctx.restore();
    processingGlow(ctx,points,processing,processingTime);
    ctx.restore(); return g;
  }

  traceContour(ctx,points);
  ctx.fillStyle = `rgba(17,${22-5*p},${28-9*p},1)`;
  ctx.shadowColor='rgba(0,0,0,.27)';ctx.shadowOffsetY=9;ctx.shadowBlur=22;
  ctx.fill();ctx.shadowBlur=0;ctx.shadowOffsetY=0;
  ctx.save();traceContour(ctx,points);ctx.clip();
  if (faceOpacity>.001) {
    ctx.save();ctx.globalAlpha*=faceOpacity;ctx.scale(.5,.5);ctx.drawImage(pearlCanvas,-105,-105,210,210);ctx.restore();
  }
  // Свет остаётся по краям; текст лежит на спокойной чёрной поверхности.
  const wash=ctx.createLinearGradient(-g.halfWidth,-g.halfHeight,g.halfWidth,g.halfHeight);
  const washAlpha=Math.sin(Math.PI*p)*.075;
  wash.addColorStop(0,`rgba(147,242,216,${washAlpha})`);
  wash.addColorStop(.5,`rgba(224,252,243,${washAlpha*.2})`);
  wash.addColorStop(1,`rgba(174,189,221,${washAlpha})`);
  ctx.fillStyle=wash;ctx.fillRect(-g.halfWidth,-g.halfHeight,g.halfWidth*2,g.halfHeight*2);ctx.restore();

  const edgeOpacity=smooth(0,.14,p);
  if(edgeOpacity>.001){
    traceContour(ctx,points);
    ctx.strokeStyle=pearlEdge(ctx,g.halfWidth,g.halfHeight,time,.20*edgeOpacity);
    ctx.lineWidth=3;ctx.shadowColor='rgba(174,189,221,.20)';ctx.shadowBlur=6+handoff*7;ctx.stroke();
    ctx.shadowBlur=0;
    traceContour(ctx,points);ctx.strokeStyle=pearlEdge(ctx,g.halfWidth,g.halfHeight,time,(.64+handoff*.2)*edgeOpacity);ctx.lineWidth=1;ctx.stroke();
  }
  processingGlow(ctx,points,processing*(1-smooth(0,.4,p)),processingTime);
  ctx.restore();return g;
}
