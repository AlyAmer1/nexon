// gRPC performance via Envoy
import grpc from 'k6/net/grpc';
import encoding from 'k6/encoding';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { open } from 'k6/fs';
import { Trend } from 'k6/metrics';

// ENV: HOST, MODEL_NAME, VUS, USE_FILE (0|1), NEW_CONN (0|1), DIMS, DTYPE, PAYLOAD_SIZE (small|large), PAYLOAD_FILE
const HOST = __ENV.HOST || '127.0.0.1:8080';
const MODEL_NAME = __ENV.MODEL_NAME || 'sigmoid.onnx';
const VUS = Number(__ENV.VUS || '1');
const USE_FILE = __ENV.USE_FILE === '1';
const NEW_CONN = __ENV.NEW_CONN === '1';
const DIMS_ENV = __ENV.DIMS || '';
const DTYPE_ENV = __ENV.DTYPE || '';
const PAYLOAD_SIZE = (__ENV.PAYLOAD_SIZE || '').toLowerCase();
const PAYLOAD_FILE = __ENV.PAYLOAD_FILE || '';

function inferFilePath() {
  if (PAYLOAD_FILE) return PAYLOAD_FILE;
  if (MODEL_NAME.startsWith('gpt2')) {
    return (PAYLOAD_SIZE === 'large')
      ? 'server/tests/performance/common/payloads/gpt2_large_1x1024.json'
      : 'server/tests/performance/common/payloads/gpt2_small.json';
  }
  if (MODEL_NAME.startsWith('medium')) {
    return 'server/tests/performance/common/payloads/medium_1x1.json';
  }
  return 'server/tests/performance/common/payloads/sigmoid_values.json';
}
const filePath = inferFilePath();

// Choose dims/dtype if not provided
const DIMS = DIMS_ENV ? JSON.parse(DIMS_ENV)
  : (MODEL_NAME.startsWith('gpt2')
        ? (PAYLOAD_SIZE === 'large' ? [1,1024] : [1,1])
        : MODEL_NAME.startsWith('medium')
            ? [1,1]
            : [3,4,5]);

const DTYPE = DTYPE_ENV || (MODEL_NAME.startsWith('gpt2') ? 'int64' : 'float32');

function flatten(x) { return Array.isArray(x) ? x.flat(Infinity) : x; }
function floatsToB64LE(arr) {
  const buf = new ArrayBuffer(arr.length * 4);
  const v = new DataView(buf);
  for (let i = 0; i < arr.length; i++) v.setFloat32(i * 4, arr[i], true);
  return encoding.b64encode(new Uint8Array(buf));
}
// int64 encoder without BigInt (low 32 bits = value, high 32 = 0)
function int64sToB64LE(arr) {
  const buf = new ArrayBuffer(arr.length * 8);
  const v = new DataView(buf);
  for (let i = 0; i < arr.length; i++) {
    v.setUint32(i * 8, arr[i] >>> 0, true);
    v.setUint32(i * 8 + 4, 0, true);
  }
  return encoding.b64encode(new Uint8Array(buf));
}

const flatValues = new SharedArray('values', function () {
  if (USE_FILE) {
    const txt = open(filePath);
    return [ flatten(JSON.parse(txt).values) ];
  }
  return [ [0.1] ];
});

// Custom latency metric so gRPC has p50/p95/p99 like REST
const rpc_duration_ms = new Trend('rpc_duration_ms');

export let options = {
  scenarios: {
    step: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '60s', target: VUS },
        { duration: '120s', target: VUS },
        { duration: '30s', target: 0 },
      ],
    },
  },
  thresholds: { checks: ['rate>0.99'] },
};

const client = new grpc.Client();
client.load([], 'server/grpc_service/protos/inference.proto');

export default function () {
  if (NEW_CONN) client.connect(HOST, { plaintext: true });
  else if (__VU === 1 && __ITER === 0) client.connect(HOST, { plaintext: true });

  const flat = flatValues[0];
  const tc = (DTYPE === 'int64') ? int64sToB64LE(flat) : floatsToB64LE(flat);
  const req = { model_name: MODEL_NAME, input: { dims: DIMS, tensor_content: tc } };

  const t0 = Date.now();
  const res = client.invoke('nexon.grpc.inference.v1.InferenceService/Predict', req, { timeout: '60s' });
  rpc_duration_ms.add(Date.now() - t0);

  check(res, { 'gRPC OK': (r) => r && r.status === grpc.StatusOK });

  if (NEW_CONN) client.close();
  sleep(0.05);
}
export function teardown() { try { client.close(); } catch (_) {} }
