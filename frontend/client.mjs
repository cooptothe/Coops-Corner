export class ApiError extends Error {
  constructor(message, code='request_failed', status=0, fields=[]) { super(message); this.name='ApiError'; this.code=code; this.status=status; this.fields=fields; }
}
export function assertEnvelope(body, expectedSnapshot) {
  const m = body?.meta;
  if (m?.format !== 'corner.product_api/1' || m.data_mode !== 'fixture' || m.production_authorized !== false || m.availability_verified !== false || typeof m.snapshot_id !== 'string')
    throw new ApiError('The API returned an unsupported environment or response format.','unsupported_response');
  if (expectedSnapshot && expectedSnapshot !== m.snapshot_id) throw new ApiError('The snapshot changed. Reload the workspace before continuing.','snapshot_changed',409);
  return body;
}
export async function request(path, {params={},body,signal,snapshot,fetcher=fetch}={}) {
  const controller = new AbortController(); let timeout = false;
  const abort = () => controller.abort(); signal?.addEventListener('abort',abort,{once:true});
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(()=>{ timeout=true; controller.abort(); },10000);
  const query = new URLSearchParams(Object.entries(params).filter(([,v])=>v!=='' && v!==null && v!==undefined).map(([k,v])=>[k,String(v)]));
  try {
    const response = await fetcher(`/api/v1/${path}${query.size?'?'+query:''}`, {method:body?'POST':'GET',signal:controller.signal,cache:'no-store',
      ...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
    let data; try { data=await response.json(); } catch { throw new ApiError('The API did not return JSON. Check the local server.','invalid_response',response.status); }
    if (!response.ok) throw new ApiError(data?.error?.message || `Request failed (${response.status}).`,data?.error?.code,response.status,data?.error?.fields||[]);
    assertEnvelope(data,snapshot);
    if (!Object.hasOwn(data,'data')) throw new ApiError('The API response is missing data.','invalid_response');
    return data;
  } catch(error) {
    if (signal?.aborted) throw new DOMException('Request cancelled','AbortError');
    if (timeout) throw new ApiError('The local API took too long to respond. Try again.','timeout');
    if (error instanceof ApiError) throw error;
    throw new ApiError('Could not reach the local API. Start it with .venv-api\\Scripts\\python.exe -m api.','offline');
  } finally { clearTimeout(timer); signal?.removeEventListener('abort',abort); }
}
export async function allPages(path, {snapshot,signal,params={},loader=request}={}) {
  const items=[]; let offset=0;
  for (let pages=0; pages<101; pages++) {
    const response = await loader(path,{params:{...params,limit:100,offset,snapshot_id:snapshot},snapshot,signal});
    snapshot ||= response.meta.snapshot_id;
    assertEnvelope(response,snapshot);
    const page=response.data;
    if (!Array.isArray(page.items) || page.offset!==offset || page.items.length>100) throw new ApiError('Invalid page received.','invalid_response');
    items.push(...page.items);
    if (page.next_offset===null) return {meta:response.meta,items};
    if (!Number.isInteger(page.next_offset) || page.next_offset<=offset || page.next_offset>10000) throw new ApiError('Invalid pagination cursor.','invalid_response');
    offset=page.next_offset;
  }
  throw new ApiError('This snapshot is too large for the local workspace. Narrow the scope.','page_limit');
}
