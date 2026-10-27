import NativeSubway from './native/NativeSubway';
import type {NativeState, Identity, Session, StationDetail, Candidate, Line} from './types';
import type {Station} from './domain/favorites';

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); }
}
export class Api {
  constructor(private readonly settings: NativeState) {}
  async identity(): Promise<Identity> { return JSON.parse(await NativeSubway.identity()) as Identity; }
  private async request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
    const headers: Record<string, string> = {'Accept': 'application/json'};
    if (path.startsWith('/api/track')) {
      const identity = await this.identity();
      if (this.settings.demo) headers['X-Demo-User'] = identity.uid;
      else headers.Authorization = `Bearer ${identity.idToken}`;
    }
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15_000);
    try {
      const response = await fetch(this.settings.baseUrl.replace(/\/$/, '') + path, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal, redirect: 'error',
      });
      const text = await response.text();
      let value: unknown;
      try { value = text ? JSON.parse(text) : null; } catch { throw new ApiError('서버 응답 형식이 올바르지 않습니다.', response.status); }
      if (!response.ok) {
        const error = value as {error?: string} | null;
        throw new ApiError(error?.error || `서버 오류 (${response.status})`, response.status);
      }
      return value as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError('서버에 연결하지 못했습니다. 네트워크와 설정의 서버 주소를 확인하세요.', 0);
    } finally { clearTimeout(timer); }
  }
  health() { return this.request<{mode: 'DEMO' | 'LIVE'; catalogReady: boolean}>('/api/health'); }
  lines() { return this.request<Line[]>('/api/lines'); }
  search(q: string, lineId = '') { return this.request<Station[]>(`/api/stations/search?q=${encodeURIComponent(q)}&lineId=${encodeURIComponent(lineId)}`); }
  nearby(latitude: number, longitude: number) { return this.request<Station[]>(`/api/stations/nearby?latitude=${latitude}&longitude=${longitude}`); }
  detail(id: string) { return this.request<StationDetail>(`/api/station/${encodeURIComponent(id)}`); }
  route(origin: Station, destination: Station, direction: string) {
    return this.request<Station[]>(`/api/routes?lineId=${encodeURIComponent(origin.lineId)}&direction=${direction}&from=${encodeURIComponent(origin.id)}&to=${encodeURIComponent(destination.id)}`);
  }
  active() { return this.request<{session: Session | null}>('/api/track/active'); }
  status(id: string) { return this.request<Session>(`/api/track/${id}/status`); }
  candidates(id: string) { return this.request<Candidate[]>(`/api/track/${id}/candidates`); }
  async start(origin: Station, destination: Station, direction: string, key: string) {
    const identity = await this.identity();
    return this.request<Session>('/api/track', 'POST', {lineId: origin.lineId, direction, boardingStationId: origin.id,
      destinationStationId: destination.id, fcmToken: identity.fcmToken, idempotencyKey: key});
  }
  board(id: string, trainNo: string) { return this.request<Session>(`/api/track/${id}/board`, 'POST', {trainNo}); }
  cancel(id: string) { return this.request<Session>(`/api/track/${id}`, 'DELETE'); }
  async refreshToken() {
    const identity = await this.identity();
    return this.request('/api/track/device-token', 'PUT', {fcmToken: identity.fcmToken});
  }
}
