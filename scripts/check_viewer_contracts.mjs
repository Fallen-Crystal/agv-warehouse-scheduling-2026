import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../src/agv/web/static/app.js', import.meta.url), 'utf8');
const match = source.match(/^function stateAt\(r,k,time\)\{[\s\S]*?^\}/m);
assert.ok(match, 'viewer must expose its replay-state helper');
const stateAt = runInNewContext('(' + match[0] + ')');
const job = {vehicle:0, assigned_at:0, pickup_arrival:3, pickup_end:5,
  delivery_arrival:8, delivery_end:9, return_end:12};
let checks = 0;
for (const [time, expected] of [[1,'to_pickup'],[3,'loading'],[5,'to_delivery'],[8,'unloading'],[9,'returning'],[12,'idle']]) {
  const result = {time, feasible:false, assignments:[job], interval_states:[[]]};
  assert.equal(stateAt(result, 0, time), expected);
  checks++;
}
const done = {time:12, feasible:true, assignments:[job], interval_states:[[]]};
assert.equal(stateAt(done, 0, 12), 'idle'); checks++;
const interrupted = {time:15, feasible:false, assignments:[job], interval_states:[[]],
  positioning_events:[{vehicle:0,start:-1,return_end:50}]};
assert.equal(stateAt(interrupted,0,15),'idle'); checks++;
console.log(JSON.stringify({checks, passed:true}));
