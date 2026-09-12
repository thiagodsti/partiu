// TypeScript interfaces matching the FastAPI backend response shapes

export interface User {
  id: string;
  username: string;
  is_admin: boolean;
  smtp_recipient_address: string | null;
  totp_enabled?: boolean;
  locale?: string;
  announcement?: string;
  /** CARTO basemap key, supplied by the server at runtime (see MeResponseDTO). */
  carto_api_key?: string;
}

export interface LoginResponse {
  requires_2fa?: boolean;
  id?: string;
  username?: string;
  is_admin?: boolean;
  smtp_recipient_address?: string | null;
  totp_enabled?: boolean;
  locale?: string;
}

export interface UserListItem extends User {
  created_at: string;
}

export interface Trip {
  id: string;
  name: string;
  start_date: string | null;
  end_date: string | null;
  origin_airport: string | null;
  destination_airport: string | null;
  booking_refs: string[];
  flight_count?: number;
  segment_count?: number;
  stay_count?: number;
  /** Distinct ground-transport types on the trip; lets the card say
   * "2 trains" instead of the generic "2 legs" when there is only one. */
  segment_types?: string[];
  flights?: Flight[];
  immich_album_id?: string | null;
  is_owner?: boolean;
  owner_username?: string | null;
  rating?: number | null;
  note?: string | null;
  expenses_total?: Record<string, number>;
  search_index?: string;
}

export type SegmentType = 'train' | 'bus' | 'ferry' | 'car';

/** One end of a trip segment. `lat`/`lon` are present when the station picker
 * matched a geocoder result, absent when the name was typed by hand — the map
 * skips segments missing either end's coordinates. */
export interface SegmentPlace {
  name: string;
  lat: number | null;
  lon: number | null;
  timezone: string | null;
  /** ISO-3166-1 alpha-2 from the geocoder; null when typed by hand. */
  country_code: string | null;
}

/** A manually-added non-flight transport leg (train, bus, ferry, car). */
export interface TripSegment {
  id: string;
  trip_id: string;
  type: SegmentType;
  operator: string | null;
  number: string | null;
  booking_reference: string | null;
  departure: SegmentPlace;
  departure_datetime: string;
  arrival: SegmentPlace;
  arrival_datetime: string;
  duration_minutes: number | null;
  seat: string | null;
  notes: string | null;
  created_by: number | null;
  created_by_username: string | null;
  created_at: string;
  updated_at: string;
}

export type StayKind = 'hotel' | 'airbnb' | 'hostel' | 'other';

/** Where a stay is. One place, unlike a segment's two.
 *
 * `address` is separate from `name` because they serve different readers: the
 * name titles the card, the address is what the calendar export puts in
 * LOCATION. `lat`/`lon` are null until the accommodation picker lands — a stay
 * without them is saved as text and left off the map. */
export interface StayPlace {
  name: string;
  address: string | null;
  lat: number | null;
  lon: number | null;
  timezone: string | null;
  /** ISO-3166-1 alpha-2 from the geocoder; null when typed by hand. */
  country_code: string | null;
}

/** A booked place to sleep: hotel, Airbnb, hostel.
 *
 * `check_in_date` / `check_out_date` are the local calendar dates at the
 * property, computed by the backend. Prefer them over slicing the datetimes:
 * a 15:00 check-in at UTC-10 is the *next* day in UTC, so the instants band
 * onto the wrong planner day. */
export interface TripStay {
  id: string;
  trip_id: string;
  kind: StayKind;
  place: StayPlace;
  check_in_datetime: string;
  check_in_date: string;
  check_out_datetime: string;
  check_out_date: string;
  nights: number | null;
  booking_reference: string | null;
  confirmation: string | null;
  contact: string | null;
  room_type: string | null;
  guests: number | null;
  notes: string | null;
  created_by: number | null;
  created_by_username: string | null;
  created_at: string;
  updated_at: string;
}

/** One geocoder candidate, from either the station or the place search. */
export interface PlaceResult {
  name: string;
  city: string;
  /** One-line street address; often "" for a station. */
  address: string;
  country: string;
  /** ISO-3166-1 alpha-2. Recorded on the saved place, and what makes it count
   * toward visited countries in Stats. */
  countrycode: string;
  /** 'place' is a mapped venue, 'address' a street. The picker groups on it. */
  category: 'place' | 'address';
  lat: number;
  lon: number;
}

/** Kept as the old name so existing station callers read unchanged. */
export type StationResult = PlaceResult;

export type PlaceInputKind = SegmentType | 'stay';

/** What PlaceInput hands back when the user picks a result or types freely. */
export interface PickedPlace {
  name: string;
  lat: number | null;
  lon: number | null;
  country_code: string | null;
  address: string | null;
}

export interface PackingItem {
  id: string;
  trip_id: string;
  text: string;
  checked: number;
  sort_order: number;
  created_by: number | null;
  created_at: string;
}

export interface Participant {
  type: 'user' | 'guest';
  id: number;
  name: string;
}

export interface TripExpense {
  id: string;
  trip_id: string;
  description: string;
  amount: number;
  currency: string;
  created_by: number | null;
  created_by_username: string | null;
  paid_by: Participant;
  participants: Participant[];
  created_at: string;
  updated_at: string;
}

export interface Guest {
  id: number;
  name: string;
  created_at: string;
}

export interface BalanceEntry {
  type: 'user' | 'guest';
  id: number;
  name: string;
  net: number;
}

export interface Balances {
  balances: Record<string, BalanceEntry[]>;
}

export interface TripShare {
  id: number;
  user_id: number;
  username: string;
  status: string;
  created_at: string;
}

export interface TripInvitation {
  id: number;
  trip_id: string;
  trip_name: string;
  invited_by_username: string;
  created_at: string;
}

export interface TrustedUser {
  user_id: number;
  username: string;
  created_at: string;
}

export interface Flight {
  id: string;
  user_id?: number | null;
  trip_id: string | null;
  flight_number: string;
  airline_code: string | null;
  airline_name: string | null;
  departure_airport: string;
  arrival_airport: string;
  departure_datetime: string | null;
  arrival_datetime: string | null;
  departure_timezone: string | null;
  arrival_timezone: string | null;
  departure_terminal: string | null;
  arrival_terminal: string | null;
  departure_gate: string | null;
  arrival_gate: string | null;
  duration_minutes: number | null;
  aircraft_type: string | null;
  aircraft_registration: string | null;
  seat: string | null;
  cabin_class: string | null;
  booking_reference: string | null;
  passenger_name: string | null;
  status: string | null;
  notes: string | null;
  email_subject: string | null;
  email_date: string | null;
  live_status: string | null;
  live_departure_delay: number | null;
  live_arrival_delay: number | null;
  live_departure_actual: string | null;
  live_arrival_estimated: string | null;
  live_status_fetched_at: string | null;
}

export interface Airport {
  iata_code: string;
  name: string;
  city_name: string | null;
  country_code: string | null;
  latitude: number | null;
  longitude: number | null;
}

export interface SyncStatus {
  status: 'idle' | 'running' | 'error';
  last_synced_at: string | null;
  last_error: string | null;
  sync_interval_minutes: number | null;
  emails_processed: number | null;
  emails_total: number | null;
}

export interface Settings {
  gmail_address: string | null;
  gmail_app_password_set: boolean;
  sync_interval_minutes: number;
  first_sync_days: number;
  imap_host: string;
  imap_port: number;
  smtp_server_enabled: boolean;
  smtp_domain: string;
  smtp_server_port?: number;        // admin only
  smtp_recipient_address: string;   // per-user
  smtp_allowed_senders: string;     // per-user
  immich_url: string;
  immich_api_key_set: boolean;
  default_currency: string;
}

export interface NotifPreferences {
  flight_reminder: boolean;
  checkin_reminder: boolean;
  trip_reminder: boolean;
  delay_alert: boolean;
  boarding_pass: boolean;
  new_flight: boolean;
}

export interface InAppNotification {
  id: number;
  type: string;
  title: string;
  body: string;
  url: string;
  read: boolean;
  created_at: string;
}

export interface BoardingPass {
  id: string;
  flight_id: string;
  passenger_name: string | null;
  seat: string | null;
  source_page: number;
  created_at: string;
}

export interface TripBoardingPass extends BoardingPass {
  flight_number: string | null;
  departure_airport: string | null;
  arrival_airport: string | null;
}

export interface TripDocument {
  id: string;
  trip_id: string;
  filename: string;
  mime_type: string;
  file_size: number;
  page_count: number;
  created_at: string;
}

export interface ImmichAlbumResponse {
  album_id: string;
  album_url: string | null;
  asset_count: number | null;
  already_exists: boolean;
}

export interface AircraftInfo {
  type_name: string | null;
  registration: string | null;
}

export interface EmailData {
  email_subject: string | null;
  html_body: string | null;
}

export interface PaginatedFlights {
  flights: Flight[];
  total: number;
  limit: number;
  offset: number;
}

export interface TripsListResponse {
  trips: Trip[];
}

export interface AirportCountResponse {
  count: number;
}


export interface TripDayNote {
  date: string;
  content: string;
  updated_at: string;
  updated_by_username: string | null;
}

export interface VersionInfo {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
}

/** Configuration state of one optional third-party integration.
 *
 * Carries no key material by design — only whether something is set and which
 * environment variable sets it. `state` distinguishes Photon's three cases,
 * where a plain configured/not answer would report the out-of-the-box public
 * instance as a deliberate choice.
 */
export interface IntegrationStatus {
  key: string;
  configured: boolean;
  state: 'set' | 'unset' | 'public_instance' | 'self_hosted' | 'disabled';
  env_var: string | null;
}
