const test = require('node:test');
const assert = require('node:assert/strict');
const { resizeBounds, visibleBounds } = require('../geometry.cjs');
const bounds = { x: 100, y: 200, width: 800, height: 500 };

test('left and top resize preserve the opposite corner at minimum size', () => {
  assert.deepEqual(resizeBounds(bounds, 'nw', 900, 900), { x: 480, y: 460, width: 420, height: 240 });
});
test('each edge changes only its intended dimension', () => {
  assert.deepEqual(resizeBounds(bounds, 'e', 150, 70), { ...bounds, width: 950 });
  assert.deepEqual(resizeBounds(bounds, 's', 150, 70), { ...bounds, height: 570 });
  assert.deepEqual(resizeBounds(bounds, 'w', -80, 70), { ...bounds, x: 20, width: 880 });
  assert.deepEqual(resizeBounds(bounds, 'n', 150, -70), { ...bounds, y: 130, height: 570 });
});
test('a removed monitor cannot strand the saved window offscreen', () => {
  assert.deepEqual(visibleBounds({ x: 6000, y: -1000, width: 1000, height: 620 },
    { x: 0, y: 0, width: 1920, height: 1080 }), { x: 920, y: 0, width: 1000, height: 620 });
});
test('invalid resize input cannot produce invalid native bounds', () => {
  assert.deepEqual(resizeBounds(bounds, 'invalid', 10, 10), bounds);
  assert.deepEqual(resizeBounds(bounds, 'se', NaN, Infinity), bounds);
});
