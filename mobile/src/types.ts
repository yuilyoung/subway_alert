import type {Favorite, Station} from './domain/favorites';
export type NativeState = {installId: string; baseUrl: string; demo: boolean; sessionId: string; favorites: Favorite[]; autoError: string};
export type Capabilities = {fineLocation: boolean; backgroundLocation: boolean; notifications: boolean; firebaseConfigured: boolean};
export type Identity = {uid: string; idToken: string; fcmToken: string};
export type Line = {id: string; name: string; topisName: string; directions: {code: '0' | '1'; label: string}[]};
export type Session = {
  id: string; status: 'WAITING_BOARDING' | 'TRACKING' | 'ALERT_PENDING' | 'ALERTED' | 'CANCELLED' | 'EXPIRED' | 'FAILED';
  lineId: string; direction: '0' | '1'; route: Station[]; trainNo: string | null; currentIndex: number;
  remainingStops: number; observedAt: string | null; dataFresh: boolean; lastReason: string | null;
  expiresAt: string; mode: 'DEMO' | 'LIVE'; alertKind: 'ALERT' | 'LATE' | null;
};
export type Candidate = {trainNo: string; stationName: string; terminalName: string; observedAt: string};
export type Facility = {kind: 'TRANSFER' | 'TOILET' | 'AMENITY' | 'GATE' | 'EXIT'; title: string; location: string;
  gateSide: string | null; direction: string | null; transferLine: string | null; carDoor: string | null; sourceUrl: string; verifiedAt: string};
export type StationDetail = {station: Station; facilities: Facility[]; informationNotice: string};
