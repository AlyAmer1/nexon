const CHECKS_MIN = Number(__ENV.CHECKS_MIN || '0.99');
import http from 'k6/http';
// REST performance via Envoy
const REQ_TIMEOUT = __ENV.REQ_TIMEOUT || '900s';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';


// ENV: BASE, MODEL_NAME, VUS, USE_FILE (0/1), NEW_CONN (0/1), PAYLOAD_SIZE (small|medium|big), PAYLOAD_FILE
const BASE = __ENV.BASE || 'http://127.0.0.1:8080';
const MODEL_NAME = __ENV.MODEL_NAME || 'sigmoid.onnx';
const VUS = Number(__ENV.VUS || '1');
const USE_FILE = __ENV.USE_FILE === '1';
const PREWARM = __ENV.PREWARM === '1';
const DURATION = __ENV.DURATION || '30s';
const NEW_CONN = __ENV.NEW_CONN === '1';
const PAYLOAD_SIZE = (__ENV.PAYLOAD_SIZE || '').toLowerCase(); // used only for GPT-2
const PAYLOAD_FILE = __ENV.PAYLOAD_FILE || '';

function inferPayloadPath() {
  if (PAYLOAD_FILE) return PAYLOAD_FILE;

  // Medium model → 1x1 float32
  if (MODEL_NAME.toLowerCase().includes('medium')) {
    return '../common/payloads/medium_1x1.json';
  }

  // GPT-2 → tokens
  if (MODEL_NAME.startsWith('gpt2')) {
    if (PAYLOAD_SIZE === 'medium') return '../common/payloads/gpt2_medium_1x256.json';
    if (PAYLOAD_SIZE === 'big' || PAYLOAD_SIZE === 'large') return '../common/payloads/gpt2_big_1x1024.json';
    return '../common/payloads/gpt2_small_1x32.json';
  }

  // Default: sigmoid → 3x4x5 float32
  return '../common/payloads/sigmoid_values.json';
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
  scenarios: PREWARM
    ? { step: { executor: 'ramping-vus', startVUs: 0,
        stages: [{ duration: (DURATION || '30s'), target: Number(__ENV.VUS || VUS) }, { duration: '1s', target: 0 }] } }
    : { step: { executor: 'ramping-vus', startVUs: 0,
        stages: [{ duration:'60s', target: VUS }, { duration:'120s', target: VUS }, { duration:'30s', target: 0 }] } },
  thresholds: PREWARM ? {} : { checks: [`rate>=${CHECKS_MIN}`] },
};

export default function () {
  const url = `${BASE}/inference/infer/${MODEL_NAME}`;
  const res = http.post(url, payload[0], { headers: { 'Content-Type': 'application/json' }, timeout: REQ_TIMEOUT });
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(0.05);
}
