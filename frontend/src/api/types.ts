// TypeScript interfaces matching the FastAPI backend response shapes

export interface User {
  id: string;
  username: string;
  is_admin: boolean;
  smtp_recipient_address: string | null;
  totp_enabled?: boolean;
  locale?: string;
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
  flights?: Flight[];
  immich_album_id?: string | null;
  is_owner?: boolean;
  owner_username?: string | null;
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
}

export interface Settings {
  gmail_address: string | null;
  gmail_app_password_set: boolean;
  sync_interval_minutes: number;
  max_emails_per_sync: number;
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
}

export interface NotifPreferences {
  flight_reminder: boolean;
  checkin_reminder: boolean;
  trip_reminder: boolean;
  delay_alert: boolean;
  boarding_pass: boolean;
  new_flight: boolean;
  failed_parse: boolean;
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

export interface FailedEmail {
  id: string;
  sender: string;
  subject: string;
  received_at: string | null;
  reason: string;
  airline_hint: string;
  last_retried_at: string | null;
  parser_version: string;
  created_at: string;
}

export interface AdminFailedEmailGroup {
  sender_domain: string;
  count: number;
  latest: string;
}

export interface TripDayNote {
  date: string;
  content: string;
  updated_at: string;
  updated_by_username: string | null;
}
