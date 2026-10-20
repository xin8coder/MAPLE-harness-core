const { test } = require('node:test');
const assert = require('node:assert/strict');
const { presentSolution } = require('../src/liveopt_dsh/assets/explorer/solution-view.js');

test('generated keyed resources and schedule fields map without changing values', () => {
  const original = {
    orders: [{ id: 'O1', team: 'A', start_hour: 1, finish_hour: 2.5, delivery_hour: 3, late_hours: 0 }],
    teams: { A: { workers: 3, total_hours: 2.5, overtime_hours: 0 } },
    warehouses: { W1: { capacity: 10, cartons: 8 } },
    total_cost: 33,
  };
  const before = JSON.stringify(original);
  const result = presentSolution(original);
  assert.equal(result.order_plan[0].order_id, 'O1');
  assert.equal(result.order_plan[0].arrival_hour, 3);
  assert.equal(result.worker_shifts[0].team, 'A');
  assert.equal(result.warehouse_plan[0].used, 8);
  assert.equal(result.total_cost, 33);
  assert.equal(JSON.stringify(original), before);
});

test('unrecognized records are preserved and missing timing is not invented', () => {
  const raw = { orders: ['O1'], teams: { A: 'name only' }, warehouses: { W1: { capacity: 10 } } };
  assert.deepEqual(presentSolution(raw), raw);
  assert.equal(presentSolution(raw).order_plan, undefined);
  assert.deepEqual(presentSolution(), {});
});

test('canonical records keep their original fields', () => {
  const raw = { order_plan: [{ order_id: 'O1', start_hour: 0, finish_hour: 2 }], warehouse_plan: [{ warehouse: 'W1', used: 8, capacity: 10 }] };
  assert.deepEqual(presentSolution(raw), raw);
});

test('explicit packing timestamps and resource arrays retain generated values', () => {
  const raw = {
    orders: [{ order_id: 'UK-204', team: 'B', start_hour: 0,
      pack_finish_hour: 2.5, arrive_hour: 2.85, overdue_hours: 0 }],
    teams: [{ team: 'B', workers: 4, total_hours: 2.5 }],
    warehouses: [{ warehouse: 'W1', capacity: 180, used_cartons: 0 }],
  };
  const before = JSON.stringify(raw);
  const shown = presentSolution(raw);
  assert.equal(shown.order_plan[0].finish_hour, 2.5);
  assert.equal(shown.order_plan[0].arrival_hour, 2.85);
  assert.equal(shown.order_plan[0].late_hours, 0);
  assert.equal(shown.worker_shifts[0].team, 'B');
  assert.equal(shown.warehouse_plan[0].used, 0);
  assert.equal(JSON.stringify(raw), before);
});

test('resource arrays without explicit identifiers are not guessed', () => {
  const raw = { teams: [{ workers: 3 }], warehouses: [{ capacity: 10, used_cartons: 2 }] };
  assert.deepEqual(presentSolution(raw), raw);
});

test('mapped Chinese entities retain their names in schedules and warehouse plots', () => {
  const raw = {
    orders: [{ order_id: '英国二号', team_id: '乙组', assigned_zone: '普通仓区',
      carton_count: 80, start_hour: 0, finish_hour: 3, arrival_hour: 4.5, tardiness_hours: 0 }],
    teams: [{ team_id: '乙组', headcount: 3, team_overtime_hours: 0 }],
    zones: [{ zone_id: '普通仓区', capacity_cartons: 180, used_cartons: 80 }],
  };
  const original = JSON.stringify(raw);
  const shown = presentSolution(raw);
  assert.equal(shown.order_plan[0].team, '乙组');
  assert.equal(shown.order_plan[0].warehouse, '普通仓区');
  assert.equal(shown.order_plan[0].late_hours, 0);
  assert.equal(shown.worker_shifts[0].workers, 3);
  assert.equal(shown.warehouse_plan[0].warehouse, '普通仓区');
  assert.equal(shown.warehouse_plan[0].used, 80);
  assert.equal(shown.warehouse_plan[0].capacity, 180);
  assert.equal(JSON.stringify(raw), original);
});
