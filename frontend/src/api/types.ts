// TypeScript interfaces matching the FastAPI backend response shapes

export interface Trip {
  id: number;
  name: string;
  start_date: string | null;
  end_date: string | null;
  origin_airport: string | null;
  destination_airport: string | null;
  booking_refs: string[];
  flight_count?: number;
  flights?: Flight[];
}

export interface Flight {
  id: number;
  trip_id: number | null;
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
}

export interface Settings {
  gmail_address: string | null;
  gmail_app_password_set: boolean;
  sync_interval_minutes: number;
  imap_host: string;
  imap_port: number;
  smtp_server_enabled: boolean;
  smtp_server_port: number;
  smtp_recipient_address: string;
  smtp_allowed_senders: string;
}

export interface AircraftInfo {
  type_name: string | null;
  registration: string | null;
}

export interface EmailData {
  email_subject: string | null;
  html_body: string | null;
}

export interface TripsListResponse {
  trips: Trip[];
}

export interface AirportCountResponse {
  count: number;
}
