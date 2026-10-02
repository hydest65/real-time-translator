'use strict';

const MIN_WIDTH = 420;
const MIN_HEIGHT = 240;
const EDGES = new Set(['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']);

// Use desktop coordinates (DIP) so resizing also works across display scales.
function resizeBounds(bounds, edge, dx, dy) {
  if (!EDGES.has(edge) || !Number.isFinite(dx) || !Number.isFinite(dy)) return bounds;
  let { x, y, width, height } = bounds;
  if (edge.includes('e')) width = Math.max(MIN_WIDTH, width + dx);
  if (edge.includes('s')) height = Math.max(MIN_HEIGHT, height + dy);
  if (edge.includes('w')) {
    width = Math.max(MIN_WIDTH, width - dx);
    x = bounds.x + bounds.width - width;
  }
  if (edge.includes('n')) {
    height = Math.max(MIN_HEIGHT, height - dy);
    y = bounds.y + bounds.height - height;
  }
  return { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) };
}

function visibleBounds(saved, workArea) {
  const width = Math.min(workArea.width, Math.max(MIN_WIDTH, Number(saved?.width) || 1000));
  const height = Math.min(workArea.height, Math.max(MIN_HEIGHT, Number(saved?.height) || 620));
  const x = Number.isFinite(saved?.x) ? saved.x : workArea.x + (workArea.width - width) / 2;
  const y = Number.isFinite(saved?.y) ? saved.y : workArea.y + (workArea.height - height) / 2;
  return { x: Math.round(Math.max(workArea.x, Math.min(x, workArea.x + workArea.width - width))),
    y: Math.round(Math.max(workArea.y, Math.min(y, workArea.y + workArea.height - height))),
    width: Math.round(width), height: Math.round(height) };
}

module.exports = { MIN_WIDTH, MIN_HEIGHT, EDGES, resizeBounds, visibleBounds };
