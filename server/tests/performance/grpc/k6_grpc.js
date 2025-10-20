const CHECKS_MIN = Number(__ENV.CHECKS_MIN || '0.99');
import grpc from 'k6/net/grpc';
const REQ_TIMEOUT = __ENV.REQ_TIMEOUT || '120s';
// gRPC performance via Envoy
const MAX_MSG_MB = Number(__ENV.MAX_MSG_MB || '256');
const MAX_MSG_BYTES = MAX_MSG_MB * 1024 * 1024;

import encoding from 'k6/encoding';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';

import { Trend } from 'k6/metrics';

// ENV: HOST, MODEL_NAME, VUS, USE_FILE (0/1), NEW_CONN (0/1), DIMS, DTYPE, PAYLOAD_SIZE (small|medium|big), PAYLOAD_FILE
const HOST = __ENV.HOST || '127.0.0.1:8080';
const MODEL_NAME = __ENV.MODEL_NAME || 'sigmoid.onnx';
const VUS = Number(__ENV.VUS || '1');
const USE_FILE = __ENV.USE_FILE === '1';
const NEW_CONN = __ENV.NEW_CONN === '1';
const DIMS_ENV = __ENV.DIMS || '';
const DTYPE_ENV = __ENV.DTYPE || '';
const PAYLOAD_SIZE = (__ENV.PAYLOAD_SIZE || '').toLowerCase();
const PAYLOAD_FILE = __ENV.PAYLOAD_FILE || '';
const PREWARM = __ENV.PREWARM === '1';
const DURATION = __ENV.DURATION || '30s';

function inferFilePath() {
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

  // Default: sigmoid
  return '../common/payloads/sigmoid_values.json';
}
const filePath = inferFilePath();

const DIMS = DIMS_ENV ? JSON.parse(DIMS_ENV)
  : (MODEL_NAME.toLowerCase().includes('medium') ? [1,1]
     : (MODEL_NAME.startsWith('gpt2')
        ? (PAYLOAD_SIZE === 'medium' ? [1,256] : ((PAYLOAD_SIZE === 'big' || PAYLOAD_SIZE === 'large') ? [1,1024] : [1,32]))
        : [3,4,5]));
const DTYPE = DTYPE_ENV || (MODEL_NAME.startsWith('gpt2') ? 'int64' : 'float32');

function flatten(x){return Array.isArray(x)?x.flat(Infinity):x;}
function floatsToB64LE(arr){const b=new ArrayBuffer(arr.length*4);const v=new DataView(b);for(let i=0;i<arr.length;i++)v.setFloat32(i*4,arr[i],true);return encoding.b64encode(new Uint8Array(b));}
function int64sToB64LE(arr){const b=new ArrayBuffer(arr.length*8);const v=new DataView(b);for(let i=0;i<arr.length;i++)v.setBigInt64(i*8,BigInt(arr[i]),true);return encoding.b64encode(new Uint8Array(b));}

const flatValues=new SharedArray('values',function(){
  if(USE_FILE){const txt=open(filePath);return [ flatten(JSON.parse(txt).values) ]; }
  return [[0.1]];
});

const rpc_duration_ms = new Trend('rpc_duration_ms');

export let options = {
  scenarios: PREWARM
    ? { step: { executor: 'ramping-vus', startVUs: 0,
        stages: [{ duration: (DURATION || '30s'), target: Number(__ENV.VUS || VUS) }, { duration: '1s', target: 0 }] } }
    : { step: { executor: 'ramping-vus', startVUs: 0,
        stages: [{ duration:'60s', target: VUS }, { duration:'120s', target: VUS }, { duration:'30s', target: 0 }] } },
  thresholds: PREWARM ? {} : { checks: [`rate>=${CHECKS_MIN}`] },
};

const client = new grpc.Client();
client.load([], '../../../grpc_service/protos/inference.proto');
let connected = false;


export default function(){
  if (NEW_CONN) { client.connect(HOST, { plaintext: true, maxReceiveSize: MAX_MSG_BYTES, maxSendSize: MAX_MSG_BYTES }); }
  else if (!connected) { client.connect(HOST, { plaintext: true, maxReceiveSize: MAX_MSG_BYTES, maxSendSize: MAX_MSG_BYTES }); connected = true; }
  const flat=flatValues[0];
  const tc=(DTYPE==='int64')?int64sToB64LE(flat):floatsToB64LE(flat);
  const req={model_name:MODEL_NAME,input:{dims:DIMS,tensor_content:tc}};

  const t0=Date.now();
  const res=client.invoke('nexon.grpc.inference.v1.InferenceService/Predict', req, { timeout: REQ_TIMEOUT });
  rpc_duration_ms.add(Date.now()-t0);

  check(res,{ 'gRPC OK':(r)=>r && r.status===grpc.StatusOK });

  if(NEW_CONN) client.close();
  sleep(0.05);
}
export function teardown(){ try{ client.close(); }catch(_){ } }
