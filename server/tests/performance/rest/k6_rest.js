// REST performance via Envoy
import http from 'k6/http';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { open } from 'k6/fs';

// ENV: BASE, MODEL_NAME, VUS, USE_FILE (0|1), NEW_CONN (0|1), PAYLOAD_SIZE (small|large), PAYLOAD_FILE
const BASE = __ENV.BASE || 'http://127.0.0.1:8080';
const MODEL_NAME = __ENV.MODEL_NAME || 'sigmoid.onnx';
const VUS = Number(__ENV.VUS || '1');
const USE_FILE = __ENV.USE_FILE === '1';
const NEW_CONN = __ENV.NEW_CONN === '1';
const PAYLOAD_SIZE = (__ENV.PAYLOAD_SIZE || '').toLowerCase();
const PAYLOAD_FILE = __ENV.PAYLOAD_FILE || '';

function inferPayloadPath() {
  if (PAYLOAD_FILE) return PAYLOAD_FILE;
  if (MODEL_NAME.startsWith('gpt2')) {
    return (PAYLOAD_SIZE === 'large')
      ? 'server/tests/performance/common/payloads/gpt2_large_1x1024.json'
      : 'server/tests/performance/common/payloads/gpt2_small.json';
  }
  if (MODEL_NAME.startsWith('medium')) {
    return 'server/tests/performance/common/payloads/medium_1x1.json';
  }
  // default: sigmoid
  return 'server/tests/performance/common/payloads/sigmoid_values.json';
}

const filePath = inferPayloadPath();

const payload = new SharedArray('payload', function () {
  if (USE_FILE) {
    const txt = open(filePath);
    const obj = JSON.parse(txt);
    return [ JSON.stringify({ input: obj.values }) ]; // REST expects {"input": ...}
  }
  return [ JSON.stringify({ input: [[0.1]] }) ];
});

export let options = {
  scenarios: {
    step: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '60s', target: VUS },  // ramp
        { duration: '120s', target: VUS }, // steady
        { duration: '30s', target: 0 },    // ramp-down
      ],
    },
  },
  noConnectionReuse: NEW_CONN,
  thresholds: {
    http_req_failed: ['rate==0'],
    http_req_duration: ['p(95)<5000'], // tolerant bound
  },
};

export default function () {
  const url = `${BASE}/inference/infer/${MODEL_NAME}`;
  const res = http.post(url, payload[0], {
    headers: { 'Content-Type': 'application/json' },
    timeout: '60s',
  });
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(0.05);
}
